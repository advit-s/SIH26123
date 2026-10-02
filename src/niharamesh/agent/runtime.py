"""The per-robot runtime: planner + task agent + coordinator + safety gate.

One class per robot. It owns exactly one robot's decisions and nothing else. It
cannot see another robot's exact pose, and it cannot grant itself authority: it
collects every grant itself, through the coordination protocol, and refuses to
move until the complete set is durable.

The loop, once per control period:

1. Read its own :class:`Observation` from the world. Never anyone's else.
2. Refresh the coordinator and the allocator with peer messages.
3. Decide the current subgoal (drive / queue at a zone / service / wait).
4. Acquire zone authority if the next segment needs it.
5. Turn the plan into a velocity command, and hand that command to the safety
   gate. The gate can veto. A veto is recorded with its reason and is visible in
   the inspector.

Everything this class decides is explainable: it keeps the *why* alongside the
*what*, because "why is this robot waiting" is the question an operator actually
asks.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from niharamesh.allocation.auction import LocalAuction
from niharamesh.clocks import Clock
from niharamesh.coordination.protocol import ZoneProtocol
from niharamesh.coordination.requester import AdmissionContext
from niharamesh.domain.coordination import AcquisitionPhase, PeerMessage
from niharamesh.domain.geometry import OrientedBox, Pose, aabb_overlap, bbox_of
from niharamesh.domain.identity import Membership, RobotIdentity, RobotSession
from niharamesh.domain.map import Obstacle, Station, WarehouseMap
from niharamesh.domain.pose import Footprint, MotionCommand, Pose2, StopReason
from niharamesh.domain.scenario import Scenario
from niharamesh.domain.task import TaskState, is_legal_task_transition
from niharamesh.domain.units import TimeDomain, wrap_angle
from niharamesh.persistence.journal import SqliteAuthorityJournal
from niharamesh.planning.astar import AStarPlanner, PathStatus
from niharamesh.planning.grid import OccupancyGrid
from niharamesh.ports import FreshnessVerdict, Observation, SafetyDecision
from niharamesh.safety.gate import GateContext, SafetyGate

__all__ = [
    "AUTHORITY_PHASES",
    "AgentPhase",
    "RobotAgent",
    "TaskProgress",
    "WhyWaiting",
    "ZoneEvidence",
]

#: Phases in which this robot *retains* authority over its zone.
#:
#: ``GRANTED`` is granted-and-entering, ``OCCUPIED`` is physically inside, and
#: ``RELEASING`` is declared-releasing but not yet reconciled. The last one is the
#: important one: a release is a promise that the body will come out, not proof
#: that it has, so authority survives it (invariant 4, ADR 0005).
AUTHORITY_PHASES: frozenset[AcquisitionPhase] = frozenset(
    {
        AcquisitionPhase.GRANTED,
        AcquisitionPhase.OCCUPIED,
        AcquisitionPhase.RELEASING,
    }
)


class AgentPhase(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    SEEKING_PICKUP = "seeking_pickup"
    QUEUED_FOR_ZONE = "queued_for_zone"
    TRAVERSING = "traversing"
    SERVICING = "servicing"
    WAITING = "waiting"
    STOPPED = "stopped"
    UNREACHABLE = "unreachable"


@dataclass(slots=True)
class WhyWaiting:
    """The operator-facing explanation for a stop.

    Empty fields are ``None`` rather than empty strings, so the UI can tell
    "not waiting" from "waiting with no reason", which is a defect.
    """

    waiting: bool = False
    reason: str = ""
    blocking_resource: str | None = None
    blocking_peer: str | None = None
    evidence_age_s: float | None = None
    recovery_condition: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "waiting": self.waiting,
            "reason": self.reason,
            "blocking_resource": self.blocking_resource,
            "blocking_peer": self.blocking_peer,
            "evidence_age_s": self.evidence_age_s,
            "recovery_condition": self.recovery_condition,
        }


@dataclass(slots=True)
class TaskProgress:
    task_id: str | None = None
    state: TaskState = TaskState.AVAILABLE
    carrying: bool = False
    completion_credited: bool = False
    unreachable_reason: str | None = None
    transitions: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ZoneEvidence:
    """Exactly what this robot tells the safety gate about zones, and why.

    Published rather than kept private because it is the honest answer to an
    operator's question -- "what does this robot *think* it is allowed to do in
    that aisle?" -- and because a cockpit that re-derives it would be building a
    second, divergent opinion. :meth:`RobotAgent.tick` builds the gate context
    from this object, so the displayed evidence and the enforced evidence cannot
    drift apart.
    """

    #: This robot's own chassis body, from its own pose estimate.
    body: OrientedBox
    #: The zone whose protected geometry contains ``body`` right now.
    occupied_zone: str | None
    #: The zone for which complete, durable GRANTED entry permission is live.
    entry_permission: str | None
    #: The zone whose authority this robot retains.
    zone_authority: str | None
    #: The conservative body this command could occupy before it stops.
    swept_body: OrientedBox | None
    #: One line, operator-facing. Empty when nothing is contentious.
    detail: str = ""


class RobotAgent:
    """One robot's independent decision process.

    Deliberately constructed with only what a robot legitimately has: its own
    identity, its own session, the immutable shared map, its own journal, and the
    membership set. There is no parameter through which another robot's truth
    could arrive.
    """

    def __init__(
        self,
        *,
        identity: RobotIdentity,
        session: RobotSession,
        scenario: Scenario,
        membership: Membership,
        clock: Clock,
        run_id: str,
        session_registry: Callable[[str], str | None] | None = None,
        journal_path: str | None = None,
    ) -> None:
        self.identity = identity
        self.session = session
        self.scenario = scenario
        self.membership = membership
        self.clock = clock
        self.run_id = run_id

        self.warehouse_map: WarehouseMap = scenario.map
        # An in-memory journal by default. A real process mode passes a durable
        # path; the harness deliberately keeps the journal ephemeral because the
        # *durability* guarantee is exercised by the journal's own tests and by
        # the three-process network test, not by repeating it per harness run.
        self.journal = SqliteAuthorityJournal(
            path=journal_path or ":memory:",
            robot_id=identity.robot_id,
            session_id=session.session_id,
        )
        #: One number, used by both the gate and the admission callback below.
        #: Duplicating it would let admission and actuation disagree about what
        #: "too little battery" means.
        self._minimum_battery = 0.10
        self.gate = SafetyGate(
            config=scenario.simulation,
            warehouse_map=self.warehouse_map,
            robot_id=identity.robot_id,
            minimum_battery=self._minimum_battery,
        )

        clearance = identity.footprint.clearance_radius_m()
        self.grid = OccupancyGrid.from_map(self.warehouse_map, clearance_m=clearance, zones_blocking=False)
        self.planner = AStarPlanner(self.grid)

        self.coordinator = ZoneProtocol(
            robot_id=identity.robot_id,
            session_id=session.session_id,
            membership=membership,
            journal=self.journal,
            warehouse_map=self.warehouse_map,
            timing=scenario.simulation.protocol,
            time_domain=TimeDomain.LOGICAL,
            # Admission needs each admitted peer's *current* session so a request
            # from a superseded boot is refused rather than merged. Without it the
            # voter cannot distinguish a live peer from a stale one, and would have
            # to either trust everything or refuse everything.
            session_registry=session_registry,
            # A real local safety callback. The coordinator's own default refuses
            # every entry, which is the correct default and is left alone; without
            # this the protocol would reach GRANTED and then stop forever, because
            # nothing in the process could ever supply the missing local evidence.
            # It answers only from this robot's own evidence -- see
            # ``_admission_safety``.
            safety_check=self._admission_safety,
        )
        # A fresh coordinator refuses to grant or enter until it has re-derived its
        # own durable promises. That refusal is deliberate: assuming an empty
        # journal would be exactly the "forgot a promise and resumed normal
        # operation" failure the protocol exists to prevent. So the agent must
        # *start* it before it can act.
        self.recovery_state = self.coordinator.start()
        self.auction = LocalAuction(
            robot_id=identity.robot_id,
            robot_session=session.session_id,
            run_id=run_id,
            epoch=membership.epoch,
            membership=membership,
            capacity=1,
        )

        self.phase = AgentPhase.IDLE
        self.why = WhyWaiting()
        self.progress = TaskProgress()
        self.plan: tuple[tuple[float, float], ...] = ()
        self.plan_version = 0
        self._goal: tuple[float, float] | None = None
        self._zone_in_progress: str | None = None
        self._command_seq = 0
        #: Nanoseconds since the previous **tick** of this control loop, measured
        #: before the current tick overwrites it. Deliberately a separate field
        #: from the last *permitted command*: a veto is still a tick, and a
        #: veto-every-tick loop must never be reported as stalled (contract A4).
        #: A loop that genuinely has not run reports its true gap on its first
        #: tick back and fails closed once, then re-arms -- which is what failing
        #: closed has to mean for a stall detector that must also recover.
        self._last_tick_ns: int | None = None
        self._control_loop_age_ns: int = 0
        self._service_until_ns: int | None = None
        self._pending_peer_intents: dict[str, FreshnessVerdict] = {}
        self._peer_state_age: dict[str, float | None] = {}
        self._last_decision: SafetyDecision | None = None
        self._last_gate_decision: SafetyDecision | None = None
        self._last_intent_freshness: FreshnessVerdict | None = None
        #: This tick's own observation. The admission callback runs inside
        #: ``coordinator.tick`` and ``may_enter``, both of which happen during
        #: ``tick``, so the evidence must be published *before* they are reached.
        self._latest_observation: Observation | None = None
        self.zone_evidence: ZoneEvidence | None = None
        self.stop_reason: StopReason = StopReason.NONE

        fixed = scenario.start_of(identity.robot_id).assigned_task_id
        if fixed is not None:
            self.progress.task_id = fixed
            self.progress.state = TaskState.CLAIMED

    # ------------------------------------------------------------------ peer

    def ingest(self, message: PeerMessage) -> None:
        """Apply one genuine peer message.

        Both subsystems validate identity, epoch and session themselves, so a
        message that either rejects is rejected for them too rather than being
        quietly forwarded.
        """
        self.coordinator.ingest(message)
        self.auction.handle(message)

    def note_peer_freshness(self, peer_id: str, verdict: FreshnessVerdict) -> None:
        self._pending_peer_intents[peer_id] = verdict

    def note_intent_freshness(self, verdict: FreshnessVerdict | None) -> None:
        self._last_intent_freshness = verdict

    # ------------------------------------------------------------------ loop

    def tick(self, observation: Observation) -> MotionCommand:
        """One control period. Returns the command the gate permitted."""
        now = observation.sim_time_ns
        # Contract A4: measure the gap since the previous *tick*, before this one
        # overwrites it. A live loop reports ~0 and is never falsely latched as
        # stalled; a loop that genuinely has not run for longer than the stall
        # bound reports that gap on its first tick back and fails closed once.
        self._control_loop_age_ns = 0 if self._last_tick_ns is None else max(0, now - self._last_tick_ns)
        self._last_tick_ns = now
        # Published before anything that can consult it: the coordinator's
        # admission callback is about to be reached.
        self._latest_observation = observation
        # The planner is local, so it must be told where *this* robot is from this
        # robot's own pose estimate. It is never allowed to guess, and it never
        # sees another robot's position.
        self.planner.set_current_pose(observation.pose_estimate.pose)
        self.coordinator.tick(now)
        self.auction.tick(now)
        self._advance_task_state(now)

        decision = self._decide(observation, now)
        command = self._to_command(observation, decision, now)
        self._last_decision = decision
        return command

    def _advance_task_state(self, now_ns: int) -> None:
        if self._service_until_ns is not None and now_ns >= self._service_until_ns:
            self._service_until_ns = None
            self._transition(TaskState.DELIVERED if self.progress.carrying else TaskState.PICKUP_CONFIRMED)

    def _transition(self, nxt: TaskState) -> None:
        if not is_legal_task_transition(self.progress.state, nxt):
            # A refused transition is recorded, never forced. Forcing one is how a
            # duplicate delivery manufactures a second completion credit.
            self.progress.transitions.append(f"refused:{self.progress.state.value}->{nxt.value}")
            return
        self.progress.transitions.append(f"{self.progress.state.value}->{nxt.value}")
        self.progress.state = nxt

    def _decide(self, observation: Observation, now_ns: int) -> SafetyDecision:
        """Choose a phase and build the gate context. Pure decision, no motion."""
        pose = observation.pose_estimate.pose
        station = self._next_station()

        if station is None:
            self.phase = AgentPhase.WAITING
            self.why = WhyWaiting(
                waiting=True,
                reason="no reachable task remains for this robot",
                recovery_condition="a new task is released and won in a later round",
            )
            return SafetyDecision(False, StopReason.SCHEDULED_STOP, "workload_complete_for_me")

        goal = (station.pose.x, station.pose.y)
        if self._goal != goal or not self.plan:
            waypoints = self.planner.plan(goal, self.identity.footprint)
            # `plan` returns None for every failure and cannot carry a reason, so
            # the reason is read from the planner's own result. Reading None as
            # "unreachable" would discard the distinction between an unreachable
            # goal, a blocked start and an exhausted search budget.
            result = self.planner.last_result
            if not waypoints or result is None or result.status is not PathStatus.OK:
                detail = ""
                if result is not None:
                    detail = result.reason or str(result.unreachable_reason or "")
                self.phase = AgentPhase.UNREACHABLE
                self.progress.unreachable_reason = detail or "planner returned no result"
                self.why = WhyWaiting(
                    waiting=True,
                    reason=f"destination unreachable: {detail or 'planner returned no result'}",
                    recovery_condition="a human edits the scenario; the robot will not improvise",
                )
                return SafetyDecision(False, StopReason.SCHEDULED_STOP, "unreachable_goal")
            self.plan = tuple(waypoints)
            self.plan_version += 1
            self._goal = goal

        upcoming = self._next_zone_ahead(pose)
        if upcoming is not None and not self._zone_authority_ok(upcoming):
            active = self.coordinator.requester.active
            if active is not None and active.zone_id != upcoming:
                # Invariant 6: at most one outstanding grant per robot, globally. A
                # robot that already holds authority for one zone cannot open a
                # transaction for another -- the requester refuses, and correctly so.
                # The runtime has to respect that rather than discover it.
                self._zone_in_progress = upcoming
                self.phase = AgentPhase.QUEUED_FOR_ZONE
                self.why = WhyWaiting(
                    waiting=True,
                    reason=(
                        f"holding authority for {active.zone_id}; one outstanding grant "
                        f"per robot, so {upcoming} cannot be requested until it is released"
                    ),
                    blocking_resource=active.zone_id,
                    recovery_condition=(f"reconciled release of {active.zone_id}, then acquire {upcoming}"),
                )
                return SafetyDecision(
                    False,
                    StopReason.ZONE_AUTHORITY_MISSING,
                    f"busy_holding:{active.zone_id}",
                )
            # Begin an acquisition only once. Re-issuing it every tick would open a
            # second outstanding transaction, which is exactly what the
            # single-outstanding-grant invariant forbids.
            if not self._acquiring(upcoming):
                self.coordinator.begin_acquire(upcoming)
            self._zone_in_progress = upcoming
            self.phase = AgentPhase.QUEUED_FOR_ZONE
            blocked = self.coordinator.why_blocked(upcoming)
            self.why = WhyWaiting(
                waiting=True,
                reason=blocked,
                blocking_resource=upcoming,
                recovery_condition=f"the complete grant set for {upcoming}, or the zone fenced",
            )
            return SafetyDecision(False, StopReason.ZONE_AUTHORITY_MISSING, f"awaiting:{upcoming}")

        if self._service_until_ns is not None:
            self.phase = AgentPhase.SERVICING
            self.why = WhyWaiting()
            return SafetyDecision(False, StopReason.SCHEDULED_STOP, "servicing")

        self.phase = AgentPhase.TRAVERSING
        self.why = WhyWaiting()
        return SafetyDecision(True, StopReason.NONE)

    def _acquiring(self, zone_id: str) -> bool:
        """True when this robot already has an outstanding transaction for *zone_id*.

        Read from the requester's own active acquisition rather than inferred from
        a phase name, so the check cannot drift out of step with the protocol.
        """
        active = self.coordinator.requester.active
        return active is not None and active.zone_id == zone_id

    def authority_zone(self) -> str | None:
        """The zone whose authority this robot **retains**, if any.

        Retained authority is granted-and-entering, physically occupied, or
        releasing-but-not-reconciled. It deliberately survives
        :meth:`~niharamesh.coordination.protocol.ZoneProtocol.may_enter` going
        false once the body is inside: "may I cross this boundary" and "am I
        responsible for this aisle" stop being the same question at the moment of
        entry, and collapsing them is how an occupied aisle gets quietly emptied.
        """
        acq = self.coordinator.requester.active
        if acq is None or acq.phase not in AUTHORITY_PHASES:
            return None
        return acq.zone_id

    def entry_permission(self) -> str | None:
        """The zone for which complete, durable GRANTED entry permission is live.

        Only ever ``GRANTED``: once the body is inside, the grant set has been
        spent on entry and the remaining question is retained authority, which is
        :meth:`authority_zone`.
        """
        acq = self.coordinator.requester.active
        if acq is None or acq.phase is not AcquisitionPhase.GRANTED:
            return None
        try:
            return acq.zone_id if self.coordinator.may_enter(acq.zone_id) else None
        except (KeyError, ValueError):
            return None

    def _zone_authority_ok(self, zone_id: str) -> bool:
        """True when this robot may move through *zone_id*'s protected geometry.

        Retained authority, not entry permission: a robot already inside a zone it
        holds must be able to finish crossing it, which is the whole point of
        retaining occupancy.
        """
        return self.authority_zone() == zone_id

    def _next_station(self) -> Station | None:
        """Where this robot is trying to go right now, given its custody."""
        if self.progress.task_id is None:
            return None
        task = self.scenario.task(self.progress.task_id)
        if self.progress.carrying:
            try:
                return self.warehouse_map.station(task.drop_station_id)
            except KeyError:
                return None
        try:
            return self.warehouse_map.station(task.pickup_station_id)
        except KeyError:
            return None

    def _next_zone_ahead(self, pose: Pose2) -> str | None:
        """First zone the remaining path brings this robot *near enough* to enter.

        "Near enough" is deliberately the same conservative margin the safety gate
        uses to decide that a command is entering protected geometry. If the two
        disagreed the robot would freeze permanently: the runtime would believe it
        needs no authority while the gate vetoed every non-zero command for want of
        it, and a refusal that never clears is indistinguishable from a fault.
        Agreement between the decider and the veto point is what makes the
        difference a queue rather than a deadlock.
        """
        margin = self._conservative_margin_m()
        for x, y in self.plan:
            bounds = _inflated_bounds(x, y, self.identity.footprint, margin)
            for zone in self.warehouse_map.zones:
                if aabb_overlap(bounds, zone.protected_bounds) and not self._zone_authority_ok(zone.id):
                    return zone.id
        del pose
        return None

    # ------------------------------------------------------- zone evidence

    def zone_evidence_for(self, observation: Observation) -> ZoneEvidence:
        """The four zone facts this robot reports to the gate, and why.

        Built entirely from this robot's own pose estimate, its own footprint, its
        own command budget and its own coordinator state. No peer pose, no
        evaluator truth. :meth:`tick` fills the gate context from exactly this
        object, so what an operator is shown and what the gate enforced are the
        same statement.
        """
        pose = observation.pose_estimate.pose
        body = self.identity.footprint.body_at(Pose(pose.x, pose.y, pose.theta))
        occupied = self._occupied_zone(body)
        authority = self.authority_zone()
        permission = self.entry_permission()
        detail = ""
        if occupied is not None and authority != occupied:
            detail = (
                f"inside {occupied} without retained authority; "
                "occupancy is retained until a reconciled release"
            )
        elif permission is not None:
            detail = f"complete grant set for {permission}; entry permitted"
        return ZoneEvidence(
            body=body,
            occupied_zone=occupied,
            entry_permission=permission,
            zone_authority=authority,
            swept_body=body.inflated(self._conservative_margin_m()),
            detail=detail,
        )

    def _occupied_zone(self, body: OrientedBox) -> str | None:
        """The zone whose protected geometry contains this body *right now*.

        The body is inflated only by this observation's own localisation
        uncertainty, not by the command's reach: "where am I" is a different
        question from "where could this command take me", and answering the second
        with the first is how a robot twelve metres away ends up reported as
        occupying an aisle it has never entered.

        Returns the alphabetically first match rather than an arbitrary one, so a
        body that genuinely straddles two protected regions is reported the same
        way on every tick.
        """
        margin = self._uncertainty_margin_m()
        bounds = bbox_of(body.inflated(margin))
        for zone in sorted(self.warehouse_map.zones, key=lambda z: z.id):
            if aabb_overlap(bounds, zone.protected_bounds):
                return zone.id
        return None

    def _uncertainty_margin_m(self) -> float:
        """Conservative planar bound from this tick's own localisation uncertainty.

        Never silently zero. An estimate that declares *no* uncertainty model gets
        the declared stopping budget, which is the only number in the
        configuration that is honestly conservative rather than optimistic.
        """
        observation = self._latest_observation
        if observation is None:
            return self.scenario.simulation.stopping.total_distance_m
        uncertainty = observation.pose_estimate.uncertainty
        if uncertainty.kind == "hard_bound":
            return max(0.0, uncertainty.max_m)
        if uncertainty.kind == "gaussian_sigma":
            # Three sigma is a declared, ordinary choice for a bounded operational
            # envelope. It is a configured assumption, not a measurement.
            return 3.0 * uncertainty.sigma_m
        return self.scenario.simulation.stopping.total_distance_m

    def _conservative_margin_m(self) -> float:
        """Total inflation applied to this robot's body for a zone decision.

        Localisation uncertainty plus the declared actuator reach over one command
        TTL: the distance it can travel under the command, the analytic braking
        reach ``v**2 / (2a)`` that follows when the command expires, and the arc a
        corner sweeps while turning. All four contributions are *configured
        assumptions* taken from the declared models, never measured quantities.
        """
        actuator = self.scenario.simulation.actuator
        speed = actuator.max_linear_mps
        ttl = actuator.command_ttl_s
        reach = speed * ttl + self._stopping_reach_m(speed)
        spin = min(math.pi, actuator.max_angular_radps * ttl)
        sweep = self.identity.footprint.half_diagonal_m * (1.0 - math.cos(spin))
        return self._uncertainty_margin_m() + reach + sweep

    def _stopping_reach_m(self, speed_mps: float) -> float:
        """Analytic braking reach ``v**2 / (2a)`` at the declared deceleration.

        The same formula the evaluator uses to check a measured stop against, so
        the gate's conservatism and the audit of that gate cannot be two different
        numbers by accident.
        """
        decel = self.scenario.simulation.actuator.decel_mps2
        if decel <= 0.0:  # pragma: no cover - constrained to gt=0 by ActuatorModel
            return 0.0
        return (speed_mps * speed_mps) / (2.0 * decel)

    def _to_command(self, observation: Observation, decision: SafetyDecision, now_ns: int) -> MotionCommand:
        """Turn a decision into a command, then let the gate have the last word."""
        pose = observation.pose_estimate.pose
        # Contract A3: the agent's own refusal is a decision, not advice. A robot
        # that just decided it must not move -- queued for a zone it does not hold,
        # servicing a station, waiting for work -- must not have that decision
        # discarded and replaced with a full-speed pursuit. It used to be, and the
        # gate's zone check was simultaneously satisfied by naming a zone ten
        # metres away, so the two together drove a robot through an aisle it had
        # never been granted.
        requested_v, requested_omega = self._pursue(pose) if decision.permitted else (0.0, 0.0)

        candidate = MotionCommand(
            robot_id=self.identity.robot_id,
            command_seq=self._command_seq,
            linear_mps=requested_v,
            angular_radps=requested_omega,
            issued_at_ns=now_ns,
            expires_at_ns=now_ns + int(self.scenario.simulation.actuator.command_ttl_s * 1e9),
            time_domain=TimeDomain.LOGICAL,
        )

        evidence = self.zone_evidence_for(observation)
        self.zone_evidence = evidence
        context = self._gate_context(observation, evidence, now_ns, candidate)

        # A stop is still a command and still has to be attributable, so it is
        # offered to the gate even when the agent produced it.
        final = self.gate.evaluate(candidate, now_ns, context)
        self._command_seq += 1
        if final.permitted:
            if not decision.permitted:
                # The gate had no reason to refuse, because the agent had already
                # removed the motion. Report the agent's reason rather than the
                # gate's silence, or an operator is told "nothing" while a robot
                # stands still.
                self.stop_reason = decision.reason
            else:
                self.stop_reason = StopReason.NONE
            self._last_gate_decision = final
            return candidate

        # Refused. Braking is longitudinal: a zero *requested* velocity is not
        # instantaneous rest, and it is emphatically not a licence to stop steering.
        # Zeroing the angular command as well strands a robot that is pointed at a
        # shelf it cannot reverse away from -- it may not translate, so it may not
        # turn, so it stays pointed at the shelf forever. So the pivot is offered to
        # the gate as its own command and gets its own decision.
        pivot = candidate.model_copy(update={"linear_mps": 0.0, "angular_radps": requested_omega})
        pivot_context = self._gate_context(observation, evidence, now_ns, pivot)
        pivot_verdict = self.gate.evaluate(pivot, now_ns, pivot_context)
        self._last_gate_decision = pivot_verdict if pivot_verdict.permitted else final
        self.stop_reason = final.reason
        if pivot_verdict.permitted:
            return pivot
        return candidate.model_copy(update={"linear_mps": 0.0, "angular_radps": 0.0})

    def _gate_context(
        self,
        observation: Observation,
        evidence: ZoneEvidence,
        now_ns: int,
        command: MotionCommand,
    ) -> GateContext:
        """Assemble everything the gate is allowed to know, and nothing else."""
        del command  # the gate receives the command as its first argument
        return GateContext(
            observation=observation,
            now_ns=now_ns,
            zone_authority=evidence.zone_authority,
            entry_permission=evidence.entry_permission,
            occupied_zone=evidence.occupied_zone,
            occupied_box=evidence.body,
            swept_body=evidence.swept_body,
            peer_freshness=dict(self._pending_peer_intents),
            intent_freshness=self._last_intent_freshness,
            battery_fraction=observation.battery_fraction,
            control_loop_age_ns=self._control_loop_age_ns,
            obstacle_distance_m=self._forward_clearance_m(observation),
        )

    def _forward_clearance_m(self, observation: Observation) -> float | None:
        """Nearest thing ahead of this robot, from **this robot's own scan**.

        Directional on purpose. The gate compares this against a *longitudinal*
        stopping budget, so a lateral measurement would be the wrong quantity: it
        compared an all-direction nearest obstacle against the budget and refused a
        robot driving parallel to a shelf 0.26 m away, which is not a stopping
        hazard at all.

        The bearings are **world-frame**, so they must be expressed relative to this
        robot's own heading before being tested against the forward half-plane.
        Filtering them without that conversion measures the wedge around the world
        ``+x`` axis, which is not a direction this robot is ever pointing in -- an
        earlier version of this method did exactly that and silently reported no
        evidence at all for any robot not facing east.

        ``None`` when the scan carries no ray ahead of the body, which the gate treats
        as "no evidence" rather than "nothing there". No measurement is invented to
        fill a gap.
        """
        heading = observation.pose_estimate.pose.theta
        ahead = [
            ray
            for ray in observation.sensor.rays
            if abs(wrap_angle(ray.bearing_rad - heading)) <= math.pi / 2.0
        ]
        if not ahead:
            return None
        return min(ray.distance_m for ray in ahead)

    # ---------------------------------------------------- admission evidence

    def _admission_safety(self, context: AdmissionContext) -> tuple[bool, str]:
        """Local safety evidence for entry into *context*'s zone.

        Wired into :class:`~niharamesh.coordination.protocol.ZoneProtocol` in place
        of its deliberately refusing default, which is why a complete grant set can
        ever become entry permission at all.

        What it may read: this tick's own observation, its localiser age, its scan,
        its battery, this robot's footprint, its own local plan, and the *static*
        shared map every agent legitimately holds.

        What it must not read: ``may_enter``, the grant set, peer state, or any
        other output of the entry decision it is being asked to make. Grants are
        the protocol's answer to "may anybody else be relying on me"; this callback
        answers the separate question "can this robot physically and safely get
        in from where it is standing". Confusing the two is circular, and would
        either deadlock or launder a grant into a safety argument.

        Two geometric checks, both about *this* robot and the *static* map:

        * the traversal the zone declares -- entry pose to exit pose -- must be
          clear of static geometry for this footprint. That is the part of the
          journey the localiser cannot re-plan around once it is inside;
        * this robot's current body must have its declared stopping budget of
          clearance from static geometry, so it is not opening a transaction while
          already committed to braking.

        It deliberately does **not** draw a straight line from the current pose to
        the entry pose. The robot follows its own A* path, not a chord; a chord
        across a shelving aisle describes a segment the robot will never drive, and
        refusing on it froze a perfectly legal approach for as long as the hold
        lasted.

        It returns ``(False, reason)`` whenever the answer is not demonstrable.
        Absence of evidence is not evidence of safety.
        """
        observation = self._latest_observation
        if observation is None:
            return False, "no local observation has been published for this tick"
        if observation.localisation_stale:
            return False, f"localisation is {observation.localisation_age_ns / 1e9:.3f}s old"
        if observation.sensor.dropped:
            return False, "this control period's sensor scan was dropped"
        battery = observation.battery_fraction
        if battery is not None and battery < self._minimum_battery:
            return False, f"battery {battery:.3f} is below the {self._minimum_battery:.2f} reserve"

        traversal = _inflated_segment_bounds(
            context.entry_pose[0],
            context.entry_pose[1],
            context.exit_pose[0],
            context.exit_pose[1],
            self.identity.footprint,
            self._uncertainty_margin_m(),
        )
        blockers = self._static_blockers_in(traversal)
        if blockers:
            return False, (f"the declared traversal of {context.zone_id} runs through {', '.join(blockers)}")

        pose = observation.pose_estimate.pose
        body = self.identity.footprint.body_at(Pose(pose.x, pose.y, pose.theta))
        gap = self.gate.nearest_obstacle_m(body)
        budget = self.scenario.simulation.stopping.total_distance_m
        if gap is not None and gap < budget:
            return False, (
                f"only {gap:.3f} m of static clearance at this pose, "
                f"and the declared stopping budget is {budget:.3f} m"
            )
        return True, f"local evidence admits entry into {context.zone_id}"

    def _static_blockers_in(self, bounds: tuple[float, float, float, float]) -> tuple[str, ...]:
        """Ids of static obstacles overlapping *bounds*, in a stable order."""
        return tuple(
            obstacle.id
            for obstacle in sorted(self.warehouse_map.obstacles, key=lambda o: o.id)
            if aabb_overlap(bounds, bbox_of(_obstacle_box(obstacle)))
        )

    def inspect_zone_evidence(self) -> dict[str, object]:
        """Operator-facing view of the evidence the gate was given last tick."""
        evidence = self.zone_evidence
        if evidence is None:
            return {
                "occupied_zone": None,
                "entry_permission": None,
                "zone_authority": None,
                "detail": "no command has been produced yet",
            }
        return {
            "occupied_zone": evidence.occupied_zone,
            "entry_permission": evidence.entry_permission,
            "zone_authority": evidence.zone_authority,
            "detail": evidence.detail,
        }

    def _pursue(self, pose: Pose2) -> tuple[float, float]:
        """Pure pursuit along the plan, clamped to the declared limits."""
        if not self.plan:
            return 0.0, 0.0
        target = self.plan[0]
        dx, dy = target[0] - pose.x, target[1] - pose.y
        distance = math.hypot(dx, dy)
        if distance < 0.15:
            if len(self.plan) == 1:
                return 0.0, 0.0
            self.plan = self.plan[1:]
            return self._pursue(pose)
        heading = math.atan2(dy, dx)
        error = (heading - pose.theta + math.pi) % (2 * math.pi) - math.pi
        actuator = self.scenario.simulation.actuator
        speed = min(actuator.max_linear_mps, max(0.0, 0.25 * math.cos(error) / max(distance, 0.05)))
        omega = max(-actuator.max_angular_radps, min(actuator.max_angular_radps, 2.0 * error))
        return speed, omega

    # ------------------------------------------------------------ inspection

    def inspect(self) -> dict[str, object]:
        """A snapshot for the cockpit. Read-only; holds no authority."""
        return {
            "robot_id": self.identity.robot_id,
            "session_id": self.session.session_id,
            "phase": self.phase.value,
            "plan_version": self.plan_version,
            "plan_length": len(self.plan),
            "goal": list(self._goal) if self._goal else None,
            "task": {
                "task_id": self.progress.task_id,
                "state": self.progress.state.value,
                "carrying": self.progress.carrying,
                "completion_credited": self.progress.completion_credited,
                "unreachable_reason": self.progress.unreachable_reason,
                "transitions": list(self.progress.transitions[-8:]),
            },
            "zone_in_progress": self._zone_in_progress,
            "zone_evidence": self.inspect_zone_evidence(),
            "why_waiting": self.why.as_dict(),
            "stop_reason": self.stop_reason.value,
            "gate_constraint": (
                "" if self._last_gate_decision is None else self._last_gate_decision.limiting_constraint
            ),
            "gate_permitted": None
            if self._last_gate_decision is None
            else self._last_gate_decision.permitted,
            "journal_healthy": self.journal.healthy,
        }

    def close(self) -> None:
        self.journal.close()


def _inflated_bounds(
    x: float, y: float, footprint: Footprint, margin: float
) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of *footprint* centred at ``(x, y)``, inflated.

    Heading is deliberately ignored. A waypoint is a position, not a heading, and
    assuming the worst orientation for an axis-aligned test costs a few
    millimetres and removes a whole class of "the plan and the gate disagreed"
    bug.
    """
    half_long = footprint.length_m / 2.0 + margin
    half_wide = footprint.width_m / 2.0 + margin
    return (x - half_long, y - half_wide, x + half_long, y + half_wide)


def _inflated_segment_bounds(
    x0: float, y0: float, x1: float, y1: float, footprint: Footprint, margin: float
) -> tuple[float, float, float, float]:
    """Bounds of the corridor between two points for an inflated footprint."""
    half_long = footprint.length_m / 2.0 + margin
    half_wide = footprint.width_m / 2.0 + margin
    return (
        min(x0, x1) - half_long,
        min(y0, y1) - half_wide,
        max(x0, x1) + half_long,
        max(y0, y1) + half_wide,
    )


def _obstacle_box(obstacle: Obstacle) -> OrientedBox:
    """The occupied geometry of a static map obstacle."""
    return OrientedBox(
        obstacle.pose.x,
        obstacle.pose.y,
        obstacle.pose.theta,
        obstacle.length_m,
        obstacle.width_m,
    )

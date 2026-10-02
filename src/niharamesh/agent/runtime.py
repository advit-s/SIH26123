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
from niharamesh.domain.coordination import PeerMessage
from niharamesh.domain.geometry import Pose
from niharamesh.domain.identity import Membership, RobotIdentity, RobotSession
from niharamesh.domain.map import Station, WarehouseMap
from niharamesh.domain.pose import MotionCommand, Pose2, StopReason
from niharamesh.domain.scenario import Scenario
from niharamesh.domain.task import TaskState, is_legal_task_transition
from niharamesh.domain.units import TimeDomain
from niharamesh.persistence.journal import SqliteAuthorityJournal
from niharamesh.planning.astar import AStarPlanner, PathStatus
from niharamesh.planning.grid import OccupancyGrid
from niharamesh.ports import FreshnessVerdict, Observation, SafetyDecision
from niharamesh.safety.gate import GateContext, SafetyGate

__all__ = ["AgentPhase", "RobotAgent", "TaskProgress", "WhyWaiting"]


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
        self.gate = SafetyGate(
            config=scenario.simulation,
            warehouse_map=self.warehouse_map,
            robot_id=identity.robot_id,
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
        self._last_command_at_ns: int | None = None
        self._service_until_ns: int | None = None
        self._pending_peer_intents: dict[str, FreshnessVerdict] = {}
        self._peer_state_age: dict[str, float | None] = {}
        self._last_decision: SafetyDecision | None = None
        self._last_intent_freshness: FreshnessVerdict | None = None
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
        if upcoming is not None and not self._zone_held(upcoming):
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

    def _held_zone(self) -> str | None:
        """The zone this robot currently holds authority for, if any."""
        zone_id = self._zone_in_progress
        if zone_id is None:
            return None
        return zone_id if self._zone_held(zone_id) else None

    def _zone_held(self, zone_id: str) -> bool:
        try:
            return bool(self.coordinator.may_enter(zone_id))
        except (KeyError, ValueError):
            return False

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
        """First zone on the remaining path that this robot does not hold."""
        for x, y in self.plan:
            for zone in self.warehouse_map.zones:
                if zone.contains_point(x, y) and not self._zone_held(zone.id):
                    return zone.id
        return None

    def _to_command(self, observation: Observation, decision: SafetyDecision, now_ns: int) -> MotionCommand:
        """Turn a decision into a command, then let the gate have the last word."""
        pose = observation.pose_estimate.pose
        requested_v, requested_omega = self._pursue(pose)

        candidate = MotionCommand(
            robot_id=self.identity.robot_id,
            command_seq=self._command_seq,
            linear_mps=requested_v,
            angular_radps=requested_omega,
            issued_at_ns=now_ns,
            expires_at_ns=now_ns + int(self.scenario.simulation.actuator.command_ttl_s * 1e9),
            time_domain=TimeDomain.LOGICAL,
        )

        body = self.identity.footprint.body_at(Pose(pose.x, pose.y, pose.theta))
        context = GateContext(
            observation=observation,
            now_ns=now_ns,
            zone_authority=self._held_zone(),
            peer_freshness=dict(self._pending_peer_intents),
            intent_freshness=getattr(self, "_last_intent_freshness", None),
            battery_fraction=observation.battery_fraction,
            control_loop_age_ns=0 if self._last_command_at_ns is None else now_ns - self._last_command_at_ns,
            obstacle_distance_m=self.gate.nearest_obstacle_m(body),
            inside_zone=self._zone_in_progress,
        )

        final = self.gate.evaluate(candidate, now_ns, context)
        if not final.permitted:
            self.stop_reason = final.reason
            # A vetoed command still carries an expiry: the robot coasts down under
            # the actuator model rather than teleporting to rest.
            self._command_seq += 1
            return candidate.model_copy(update={"linear_mps": 0.0, "angular_radps": 0.0})
        self.stop_reason = StopReason.NONE
        self._command_seq += 1
        self._last_command_at_ns = now_ns
        return candidate

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
            "why_waiting": self.why.as_dict(),
            "stop_reason": self.stop_reason.value,
            "journal_healthy": self.journal.healthy,
        }

    def close(self) -> None:
        self.journal.close()

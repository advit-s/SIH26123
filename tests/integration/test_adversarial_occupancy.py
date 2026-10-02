"""Adversarial occupancy: can two robots hold overlapping usable authority?

The holder retaining its own local occupancy record is **not** the property under
test. That record only stops *that* robot from letting go; it says nothing about
whether a *peer* will still refuse a competing entrant. The question here is the
fleet-wide one:

    while any robot's body is physically inside a protected zone, no other robot
    may hold usable authority over that zone.

Three real in-process ``RobotAgent`` objects are driven against the real
``World``, exchanging real framed messages. Ground truth is read only by the
test, from ``world.truth()``; no robot's decision code is ever shown it.

Delivery is attacked in two ways, because the two are different threats:

* **immediate** -- everything delivered in order, the baseline;
* **delayed / reordered** -- ``zone_occupy`` frames withheld around the moment of
  entry, one control period's scan dropped on that same tick, and a duplicate of
  a genuine ``zone_grant`` re-framed with a fresh sequence and delivered late.

The harness's own outbox/inbox plumbing is deliberately not used: this file
drives ``RobotAgent.tick`` and ``RobotAgent.ingest`` directly and keeps its own
inbox, so an adversarial schedule is expressible at all. Everything inside the
robots -- coordinator, voters, journals, safety gate -- is the shipped code.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Final

from niharamesh.agent.runtime import RobotAgent
from niharamesh.coordination.protocol import ZoneProtocol
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    PeerEnvelope,
    PeerMessage,
    ZoneFenceBody,
    build_message,
)
from niharamesh.domain.geometry import Pose, aabb_overlap, bbox_of
from niharamesh.domain.map import ZoneState
from niharamesh.ports import Observation, SensorObservation
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.scenario.library import three_way_junction

ZONE: Final[str] = "zn-junction"
#: The robot that crosses the junction from the west, and its closest rival.
HOLDER: Final[str] = "amr-02"
RIVAL: Final[str] = "amr-03"
DONOR: Final[str] = "amr-01"
#: Hard bound on the adversarial window, in control periods.
WINDOW: Final[int] = 900


@contextlib.contextmanager
def allocation_round_disabled() -> Iterator[None]:
    """Skip the allocation round for the duration of the block.

    ``RobotAgent.tick`` prices every released task on every round boundary
    (``runtime.py:487``). That work awards *tasks*; by ``AGENTS.md`` rule 1 it
    can neither grant, withhold nor vacate a zone, so it is not what is under
    test here. Everything else in ``tick`` runs, unmodified, through the shipped
    ``RobotAgent.tick`` itself -- only this one step is removed, and the real
    method is restored on the way out.
    """
    original = RobotAgent._run_allocation_round
    RobotAgent._run_allocation_round = _no_allocation_round  # type: ignore[method-assign]
    try:
        yield
    finally:
        RobotAgent._run_allocation_round = original  # type: ignore[method-assign]


def _no_allocation_round(self: RobotAgent, now_ns: int, observation: object) -> None:
    del self, now_ns, observation


def build_harness() -> DeterministicHarness:
    """Three real agents on the **authored, unmodified** junction scenario.

    Nothing about the map, the zone, the start poses, the tasks or the policy is
    changed. That matters: an earlier revision of this file moved the holder to
    1.4 m from the junction to save twenty simulation seconds, and that changed
    the answer -- the approach line it produced made the localisation estimate
    oscillate across the protected boundary, which is a property of where the
    robot happens to start, not of the code. A result that only appears on a
    re-authored scenario is not a result about the shipped one.
    """
    return DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="adversarial-occupancy")


def dropped_scan(observation: Observation) -> Observation:
    """A real observation whose scan was dropped this control period.

    Built from the published value objects, exactly as a lost sensor frame would
    arrive. The shipped deterministic world never drops one, which is precisely
    why a harness-only run cannot demonstrate this hazard.
    """
    return Observation(
        robot_id=observation.robot_id,
        pose_estimate=observation.pose_estimate,
        motion=observation.motion,
        sensor=SensorObservation(
            robot_id=observation.sensor.robot_id,
            observed_at_ns=observation.sensor.observed_at_ns,
            delivered_at_ns=observation.sensor.delivered_at_ns,
            rays=observation.sensor.rays,
            dropped=True,
        ),
        battery_fraction=observation.battery_fraction,
        sim_time_ns=observation.sim_time_ns,
    )


@dataclass(slots=True)
class Overlap:
    """One tick at which the required fleet-wide property did not hold."""

    tick: int
    inside: str
    competitor: str
    phase: str
    authority: str | None
    own_voter_state: ZoneState


@dataclass(slots=True)
class Faults:
    """What this run injects, and everything it measured."""

    delay_occupy: bool = False
    drop_scan_on_entry: bool = False
    duplicate_grant: bool = False
    injected: list[str] = field(default_factory=list)
    overlaps: list[Overlap] = field(default_factory=list)
    #: Ticks at which the local single-voter guard was broken.
    voter_unguarded: list[tuple[int, str, ZoneState]] = field(default_factory=list)
    co_occupied_ticks: int = 0
    #: Voters that recorded physical occupancy at some point in the run.
    occupancy_declared: set[str] = field(default_factory=set)


class HarnessRun:
    """A whole run in one process, with an adversarial message schedule."""

    def __init__(self, harness: DeterministicHarness, faults: Faults) -> None:
        self.h = harness
        self.faults = faults
        self.inbox: dict[str, list[PeerMessage]] = {rid: [] for rid in harness.agents}
        self.withheld: list[tuple[str, PeerMessage]] = []
        self.grants_seen: list[PeerMessage] = []
        self.tick_index = 0
        self.hold: Callable[[PeerMessage], bool] | None = None
        #: Ticks at which a rival was actively asking for the occupied zone.
        self.contended_ticks = 0
        self.zone = harness.scenario.map.zone(ZONE)
        self._original_send = ZoneProtocol._send
        self._install_grant_capture()

    # ------------------------------------------------------------- observation

    def _install_grant_capture(self) -> None:
        """Record genuine ``zone_grant`` frames so one can be replayed later.

        An observation hook over the shipped ``_send``. It reads what the real
        state machine produced, forwards it unchanged, and decides nothing.
        """
        original = self._original_send
        seen = self.grants_seen

        def spy(
            protocol: ZoneProtocol, peer: str, kind: str, body: object, correlation_id: str = ""
        ) -> None:
            if kind == "zone_grant" and peer == HOLDER:
                envelope = PeerEnvelope(
                    kind=kind,
                    sender=protocol.robot_id,
                    sender_session=protocol.session_id,
                    run_id=protocol.membership.run_id,
                    epoch=protocol.membership.epoch,
                    seq=0,
                    sent_at_ns=protocol.now_ns,
                    time_domain=protocol.time_domain,
                    correlation_id=correlation_id,
                )
                seen.append(build_message(envelope, body))
            original(protocol, peer, kind, body, correlation_id)

        ZoneProtocol._send = spy  # type: ignore[method-assign]

    # ------------------------------------------------------------- transport

    def _drain_outboxes(self) -> None:
        for robot_id in sorted(self.h.agents):
            for target, message in self.h.agents[robot_id].coordinator.outbox:
                self.inbox[target].append(message)
            self.h.agents[robot_id].coordinator.outbox.clear()

    def _deliver(self) -> None:
        hold = self.hold
        for target in sorted(self.inbox):
            queued = self.inbox[target]
            self.inbox[target] = []
            for message in sorted(queued, key=lambda m: (m.envelope.sender, m.envelope.seq)):
                if hold is not None and hold(message):
                    self.withheld.append((target, message))
                    continue
                self.h.agents[target].ingest(message)
        if hold is None and self.withheld:
            for target, message in self.withheld:
                self.h.agents[target].ingest(message)
            self.withheld.clear()

    # ------------------------------------------------------------ physics

    def step(self) -> None:
        for robot_id in sorted(self.h.agents):
            agent = self.h.agents[robot_id]
            self.h.world.apply_command(agent.tick(self.h.world.observe(robot_id)))
        self._drain_outboxes()
        self._deliver()
        self.h.world.step(self.h.scenario.simulation.dt_s)
        self.h.clock.advance_seconds(self.h.scenario.simulation.dt_s)

    # -------------------------------------------------------- truth (evaluator)

    def body_of(self, robot_id: str) -> Pose:
        """Exact pose from world truth. **Evaluator side only.**"""
        truth = self.h.world.truth().robots[robot_id]
        return Pose(truth.x, truth.y, truth.theta)

    def inside(self, robot_id: str) -> bool:
        """True when world truth says the body overlaps the protected bounds."""
        footprint = self.h.agents[robot_id].identity.footprint
        return aabb_overlap(bbox_of(footprint.body_at(self.body_of(robot_id))), self.zone.protected_bounds)

    def own_evidence_inside(self, robot_id: str) -> bool:
        agent = self.h.agents[robot_id]
        evidence = agent.zone_evidence
        if evidence is None:
            return False
        return evidence.occupied_zone == ZONE

    def usable_authority(self, robot_id: str) -> bool:
        """Exactly what would let this robot act on the zone: entry, or retention."""
        agent = self.h.agents[robot_id]
        return bool(agent.coordinator.may_enter(ZONE)) or agent.authority_zone() == ZONE

    # ------------------------------------------------------------- the invariant

    def audit(self) -> None:
        """The required property, checked at the current tick against world truth."""
        tick = self.tick_index
        for robot_id, agent in self.h.agents.items():
            if agent.coordinator.voter.state_of(ZONE) is ZoneState.OCCUPIED:
                self.faults.occupancy_declared.add(robot_id)
        inside = [r for r in sorted(self.h.agents) if self.inside(r)]
        for occupant in inside:
            own_state = self.h.agents[occupant].coordinator.voter.state_of(ZONE)
            if own_state is ZoneState.FREE:
                self.faults.voter_unguarded.append((tick, occupant, own_state))
            for other in sorted(self.h.agents):
                if other == occupant:
                    continue
                if self.h.agents[other].coordinator.phase().value in ("initiated", "acquiring"):
                    self.contended_ticks += 1
            if self.usable_authority(other):
                    self.faults.overlaps.append(
                        Overlap(
                            tick=tick,
                            inside=occupant,
                            competitor=other,
                            phase=self.h.agents[other].coordinator.phase().value,
                            authority=self.h.agents[other].authority_zone(),
                            own_voter_state=own_state,
                        )
                    )
        if len(inside) > 1:
            self.faults.co_occupied_ticks += 1

    # --------------------------------------------------------------- injection

    def entry_reached(self) -> bool:
        """True once the holder's own geometry says it is in the protected zone."""
        agent = self.h.agents[HOLDER]
        evidence = agent.zone_evidence_for(self.h.world.observe(HOLDER))
        agent._latest_observation = self.h.world.observe(HOLDER)
        return evidence.occupied_zone == ZONE

    def replay_grant(self) -> bool:
        """Deliver a duplicate of a genuine ``zone_grant``, freshly framed.

        A real frame the peer really sent, replayed under a sequence number the
        receiver has never seen, so the replay window cannot discard it as an
        idempotent duplicate before it reaches the state machine.
        """
        if not self.grants_seen:
            return False
        original = self.grants_seen[-1]
        envelope = original.envelope.model_copy(update={"seq": 990_000 + len(self.faults.injected)})
        self.h.agents[HOLDER].ingest(build_message(envelope, original.body))
        self.faults.injected.append(f"duplicate zone_grant from {original.envelope.sender}")
        return True

    def close(self) -> None:
        ZoneProtocol._send = self._original_send  # type: ignore[method-assign]
        for agent in self.h.agents.values():
            agent.close()


# ====================================================================== helpers


@contextlib.contextmanager
def entry_scan_dropped(agent: RobotAgent) -> Iterator[dict[str, int]]:
    """Make this robot's **entry declaration** see a dropped scan, every time.

    ``RobotAgent._update_zone_lifecycle`` is the only place that declares entry,
    and it decides from its own geometry plus ``may_enter``, which consults
    ``_admission_safety``, which refuses a dropped scan. The fault is therefore
    injected at exactly that decision point and nowhere else: the published
    observation is swapped for one whose scan was dropped, on every call where
    this robot is ``GRANTED`` and its own body is already on the protected
    geometry. Entry therefore stays *undeclared* for as long as the body is in
    there, which is the honest picture of a robot whose entry report never gets
    made. The method itself is restored on the way out.
    """
    original = RobotAgent._update_zone_lifecycle
    fired: dict[str, int] = {"n": 0}

    def patched(self: RobotAgent, evidence: object) -> None:
        if (
            self is agent
            and self.coordinator.phase() is AcquisitionPhase.GRANTED
            and getattr(evidence, "occupied_zone", None) is not None
        ):
            fired["n"] += 1
            if self._latest_observation is not None:
                self._latest_observation = dropped_scan(self._latest_observation)
        original(self, evidence)

    RobotAgent._update_zone_lifecycle = patched  # type: ignore[method-assign]
    try:
        yield fired
    finally:
        RobotAgent._update_zone_lifecycle = original  # type: ignore[method-assign]


def drive(run: HarnessRun, ticks: int) -> None:
    for _ in range(ticks):
        run.step()
        run.tick_index += 1
        run.audit()


def drive_until_holder_inside(run: HarnessRun, limit: int = 900) -> int:
    """Tick until **world truth** says the holder's body overlaps the zone.

    The runtime declares entry on its own localisation uncertainty, which is
    conservative and therefore a little early. The evaluator still has to
    confirm the body really got in, or the rest of the test proves nothing.
    """
    for _ in range(limit):
        run.step()
        run.tick_index += 1
        run.audit()
        if run.inside(HOLDER):
            return run.tick_index
    raise AssertionError(
        "the holder's body never overlapped the protected geometry, so there was "
        "no occupancy to protect"
    )


def describe(overlap: Overlap) -> str:
    return (
        f"tick {overlap.tick}: {overlap.competitor} holds usable authority over {ZONE} "
        f"(phase={overlap.phase}, authority_zone={overlap.authority}) while "
        f"{overlap.inside}'s body is inside it; the occupant's own voter reads "
        f"{overlap.own_voter_state.value}"
    )


def assert_required(run: HarnessRun) -> None:
    """The fleet-wide property, checked against world truth at every tick."""
    assert run.contended_ticks > 0, (
        "no rival ever asked for the zone while it was occupied, so the refusals "
        "this run exercises prove nothing"
    )
    assert not run.faults.voter_unguarded, (
        "the local single-voter guard was broken: at the ticks below a robot's body was "
        "inside a protected zone while its OWN voter already read FREE, so every peer was "
        f"free to grant it to somebody else. First occurrences: {run.faults.voter_unguarded[:4]}"
    )
    assert not run.faults.overlaps, "\n".join(describe(o) for o in run.faults.overlaps)
    assert run.faults.co_occupied_ticks == 0, (
        f"two robots were inside {ZONE} at the same time on {run.faults.co_occupied_ticks} ticks"
    )


# ======================================================================== tests


def test_immediate_delivery_never_lets_a_competitor_in_behind_the_holder() -> None:
    """REQUIRED: with honest delivery the fleet-wide property holds throughout.

    The control. It establishes that the scenario, the map, the three agents and
    the world really do produce a holder crossing the junction while a rival is
    asking for it, so a failure in the adversarial cases cannot be dismissed as
    an unreachable setup.
    """
    with allocation_round_disabled():
        run = HarnessRun(build_harness(), Faults())
        try:
            drive_until_holder_inside(run)
            assert all(not run.inside(r) for r in (RIVAL, DONOR)), "precondition: sole occupant"

            drive(run, 60)
            assert_required(run)
            assert run.faults.occupancy_declared == {HOLDER, DONOR, RIVAL}, (
                "precondition: occupancy really was declared at every voter in the control "
                f"case, saw {sorted(run.faults.occupancy_declared)}"
            )
        finally:
            run.close()


def test_a_replayed_grant_does_not_free_an_occupied_junction() -> None:
    """REQUIRED: a duplicate ``zone_grant`` must not free an occupied junction.

    Occupancy is declared honestly, so every voter reads ``OCCUPIED`` before the
    duplicate arrives. ``ZoneVoter.apply_cancel`` refuses a pre-entry
    cancellation for an occupied zone, so the peers must keep the zone.
    """
    with allocation_round_disabled():
        run = HarnessRun(build_harness(), Faults(duplicate_grant=True))
        try:
            drive_until_holder_inside(run)
            assert run.faults.occupancy_declared == {HOLDER, DONOR, RIVAL}, (
                "precondition: occupancy was declared at every voter before the replay"
            )

            assert run.replay_grant(), "no genuine grant frame was captured to replay"
            # The instant after the replay, while the body is still in the aisle.
            for robot_id in (HOLDER, DONOR, RIVAL):
                assert (
                    run.h.agents[robot_id].coordinator.voter.state_of(ZONE) is ZoneState.OCCUPIED
                ), f"{robot_id} let a replayed grant free an occupied junction"
            drive(run, 60)

            assert_required(run)
            assert run.withheld == [], "precondition: this case delivers everything"
        finally:
            run.close()


def test_a_replayed_grant_with_delayed_occupancy_is_still_refused() -> None:
    """REQUIRED: the same must hold when the occupancy declaration is *late*.

    The attack has three parts and all three are needed:

    * every ``zone_occupy`` frame is withheld, so no peer ever hears that the
      junction is occupied;
    * the entry control period's scan is dropped, so the holder's declaration of
      entry is refused once while its body is already on the geometry;
    * a genuine ``zone_grant`` is then replayed under a fresh sequence number.

    The property that must survive is the single-voter guard: while a body is
    inside a protected zone, that robot's **own** voter must still hold the zone.
    That record is in-process, so it cannot be defended by message delivery, and
    it is the only thing that refuses every competing entrant.
    """
    with allocation_round_disabled():
        run = HarnessRun(build_harness(), Faults(delay_occupy=True, drop_scan_on_entry=True))
        run.hold = lambda message: message.envelope.kind == "zone_occupy"
        try:
            with entry_scan_dropped(run.h.agents[HOLDER]) as fired:
                drive_until_holder_inside(run)
            assert fired["n"] >= 1, (
                "the entry declaration was never reached, so the attack did not land"
            )
            for robot_id in (HOLDER, DONOR, RIVAL):
                assert (
                    run.h.agents[robot_id].coordinator.voter.state_of(ZONE) is ZoneState.PROMISED
                ), (
                    f"{robot_id} holds something other than a plain promise: entry was "
                    "declared despite the dropped scan, or a peer was told anyway"
                )

            assert run.replay_grant(), "no genuine grant frame was captured to replay"
            drive(run, 80)

            assert_required(run)
        finally:
            run.hold = None
            run.close()


def test_occupancy_survives_a_partition_and_is_only_left_by_an_authorised_fence() -> None:
    """REQUIRED (``AGENTS.md`` 4): a timer expires permission, never occupancy.

    Once the holder is inside and every voter has recorded it, this run then
    cuts **every** frame to and from the holder for twenty simulated seconds and
    never releases. Nothing may empty the aisle: not the silence, not the lost
    heartbeats, not the absence of a release. A competing entrant must still be
    refused, and the only way out is the supervised fence -- which makes the zone
    unavailable rather than free.
    """
    with allocation_round_disabled():
        run = HarnessRun(build_harness(), Faults())
        try:
            drive_until_holder_inside(run)
            drive(run, 2)
            for robot_id in (HOLDER, DONOR, RIVAL):
                assert (
                    run.h.agents[robot_id].coordinator.voter.state_of(ZONE) is ZoneState.OCCUPIED
                ), f"precondition: {robot_id} recorded the occupancy"

            run.hold = lambda message: True
            drive(run, 400)  # twenty simulated seconds of total silence
            assert run.withheld, "precondition: frames really were withheld"

            for robot_id in (HOLDER, DONOR, RIVAL):
                assert (
                    run.h.agents[robot_id].coordinator.voter.state_of(ZONE) is ZoneState.OCCUPIED
                ), (
                    f"{robot_id} emptied an occupied junction after "
                    f"{run.tick_index} ticks of silence: something is on a timer"
                )
            assert run.h.agents[RIVAL].coordinator.holders() == {ZONE: HOLDER}
            blocked = run.h.agents[RIVAL].coordinator.why_blocked(ZONE)
            assert "zone" in blocked or "acquir" in blocked, blocked

            # The only way out is an authorised, logged fence.
            run.hold = None
            for robot_id in sorted(run.h.agents):
                body = ZoneFenceBody(
                    run_id=run.h.membership.run_id,
                    epoch=run.h.membership.epoch,
                    zone_id=ZONE,
                    fenced_by=robot_id,
                    reason="review_harness: holder unreachable for twenty simulated seconds",
                    previous_holder=HOLDER,
                    previous_requester_session=f"{HOLDER}-s1",
                    operator_authorised=True,
                )
                outcome = run.h.agents[robot_id].coordinator.apply_fence(body)
                assert outcome.applied, f"{robot_id} refused the fence: {outcome.detail}"
            for robot_id in sorted(run.h.agents):
                assert (
                    run.h.agents[robot_id].coordinator.voter.state_of(ZONE) is ZoneState.FENCED
                ), robot_id
            drive(run, 10)
            for robot_id in (DONOR, RIVAL):
                assert run.h.agents[robot_id].coordinator.holders() == {}, robot_id
                assert not run.h.agents[robot_id].coordinator.may_enter(ZONE)
        finally:
            run.hold = None
            run.close()

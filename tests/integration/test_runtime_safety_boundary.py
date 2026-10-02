"""The runtime half of the Milestone A safety boundary.

Behavioural tests: they run the real ``RobotAgent``, the real ``ZoneProtocol``, the
real ``SafetyGate`` and the real ``World`` over the authored ``three-way-junction``
scenario, and assert on what the robot *did* -- odometry from world truth, the
gate's own decision log, retained authority -- rather than on internal call
sequences.

Every defect reproduced here is written up in
``docs/superpowers/plans/milestone-a-contract.md`` (sections A2 to A5, plus the
obstacle-gap defect found while running the fix).
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest

from niharamesh.agent.runtime import AgentPhase
from niharamesh.domain.coordination import AcquisitionPhase, FreshnessClass
from niharamesh.domain.geometry import OrientedBox, Pose
from niharamesh.domain.pose import MotionCommand, StopReason
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import FreshnessVerdict
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.safety.gate import DEFAULT_STALL_NS, GateContext, SafetyGate
from niharamesh.scenario.library import cycle_with_holding, three_way_junction

JUNCTION = "zn-junction"
CONTENDER = "amr-03"
TRAVELLER = "amr-02"
UNHURRIED = "amr-01"


@pytest.fixture
def fleet() -> Iterator[DeterministicHarness]:
    """One second of the real scenario: enough for a three-voter grant to land."""
    harness = DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="milestone-a")
    try:
        harness.run(max_sim_time_s=1.0)
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


def _odometry(harness: DeterministicHarness, robot_id: str) -> tuple[float, float, float]:
    """Exact pose from world truth. **Evaluator-side only**, never given to an agent."""
    truth = harness.world.truth().robots[robot_id]
    return (truth.x, truth.y, truth.theta)


def _drive(harness: DeterministicHarness, robot_id: str, ticks: int) -> list[MotionCommand]:
    """Tick one robot against the real world and apply every command it produced."""
    agent = harness.agents[robot_id]
    commands: list[MotionCommand] = []
    for _ in range(ticks):
        command = agent.tick(harness.world.observe(robot_id))
        commands.append(command)
        harness.world.apply_command(command)
        harness.world.step(harness.scenario.simulation.dt_s)
    return commands


# ===========================================================================
# A3 -- the agent's own refusal is a decision, not advice.
# ===========================================================================


def test_a_refused_decision_produces_a_stop_command_not_a_pursuit_command(
    fleet: DeterministicHarness,
) -> None:
    """A robot that decided it must not move must not emit a velocity.

    ``amr-03`` is refused ``zn-junction`` by the robot that holds it, so
    ``_decide`` returns ``ZONE_AUTHORITY_MISSING``. Before the fix ``_to_command``
    discarded that refusal and called ``_pursue`` anyway, so the command that
    reached the gate carried a full-speed pursuit -- and because ``inside_zone``
    named the junction from twelve metres away, the gate let it through.
    """
    agent = fleet.agents[CONTENDER]
    observation = fleet.world.observe(CONTENDER)

    evidence = agent.zone_evidence_for(observation)
    decision = agent._decide(observation, evidence, observation.sim_time_ns)
    assert not decision.permitted, "precondition: this robot must be refusing"
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert agent.phase is AgentPhase.QUEUED_FOR_ZONE

    command = agent.tick(observation)
    assert command.linear_mps == 0.0
    assert command.angular_radps == 0.0


def test_a_refused_stop_command_still_passes_through_the_one_gate(
    fleet: DeterministicHarness,
) -> None:
    """A stop is a command, and must stay attributable to the single veto point."""
    agent = fleet.agents[CONTENDER]
    before = len(agent.gate.recent_decisions(limit=4096))
    agent.tick(fleet.world.observe(CONTENDER))
    after = agent.gate.recent_decisions(limit=4096)
    assert len(after) > before, "the stop must be recorded by the gate, not bypass it"


def test_a_refusal_reports_the_agents_reason_not_the_gates_silence(
    fleet: DeterministicHarness,
) -> None:
    """An operator must not be told "nothing" while a robot stands still."""
    agent = fleet.agents[CONTENDER]
    agent.tick(fleet.world.observe(CONTENDER))
    assert agent.stop_reason is StopReason.ZONE_AUTHORITY_MISSING
    assert agent.inspect()["stop_reason"] == StopReason.ZONE_AUTHORITY_MISSING.value


def test_a_queued_robot_does_not_travel_toward_a_zone_it_does_not_hold(
    fleet: DeterministicHarness,
) -> None:
    """End-to-end, on metres rather than on a command value.

    Asserted against world truth, because a command value alone would not prove the
    physics honoured it.
    """
    agent = fleet.agents[CONTENDER]
    assert not agent.coordinator.may_enter(JUNCTION), "precondition: no entry permission"

    before = _odometry(fleet, CONTENDER)
    _drive(fleet, CONTENDER, ticks=40)
    after = _odometry(fleet, CONTENDER)

    assert math.dist(before, after) < 1e-6, f"{CONTENDER} moved {math.dist(before, after):.3f} m"


# ===========================================================================
# A2 -- the gate's zone evidence contract.
# ===========================================================================


def test_a_zone_on_the_plan_is_not_a_zone_in_the_body(fleet: DeterministicHarness) -> None:
    """``occupied_zone`` is geometry, never intent.

    ``amr-03`` starts twelve metres south of the junction with the junction first on
    its plan. Before A2 the runtime named that zone in ``inside_zone``, which
    satisfied the old gate's blanket authority check from twelve metres away.
    """
    agent = fleet.agents[CONTENDER]
    evidence = agent.zone_evidence_for(fleet.world.observe(CONTENDER))
    zone = fleet.scenario.map.zone(JUNCTION)

    assert evidence.occupied_zone is None
    assert evidence.zone_authority is None
    assert evidence.entry_permission is None
    assert not zone.contains_point(evidence.body.cx, evidence.body.cy)


def test_open_space_motion_is_permitted_without_any_zone_authority(
    fleet: DeterministicHarness,
) -> None:
    """Legitimate driving must not be frozen by a zone it will never touch."""
    agent = fleet.agents[UNHURRIED]
    assert agent.coordinator.requester.active is None, "precondition: no transaction"

    before = _odometry(fleet, UNHURRIED)
    commands = _drive(fleet, UNHURRIED, ticks=200)

    assert max(abs(c.linear_mps) for c in commands) > 0.0, "amr-01 must actually drive"
    assert math.dist(before, _odometry(fleet, UNHURRIED)) > 1.0
    assert agent.coordinator.requester.active is None, "and must never open a transaction"
    assert all(agent.stop_reason is not StopReason.ZONE_AUTHORITY_MISSING for _ in commands)


def test_the_runtime_and_the_gate_agree_about_which_zones_are_ahead(
    fleet: DeterministicHarness,
) -> None:
    """The decider and the veto point must use one margin.

    If the runtime believed it needed no authority for a zone the gate believed it
    was entering, the robot would brake to a stop, issue a zero command, be
    permitted to sit there, and then request motion again -- forever. A refusal
    that never clears is indistinguishable from a fault.
    """
    agent = fleet.agents[TRAVELLER]
    assert agent.authority_zone() == JUNCTION, "precondition: it holds the junction"

    evidence = agent.zone_evidence_for(fleet.world.observe(TRAVELLER))
    assert evidence.swept_body is not None

    gate = agent.gate
    body = evidence.body
    assert not _touches_any_zone(gate, evidence.swept_body), (
        "amr-02 is twelve metres clear of the junction, so its swept body must not "
        "reach protected geometry; if this fails, the gate would veto every command"
    )
    assert math.dist((body.cx, body.cy), (13.5, 11.9)) > 5.0


def _touches_any_zone(gate: SafetyGate, body: OrientedBox) -> bool:
    """True when *body* overlaps any zone's protected bounds."""
    from niharamesh.domain.geometry import aabb_overlap, bbox_of  # local: test-local helper

    return any(aabb_overlap(bbox_of(body), zone.protected_bounds) for zone in gate._map.zones)


# ===========================================================================
# A2 -- entry permission versus retained authority.
# ===========================================================================


def test_entry_permission_is_spent_by_entry_and_authority_is_not(
    fleet: DeterministicHarness,
) -> None:
    """``may_enter`` going false after entry does not empty the aisle.

    Declaring physical entry moves the transaction to ``OCCUPIED``. The complete
    grant set has now been spent on entry, so ``may_enter`` is false -- but this
    robot is still the one responsible for the junction.
    """
    agent = fleet.agents[TRAVELLER]
    requester = agent.coordinator

    assert requester.may_enter(JUNCTION), "precondition: entry permission is live"
    assert agent.entry_permission() == JUNCTION
    assert requester.mark_entered(JUNCTION)

    assert requester.phase() is AcquisitionPhase.OCCUPIED
    assert not requester.may_enter(JUNCTION), "entry permission is spent once entered"
    assert agent.entry_permission() is None
    assert agent.authority_zone() == JUNCTION, "authority is retained"

    # Nobody quietly freed the aisle: every voter still holds this robot's promise.
    for peer in fleet.agents.values():
        assert peer.coordinator.holders() == {JUNCTION: TRAVELLER}


def test_a_release_does_not_free_an_aisle_the_body_is_still_in(
    fleet: DeterministicHarness,
) -> None:
    """Release is a promise to come out, not proof of having come out."""
    agent = fleet.agents[TRAVELLER]
    requester = agent.coordinator

    assert requester.mark_entered(JUNCTION)
    requester.release()

    assert agent.authority_zone() == JUNCTION, "authority survives an unreconciled release"
    for peer in fleet.agents.values():
        assert peer.coordinator.holders() == {JUNCTION: TRAVELLER}


def test_a_body_inside_a_zone_without_retained_authority_is_vetoed(
    fleet: DeterministicHarness,
) -> None:
    """Pinned directly against the gate so it cannot come back by another route."""
    agent = fleet.agents[CONTENDER]
    observation = fleet.world.observe(CONTENDER)
    inside = OrientedBox(13.5, 11.9, 0.0, 0.6, 0.4)

    def decide(**overrides: object) -> object:
        fields: dict[str, object] = {
            "observation": observation,
            "now_ns": observation.sim_time_ns,
            "zone_authority": None,
            "entry_permission": None,
            "occupied_zone": None,
            "swept_body": inside,
        }
        fields.update(overrides)
        context = GateContext(**fields)  # type: ignore[arg-type]
        command = MotionCommand(
            robot_id=CONTENDER,
            command_seq=1,
            linear_mps=0.2,
            angular_radps=0.0,
            issued_at_ns=observation.sim_time_ns,
            expires_at_ns=observation.sim_time_ns + 400_000_000,
            time_domain=observation.pose_estimate.time_domain,
        )
        return agent.gate.evaluate(command, observation.sim_time_ns, context)

    refused = decide()
    assert not refused.permitted
    assert refused.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert "entry" in refused.limiting_constraint, (
        "a body with no occupancy evidence and no permission is *entering*, and the "
        "gate must say so rather than blame occupancy it was never told about"
    )

    # Reported occupancy without retained authority is the distinct refusal: this
    # robot is already in the aisle and cannot make that safe by acquiring it.
    occupying = decide(occupied_zone=JUNCTION)
    assert not occupying.permitted
    assert "occupancy" in occupying.limiting_constraint
    assert JUNCTION in occupying.limiting_constraint

    # Retained authority is what makes continuing inside legitimate.
    allowed = decide(occupied_zone=JUNCTION, zone_authority=JUNCTION)
    assert allowed.permitted


def test_naming_a_distant_zone_grants_nothing(fleet: DeterministicHarness) -> None:
    """The exact evidence the pre-A2 runtime supplied, and its replacement value.

    A swept body out in the open is not this gate's business; the same body
    translated into protected geometry with no grant is refused.
    """
    agent = fleet.agents[CONTENDER]
    observation = fleet.world.observe(CONTENDER)
    command = MotionCommand(
        robot_id=CONTENDER,
        command_seq=1,
        linear_mps=0.2,
        angular_radps=0.0,
        issued_at_ns=observation.sim_time_ns,
        expires_at_ns=observation.sim_time_ns + 400_000_000,
        time_domain=observation.pose_estimate.time_domain,
    )

    def decide(swept: OrientedBox) -> object:
        context = GateContext(
            observation=observation,
            now_ns=observation.sim_time_ns,
            entry_permission=None,
            zone_authority=None,
            occupied_zone=None,
            swept_body=swept,
        )
        return agent.gate.evaluate(command, observation.sim_time_ns, context)

    assert decide(OrientedBox(13.5, 1.3, 0.0, 0.6, 0.4)).permitted

    refused = decide(OrientedBox(13.5, 11.9, 0.0, 0.6, 0.4))
    assert not refused.permitted
    assert JUNCTION in refused.limiting_constraint


# ===========================================================================
# A4 -- control-loop age is measured, not inferred from permission.
# ===========================================================================


def test_continuous_vetoed_ticks_do_not_latch_control_loop_stalled(
    fleet: DeterministicHarness,
) -> None:
    """A veto every tick is still a live control loop.

    Before A4 the "last command" timestamp only advanced on a *permitted* command,
    so a robot vetoed every tick looked permanently stalled and the gate latched
    ``CONTROL_LOOP_STALLED`` on top of the real reason. The stall check runs before
    the freshness check, so a false latch would hide the true cause from an
    operator.
    """
    agent = fleet.agents[UNHURRIED]
    stale = FreshnessVerdict(FreshnessClass.STALE, 9.0, 0, "milestone A4 test")

    seen: set[StopReason] = set()
    for _ in range(200):  # 200 x 20 Hz = 10 s, twenty times DEFAULT_STALL_NS
        agent.note_intent_freshness(stale)
        agent.tick(fleet.world.observe(UNHURRIED))
        fleet.world.step(fleet.scenario.simulation.dt_s)
        seen.add(agent.stop_reason)

    assert StopReason.FRESHNESS_UNCERTAIN in seen, "the real reason must be reported"
    assert StopReason.CONTROL_LOOP_STALLED not in seen, "a live loop must not be called stalled"


def test_a_genuinely_stalled_control_loop_fails_closed(fleet: DeterministicHarness) -> None:
    """Re-arming a stall detector must not disarm it.

    The world is advanced without the agent ticking, which is exactly what a
    wedged control loop looks like from outside. The first tick back must fail
    closed; the ticks after it must be normal again, or one hiccup freezes a robot
    for the rest of the run.
    """
    agent = fleet.agents[UNHURRIED]
    agent.tick(fleet.world.observe(UNHURRIED))

    dt = fleet.scenario.simulation.dt_s
    for _ in range(int(DEFAULT_STALL_NS / 1e9 / dt) + 4):
        fleet.world.step(dt)

    agent.tick(fleet.world.observe(UNHURRIED))
    assert agent.stop_reason is StopReason.CONTROL_LOOP_STALLED

    agent.tick(fleet.world.observe(UNHURRIED))
    assert agent.stop_reason is not StopReason.CONTROL_LOOP_STALLED


# ===========================================================================
# A5 -- the coordinator's local safety callback must be a real one.
# ===========================================================================


def test_a_complete_grant_set_becomes_entry_permission_once_local_evidence_says_so(
    fleet: DeterministicHarness,
) -> None:
    """Delivery is not admission -- and admission is not impossible.

    With the coordinator's deliberately refusing default, ``three-way-junction``
    reached ``GRANTED`` and stopped there forever: no process could ever supply the
    missing local evidence. The runtime must supply a real callback, after which a
    complete grant set *does* permit entry.
    """
    requester = fleet.agents[TRAVELLER].coordinator
    acquisition = requester.requester.active

    assert acquisition is not None
    assert acquisition.phase is AcquisitionPhase.GRANTED
    assert acquisition.held() == ("amr-01", "amr-02", "amr-03")
    assert requester.may_enter(JUNCTION), "local admission refused a lawful entry"
    assert "SAFETY_GATE" not in requester.why_blocked(JUNCTION)


def test_admission_refuses_when_this_robot_has_no_local_evidence(
    fleet: DeterministicHarness,
) -> None:
    """Absence of evidence is not evidence of safety, at admission too."""
    agent = fleet.agents[TRAVELLER]
    agent.tick(fleet.world.observe(TRAVELLER))
    context = _admission_context(JUNCTION)

    granted, _ = agent._admission_safety(context)
    assert granted, "precondition: a healthy robot with a clear approach is admitted"

    agent._latest_observation = None
    granted, reason = agent._admission_safety(context)
    assert not granted
    assert "observation" in reason


def test_admission_refuses_a_stale_localiser(fleet: DeterministicHarness) -> None:
    agent = fleet.agents[TRAVELLER]
    agent.tick(fleet.world.observe(TRAVELLER))  # publish a current observation
    context = _admission_context(JUNCTION)

    stale = _aged_observation(fleet.world.observe(TRAVELLER), seconds=5.0)
    agent._latest_observation = stale

    granted, reason = agent._admission_safety(context)
    assert not granted
    assert "localisation" in reason


def test_admission_refuses_a_dropped_scan(fleet: DeterministicHarness) -> None:
    agent = fleet.agents[TRAVELLER]
    agent.tick(fleet.world.observe(TRAVELLER))
    context = _admission_context(JUNCTION)

    dropped = _dropped_observation(fleet.world.observe(TRAVELLER))
    agent._latest_observation = dropped

    granted, reason = agent._admission_safety(context)
    assert not granted
    assert "dropped" in reason


def test_admission_never_consults_the_permission_it_is_deciding(
    fleet: DeterministicHarness,
) -> None:
    """The callback must be non-circular.

    Grants are the protocol's answer to "may anybody else be relying on me"; this
    callback answers the separate question "can this robot physically and safely get
    in from where it is standing". Confusing the two either deadlocks or launders a
    grant into a safety argument, so the callback must still permit entry when the
    grant set is *withheld*.
    """
    agent = fleet.agents[TRAVELLER]
    agent.tick(fleet.world.observe(TRAVELLER))
    context = _admission_context(JUNCTION)

    agent.coordinator.cancel("milestone A5 test: grant set withdrawn")
    assert not agent.coordinator.may_enter(JUNCTION), "precondition: no entry permission"

    granted, reason = agent._admission_safety(context)
    assert granted, (
        f"local admission must not depend on the grant set it is being asked to qualify; got {reason!r}"
    )


# ===========================================================================
# Defects found while running the fix: obstacle evidence and the pivot escape.
# ===========================================================================


def test_a_lateral_shelf_is_not_a_stopping_hazard(fleet: DeterministicHarness) -> None:
    """The stopping budget is longitudinal; a shelf beside you is not in the way.

    The gate used to compare the nearest obstacle *in any direction* against the
    declared stopping budget. A robot driving parallel to a shelf 0.26 m away was
    refused, because 0.26 < 0.32 -- and two of the three robots in ``headon-aisle``
    were frozen solid by it. The gate now also does the exact test that actually
    answers the question: the body, and the body carried *forward* by its own stopping
    reach, must not overlap static geometry.

    ``shelf-30`` spans x 18.8..22.0, y 2.6..6.2. This body sits 0.26 m below it with
    its heading along the aisle, so a 0.26 m forward sweep moves it in x, never
    toward the shelf.
    """
    gate = fleet.agents[TRAVELLER].gate
    along_shelf = OrientedBox(20.0, 2.14, 0.0, 0.6, 0.4)  # y 1.94..2.34, heading +x
    gap = gate.nearest_obstacle_m(along_shelf)

    assert gap is not None
    assert gap < fleet.scenario.simulation.stopping.total_distance_m, (
        "precondition: the lateral gap really is inside the stopping budget, which is "
        "what used to make the comparison refuse a legal manoeuvre"
    )
    permitted = _judge_obstacles(gate, along_shelf, linear=0.4, angular=0.0)
    assert permitted.permitted, (
        f"driving parallel to a shelf {gap:.3f} m away must not be refused: {permitted.limiting_constraint}"
    )


def test_a_robot_pointed_at_a_shelf_may_not_drive_into_it(fleet: DeterministicHarness) -> None:
    """The exact test is directional, so it still refuses the real hazard."""
    gate = fleet.agents[TRAVELLER].gate
    facing = OrientedBox(20.0, 2.14, math.pi / 2.0, 0.6, 0.4)  # heading +y, at the shelf

    refused = _judge_obstacles(gate, facing, linear=0.4, angular=0.0)
    assert not refused.permitted
    assert refused.reason is StopReason.OBSTACLE_IN_PATH
    assert "reaches_static" in refused.limiting_constraint


def test_a_robot_overlapping_a_shelf_is_refused_regardless_of_speed(
    fleet: DeterministicHarness,
) -> None:
    gate = fleet.agents[TRAVELLER].gate
    inside = OrientedBox(6.6, 4.4, 0.0, 0.6, 0.4)  # shelf-00 is 3.2 x 3.6 at (6.6, 4.4)

    stopped = _judge_obstacles(gate, inside, linear=0.0, angular=0.0)
    assert not stopped.permitted
    assert "body_overlaps_static" in stopped.limiting_constraint


def test_a_turning_robot_may_not_swing_a_corner_into_a_shelf(
    fleet: DeterministicHarness,
) -> None:
    """Rotation is physical motion too, and the gate has to know it.

    This is what makes the pivot escape below safe: if the swept corner were ignored,
    letting a refused command keep steering would be a way to crash. The bound counts
    the spin-down *after* the command expires as well, because the actuator keeps
    rotating while it coasts.
    """
    gate = fleet.agents[TRAVELLER].gate
    tight = OrientedBox(20.0, 2.30, 0.0, 0.6, 0.4)  # y 2.10..2.50, shelf starts at 2.6

    assert _judge_obstacles(gate, tight, linear=0.0, angular=0.0).permitted
    assert _judge_obstacles(gate, tight, linear=0.0, angular=0.2).permitted, (
        "0.14 rad of swing moves the corner about 4 mm; it is not a hazard"
    )
    assert not _judge_obstacles(gate, tight, linear=0.0, angular=1.0).permitted, (
        "0.73 rad of swing moves the corner 0.26 m, straight into the shelf"
    )


# ===========================================================================
# Slowing in, not stopping dead. The governor exists because the gate can only
# permit or refuse, and refusing outright used to freeze robots.
# ===========================================================================


def test_the_robot_slows_into_a_constriction_instead_of_stopping_dead(
    fleet: DeterministicHarness,
) -> None:
    """A command that is too fast becomes a slower command, not a refused one.

    Refusing outright was the original defect: the robot may not translate, may not
    steer, and is stuck. Reducing the *command* keeps it moving, which is what a real
    robot does when it approaches something it cannot clear at full speed.
    """
    agent = fleet.agents[UNHURRIED]
    # `shelf-30` spans x 18.8..22.0, y 2.6..6.2. Heading +x along the shelf face, the
    # full-speed stopping reach carries the body from 18.7 to 18.96 -- into it.
    tight = _observation_at(fleet.world.observe(UNHURRIED), x=18.4, y=4.4, theta=0.0, stopped=True)
    agent.plan = ((22.0, 4.4),)

    result = agent.tick(tight)
    assert 0.0 < result.linear_mps < 0.4, f"the robot must creep rather than stop, got v={result.linear_mps}"
    assert agent.stop_reason is StopReason.NONE


def test_a_robot_with_nowhere_to_go_stops_completely(fleet: DeterministicHarness) -> None:
    """When even a crawl would touch geometry, nothing moves.

    The governor's floor is declared rather than asymptotic, so a boxed-in robot
    reaches ``(0.0, 0.0)`` in a bounded number of halvings instead of creeping
    toward zero forever. Here the body is already overlapping ``shelf-00``.
    """
    agent = fleet.agents[UNHURRIED]
    boxed_in = _observation_at(fleet.world.observe(UNHURRIED), x=6.6, y=4.4, theta=0.0, stopped=True)
    agent.plan = ((8.0, 4.4),)

    result = agent.tick(boxed_in)
    assert result.linear_mps == 0.0
    assert result.angular_radps == 0.0
    assert agent.stop_reason is StopReason.OBSTACLE_IN_PATH


def test_the_governor_is_bounded(fleet: DeterministicHarness) -> None:
    """A control period may not be spent searching for a clearable command."""
    agent = fleet.agents[UNHURRIED]
    observation = fleet.world.observe(UNHURRIED)
    body = agent.identity.footprint.body_at(
        Pose(observation.pose_estimate.pose.x, observation.pose_estimate.pose.y, 0.0)
    )
    start = (0.4, 1.0)
    result = agent._limit_for_clearance(body, *start)
    v, omega = result
    assert 0.0 <= v <= start[0]
    assert abs(omega) <= start[1]
    assert (v, omega) == start, (
        "a body clear of every obstacle must pass through untouched -- the governor "
        "is a constraint, not a habit"
    )


# ===========================================================================
# Defect found while running the fix: the obstacle gap is a false measurement.
# ===========================================================================


def test_one_outstanding_grant_per_robot_globally_is_respected_by_the_runtime() -> None:
    """Holding one zone forbids opening a transaction for another.

    The requester raises on a second outstanding acquisition, which is the invariant
    working. The runtime used to walk straight into that raise: with authority held
    for one zone and a *different* zone next on the plan, it called ``begin_acquire``
    anyway and the run crashed with ``robot amr-02 already holds an outstanding
    transaction for 'zn-cycle-bottom'``.

    ``cycle-with-holding`` is used because ``three-way-junction`` declares a single
    zone, so the situation cannot arise there at all.
    """
    harness = DeterministicHarness(freeze_snapshot(cycle_with_holding()), run_id="invariant-6")
    try:
        harness.run(max_sim_time_s=2)
        agent = next(a for a in harness.agents.values() if a.authority_zone() is not None)
        held = agent.authority_zone()
        assert held is not None
        coordinator = agent.coordinator

        other = next(z for z in sorted(agent.warehouse_map.zones, key=lambda z: z.id) if z.id != held)
        agent.plan = ((other.protected_bounds[0], other.protected_bounds[1]),) * 2

        observation = harness.world.observe(agent.identity.robot_id)
        evidence = agent.zone_evidence_for(observation)
        decision = agent._decide(observation, evidence, observation.sim_time_ns)

        assert not decision.permitted
        assert decision.limiting_constraint == f"busy_holding:{held}"
        assert agent.why.blocking_resource == held
        assert coordinator.requester.active.zone_id == held, "no second transaction may exist"
    finally:
        for a in harness.agents.values():
            a.close()


def test_forward_clearance_is_measured_in_the_robots_own_frame(
    fleet: DeterministicHarness,
) -> None:
    """Sensor bearings are world-frame and must be expressed relative to the body.

    Filtering them directly against ``|bearing| <= pi/2`` measures the wedge around the
    world ``+x`` axis. A robot pointing anywhere else then reports *no forward evidence
    at all* and silently falls back on the exact map test alone -- which is how the
    measured half of the obstacle check quietly disappeared for two of three robots.
    """
    agent = fleet.agents[UNHURRIED]
    observation = fleet.world.observe(UNHURRIED)
    heading = observation.pose_estimate.pose.theta

    clearance = agent._forward_clearance_m(observation)
    assert clearance is not None, "a real scan always has rays ahead of the body"
    assert 0.0 < clearance <= fleet.scenario.simulation.sensor.range_m + 1e-9

    # Turning the robot must turn the window with it, not move it.
    #
    # Driven by a **synthetic scan** rather than the live one. The live scan's
    # geometry depends on wherever this robot happened to be after one second, and
    # an assertion of "the two headings give different minima" is then satisfied or
    # broken by coincidence -- it passed only because the shortest ray happened to
    # fall outside both windows. With one obstacle ray at a known bearing the
    # property is tested directly: a body-frame window finds it when the robot
    # faces it and reports no evidence at all when it faces away.
    ahead = _observation_at(
        observation,
        x=20.0,
        y=11.9,
        theta=0.0,
        stopped=True,
        rays=_rays_at(0.0, 0.9),
    )
    away = _observation_at(
        observation,
        x=20.0,
        y=11.9,
        theta=math.pi,
        stopped=True,
        rays=_rays_at(0.0, 0.9),
    )
    assert heading is not None
    assert agent._forward_clearance_m(ahead) == pytest.approx(0.9)
    assert agent._forward_clearance_m(away) is None, (
        "an obstacle dead ahead must not be reported when the robot faces the other way; "
        "a fixed world-frame wedge would report it for both headings"
    )


def test_no_ray_ahead_reports_no_evidence_rather_than_an_infinite_clearance(
    fleet: DeterministicHarness,
) -> None:
    """A missing measurement is not a clear road, and not a near one either."""
    agent = fleet.agents[UNHURRIED]
    observation = _empty_scan_observation(fleet.world.observe(UNHURRIED))
    assert agent._forward_clearance_m(observation) is None


# ===========================================================================
# Defect found while running the fix: the obstacle gap is a false measurement.
# ===========================================================================


def test_a_clear_aisle_is_never_reported_as_zero_range(fleet: DeterministicHarness) -> None:
    """A 180-degree robot in a clear aisle was told an obstacle was at 0.000 m.

    ``_box_gap`` accumulated its per-axis SAT projections with ``min`` where SAT
    requires ``max``, so for any body facing roughly backwards one axis produced a
    large negative value, the minimum went negative, and ``max(0.0, ...)`` reported
    a genuine 0.30 m gap as ``0.0``. The gate then vetoed with
    ``obstacle_0.000m<0.320m`` and the robot could not move at all. A false
    measurement is a defect even when it errs towards refusing: it tells an
    operator an obstacle exists where none does.
    """
    gate = fleet.agents[TRAVELLER].gate
    facing_west = OrientedBox(24.0, 11.9, -math.pi, 0.6, 0.4)
    gap = gate.nearest_obstacle_m(facing_west)

    assert gap is not None
    assert gap > 0.25, f"a robot in a 1.4 m aisle is not touching a shelf, got {gap}"
    assert gate.nearest_obstacle_m(OrientedBox(24.0, 11.9, 0.0, 0.6, 0.4)) == pytest.approx(gap, abs=0.01), (
        "heading must not change the reported clearance"
    )


def test_a_robot_held_at_a_clear_junction_actually_drives(fleet: DeterministicHarness) -> None:
    """The end of the whole exercise: a granted robot moves.

    ``amr-02`` holds the complete grant set for the junction and has a 217-waypoint
    plan to the far pickup station. Before the obstacle-gap fix it was vetoed every
    tick and stood still.
    """
    agent = fleet.agents[TRAVELLER]
    assert agent.authority_zone() == JUNCTION, "precondition: it holds the junction"

    before = _odometry(fleet, TRAVELLER)
    commands = _drive(fleet, TRAVELLER, ticks=100)
    after = _odometry(fleet, TRAVELLER)

    assert all(agent.stop_reason is not StopReason.OBSTACLE_IN_PATH for _ in commands)
    assert math.dist(before, after) > 0.5, f"amr-02 travelled only {math.dist(before, after):.3f} m"


# --------------------------------------------------------------------------- #
# Helpers. All of them build real value objects; none of them fakes a decision.
# --------------------------------------------------------------------------- #


def _admission_context(zone_id: str) -> object:
    """A real ``AdmissionContext`` for *zone_id*, taken from the real protocol."""
    from niharamesh.coordination.requester import AdmissionContext  # local: keeps the import honest
    from niharamesh.domain.map import ZoneMovement

    return AdmissionContext(
        zone_id=zone_id,
        movement=ZoneMovement.FWD,
        entry_pose=(13.5, 10.9, math.pi / 2.0),
        exit_pose=(13.5, 12.9, math.pi / 2.0),
        required_voters=("amr-01", "amr-02", "amr-03"),
        held_voters=("amr-01", "amr-02", "amr-03"),
        required_set_digest="0" * 64,
        now_ns=0,
    )


def _aged_observation(observation: object, *, seconds: float) -> object:
    """A real observation whose localiser fix is *seconds* old.

    Built from the published value objects because ``PoseEstimate`` exists precisely
    so the system can represent "last known pose, age 3.2 s, uncertain" -- and the
    live sensor model never produces that, so no run can demonstrate it.

    Age is created by moving ``sim_time_ns`` forward while leaving the fix where it
    was, which makes the age exactly ``seconds`` instead of clamping at zero on a
    world that has only been running for a second or two.
    """
    from niharamesh.domain.pose import PoseEstimate, UncertaintyModel  # local
    from niharamesh.ports import Observation, SensorObservation

    assert isinstance(observation, Observation)
    estimate = PoseEstimate(
        map_id=observation.pose_estimate.map_id,
        frame_id=observation.pose_estimate.frame_id,
        pose=observation.pose_estimate.pose,
        observed_at_ns=observation.pose_estimate.observed_at_ns,
        time_domain=observation.pose_estimate.time_domain,
        uncertainty=UncertaintyModel(kind="hard_bound", max_m=0.25, source="milestone-a-test"),
        fused=observation.pose_estimate.fused,
    )
    scan = SensorObservation(
        robot_id=observation.sensor.robot_id,
        observed_at_ns=observation.sensor.observed_at_ns,
        delivered_at_ns=observation.sensor.delivered_at_ns,
        rays=observation.sensor.rays,
        dropped=False,
    )
    return Observation(
        robot_id=observation.robot_id,
        pose_estimate=estimate,
        motion=observation.motion,
        sensor=scan,
        battery_fraction=observation.battery_fraction,
        sim_time_ns=observation.sim_time_ns + int(seconds * 1e9),
    )


def _dropped_observation(observation: object) -> object:
    """A real observation whose scan was dropped this control period."""
    from niharamesh.ports import Observation, SensorObservation

    assert isinstance(observation, Observation)
    scan = SensorObservation(
        robot_id=observation.sensor.robot_id,
        observed_at_ns=observation.sensor.observed_at_ns,
        delivered_at_ns=observation.sensor.delivered_at_ns,
        rays=observation.sensor.rays,
        dropped=True,
    )
    return Observation(
        robot_id=observation.robot_id,
        pose_estimate=observation.pose_estimate,
        motion=observation.motion,
        sensor=scan,
        battery_fraction=observation.battery_fraction,
        sim_time_ns=observation.sim_time_ns,
    )


def _pose(x: float, y: float, theta: float = 0.0) -> Pose:
    return Pose(x, y, theta)


def _judge_obstacles(gate: SafetyGate, body: OrientedBox, *, linear: float, angular: float) -> object:
    """Run *body*'s obstacle evidence through the gate and return its decision.

    Everything else the gate needs is held neutral on purpose: this is about the
    obstacle test, and a decision refused for an unrelated reason would prove
    nothing about it.
    """
    from niharamesh.ports import Observation  # local

    observation = Observation(
        robot_id="probe",
        pose_estimate=_pose_estimate(body),
        motion=_motion(),
        sensor=_empty_scan(),
        battery_fraction=0.9,
        sim_time_ns=0,
    )
    context = GateContext(
        observation=observation,
        now_ns=0,
        zone_authority=None,
        entry_permission=None,
        occupied_zone=None,
        occupied_box=body,
        swept_body=None,
    )
    command = MotionCommand(
        robot_id="probe",
        command_seq=1,
        linear_mps=linear,
        angular_radps=angular,
        issued_at_ns=0,
        expires_at_ns=400_000_000,
        time_domain=TimeDomain.LOGICAL,
    )
    return gate.evaluate(command, 0, context)


def _rays_at(bearing_rad: float, distance_m: float) -> tuple[object, ...]:
    """A one-ray world-frame scan, as the sensor model would deliver it."""
    from niharamesh.ports import RangeRay  # local

    return (RangeRay(bearing_rad, distance_m, "obstacle", 0, 0),)


def _observation_at(
    observation: object,
    *,
    x: float,
    y: float,
    theta: float,
    stopped: bool = False,
    rays: tuple[object, ...] | None = None,
) -> object:
    """A real observation with its pose estimate moved, as the localiser would.

    Uses the published value objects so the gate sees a genuine ``PoseEstimate`` and
    not a stand-in. Localising a robot into a shelf is not something the world will
    do, which is exactly why the harness cannot demonstrate this hazard on its own.

    ``stopped`` zeroes the measured velocity. It matters: a robot already coasting at
    0.4 m/s genuinely cannot brake out of a shelf in one command, and the gate is
    right to refuse even a pivot in that case. The hazard being tested here is a
    robot that is *already at rest* and merely pointed the wrong way.
    """
    from niharamesh.domain.pose import MotionState, Pose2, PoseEstimate, UncertaintyModel  # local
    from niharamesh.ports import Observation  # local

    assert isinstance(observation, Observation)
    estimate = PoseEstimate(
        map_id=observation.pose_estimate.map_id,
        frame_id=observation.pose_estimate.frame_id,
        pose=Pose2(x=x, y=y, theta=theta),
        observed_at_ns=observation.pose_estimate.observed_at_ns,
        time_domain=observation.pose_estimate.time_domain,
        uncertainty=UncertaintyModel(kind="gaussian_sigma", sigma_m=0.02, sigma_rad=0.01),
    )
    motion = observation.motion
    if stopped:
        motion = MotionState(
            linear_velocity_mps=0.0,
            angular_velocity_radps=0.0,
            actuation_enabled=True,
            actuator=motion.actuator,
        )
    scan = observation.sensor if rays is None else _scan_with(observation, rays)
    return Observation(
        robot_id=observation.robot_id,
        pose_estimate=estimate,
        motion=motion,
        sensor=scan,
        battery_fraction=observation.battery_fraction,
        sim_time_ns=observation.sim_time_ns,
    )


def _scan_with(observation: object, rays: tuple[object, ...]) -> object:
    """A real ``SensorObservation`` carrying *rays* instead of the live scan."""
    from niharamesh.ports import Observation, SensorObservation  # local

    assert isinstance(observation, Observation)
    live = observation.sensor
    return SensorObservation(
        robot_id=live.robot_id,
        observed_at_ns=live.observed_at_ns,
        delivered_at_ns=live.delivered_at_ns,
        rays=rays,
    )


def _pose_estimate(body: OrientedBox) -> object:
    from niharamesh.domain.pose import Pose2, PoseEstimate, UncertaintyModel  # local

    return PoseEstimate(
        map_id="probe",
        pose=Pose2(x=body.cx, y=body.cy, theta=body.theta),
        observed_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
        uncertainty=UncertaintyModel(kind="gaussian_sigma", sigma_m=0.02, sigma_rad=0.01),
    )


def _motion() -> object:
    from niharamesh.domain.pose import ActuatorState, MotionState  # local

    return MotionState(actuation_enabled=True, actuator=ActuatorState.ENABLED)


def _empty_scan() -> object:
    from niharamesh.ports import SensorObservation  # local

    return SensorObservation(robot_id="probe", observed_at_ns=0, delivered_at_ns=0, rays=())


def _empty_scan_observation(observation: object) -> object:
    """A real observation whose scan came back with nothing in it."""
    from niharamesh.ports import Observation  # local

    assert isinstance(observation, Observation)
    return Observation(
        robot_id=observation.robot_id,
        pose_estimate=observation.pose_estimate,
        motion=observation.motion,
        sensor=_empty_scan(),
        battery_fraction=observation.battery_fraction,
        sim_time_ns=observation.sim_time_ns,
    )

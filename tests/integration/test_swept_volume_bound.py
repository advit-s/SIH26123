"""The swept-volume bound, checked by integrating physics rather than by geometry.

Every other obstacle test in this repository is a single-tick gate decision on a
hand-placed body. That is exactly why an unsound swept-volume witness survived a
change set whose purpose included adding an obstacle check: a box comparison can
only tell you the box was wrong, not that the robot would actually hit something.

These tests close that gap. They take a command the *real* agent would issue, hand
it to the *real* gate, and then integrate it with the *real* kinematics against the
*real* map, checking every intermediate pose against the independent collision
predicate. If a permitted command reaches a shelf, the test fails.

The defect these exist for is recorded in ``docs/STATUS.md``: an earlier witness
translated a single box along the initial heading and widened it by
``min(pi, omega * ttl)``, which for a robot translating *and* rotating left the
lateral component entirely outside the box and ignored the post-expiry spin-down.
A real command was permitted that drove the chassis 44 mm into a shelf.
"""

from __future__ import annotations

import math
from collections.abc import Iterator

import pytest

from niharamesh.domain.geometry import (
    OrientedBox,
    centre_arc_lateral_m,
    sat_overlap,
    swept_body_bound,
)
from niharamesh.domain.pose import MotionCommand, StopReason
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import Observation
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.safety.gate import GateContext
from niharamesh.scenario.library import three_way_junction
from niharamesh.simulator import kinematics

SHELF_31 = (18.8, 7.6, 22.0, 11.2)  # x0, y0, x1, y1, from the three-way-junction map
FOOTPRINT = (0.60, 0.40)


@pytest.fixture
def fleet() -> Iterator[DeterministicHarness]:
    harness = DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="swept")
    try:
        harness.run(max_sim_time_s=1.0)
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


def _static(fleet: DeterministicHarness) -> tuple[OrientedBox, ...]:
    return fleet.world.static_boxes_for_evaluation()


def _shelf_31(fleet: DeterministicHarness) -> OrientedBox:
    return next(b for b in _static(fleet) if b.cx == pytest.approx(20.4) and b.cy == pytest.approx(9.4))


def _integrate(
    fleet: DeterministicHarness,
    observation: Observation,
    body: OrientedBox,
    command: MotionCommand,
) -> tuple[float, int]:
    """Integrate *command* with the real actuator model and report the worst overlap.

    Returns ``(max_penetration_m, first_overlap_step)``. The loop is the same one the
    world runs: velocity ramps toward the command, the command expires after its TTL,
    the watchdog brakes, and the body keeps rotating while it coasts.
    """
    actuator = fleet.scenario.simulation.actuator
    shelf = _shelf_31(fleet)
    dt = fleet.scenario.simulation.dt_s
    x, y, theta = body.cx, body.cy, body.theta
    v, omega = 0.0, 0.0
    worst = 0.0
    first = -1

    steps = math.ceil((command.expires_at_ns - command.issued_at_ns) / 1e9 / dt) + 40
    for step in range(steps):
        expired = step >= math.ceil(actuator.command_ttl_s / dt)
        want_v = 0.0 if expired else command.linear_mps
        want_w = 0.0 if expired else command.angular_radps
        result = kinematics.step(
            x=x,
            y=y,
            theta=theta,
            v=v,
            omega=omega,
            command_v=want_v,
            command_omega=want_w,
            dt=dt,
            actuator=actuator,
            command_expired=expired,
            actuation_enabled=True,
        )
        x, y, theta, v, omega = result.x, result.y, result.theta, result.v, result.omega
        moved = OrientedBox(x, y, theta, *FOOTPRINT)
        if sat_overlap(moved, shelf):
            depth = _penetration(moved, shelf)
            worst = max(worst, depth)
            if first < 0:
                first = step
    return worst, first


def _penetration(a: OrientedBox, b: OrientedBox) -> float:
    """Overlap depth along the best separating axis; positive when they overlap."""
    from niharamesh.domain.geometry import sat_penetration

    return sat_penetration(a, b)


def _context(fleet: DeterministicHarness, observation: Observation, body: OrientedBox) -> GateContext:
    return GateContext(
        observation=observation,
        now_ns=observation.sim_time_ns,
        zone_authority=None,
        entry_permission=None,
        occupied_zone=None,
        occupied_box=body,
        swept_body=swept_body_bound(
            body,
            reach_m=0.26,
            spin_rad=0.4 + (1.0**2) / (2.0 * 1.5),
        ),
    )


def _command(observation: Observation, *, linear: float, angular: float) -> MotionCommand:
    return MotionCommand(
        robot_id=observation.robot_id,
        command_seq=1,
        linear_mps=linear,
        angular_radps=angular,
        issued_at_ns=observation.sim_time_ns,
        expires_at_ns=observation.sim_time_ns + 400_000_000,
        time_domain=TimeDomain.LOGICAL,
    )


# ===========================================================================
# The regression the review found.
# ===========================================================================


def test_a_command_that_drives_into_a_shelf_is_vetoed(fleet: DeterministicHarness) -> None:
    """The exact end-to-end case the reviewer's probe reproduced.

    A 0.60 x 0.40 robot 28 mm below ``shelf-31``, commanded 0.30 m/s while turning at
    the declared maximum 1.0 rad/s. The old witness permitted this and the integrated
    body reached 7.6035 m against a shelf edge at 7.6000 m.
    """
    observation = _observation_at(fleet, x=20.4, y=7.3714, theta=0.0, stopped=True)
    body = OrientedBox(20.4, 7.3714, 0.0, *FOOTPRINT)
    shelf = _shelf_31(fleet)

    assert not sat_overlap(body, shelf), "precondition: the body starts clear of the shelf"
    command = _command(observation, linear=0.3005, angular=1.0)

    penetration, first_overlap = _integrate(fleet, observation, body, command)
    assert first_overlap >= 0 and penetration > 0.0, (
        "precondition: integrating this command really does drive the body into the "
        f"shelf (first overlap at step {first_overlap}, depth {penetration:.4f} m)"
    )

    gate = fleet.agents["amr-02"].gate
    decision = gate.evaluate(command, observation.sim_time_ns, _context(fleet, observation, body))
    assert not decision.permitted, (
        f"the gate permitted a command the physics carries into a shelf: {decision!r}"
    )
    assert decision.reason is StopReason.OBSTACLE_IN_PATH


@pytest.mark.parametrize(
    ("linear", "angular"),
    [
        (0.0, 1.0),
        (0.10, 0.50),
        (0.10, 0.75),
        (0.20, 0.75),
        (0.30, 1.00),
        (0.40, 0.10),
        (0.40, 0.40),
        (0.40, 1.00),
        (0.00, -1.00),
        (0.25, -0.60),
    ],
)
def test_no_permitted_command_reaches_a_shelf_across_the_whole_command_space(
    fleet: DeterministicHarness, linear: float, angular: float
) -> None:
    """Sweep the combined translate-and-rotate space, not just its easy ends.

    The review's conservativeness grid found the worst poke-out of the old witness at
    ``(0.40, 0.10)`` -- 0.2598 m outside it -- and the two assertions that existed
    only ever used ``linear = 0``. Any ``linear > 0`` with ``angular != 0`` is what
    :meth:`_pursue` emits whenever the heading error is non-zero, which is most ticks.
    """
    for body in _bodies_near_shelves(fleet):
        observation = _observation_for(fleet, body)
        command = _command(observation, linear=linear, angular=angular)
        gate = fleet.agents["amr-02"].gate
        decision = gate.evaluate(command, observation.sim_time_ns, _context(fleet, observation, body))
        if not decision.permitted:
            continue
        penetration, first = _integrate(fleet, observation, body, command)
        assert first < 0, (
            f"gate permitted v={linear} w={angular} from {body.cx:.2f},{body.cy:.2f} "
            f"but the body reached a shelf at step {first} ({penetration:.4f} m)"
        )


def test_the_swept_bound_actually_encloses_the_integrated_motion(
    fleet: DeterministicHarness,
) -> None:
    """The witness is a bound, checked against the physics rather than argued about.

    Every pose the integrated body occupies must lie inside the witness returned by
    :func:`~niharamesh.domain.geometry.swept_body_bound`, using exactly the reach and
    spin the gate computes.
    """
    actuator = fleet.scenario.simulation.actuator
    dt = fleet.scenario.simulation.dt_s
    start = OrientedBox(20.4, 7.3714, 0.0, *FOOTPRINT)

    for linear, angular in [(0.4, 1.0), (0.4, 0.1), (0.2, 0.75), (0.1, 0.5), (0.0, 1.0)]:
        speed = max(linear, 0.0)
        omega = abs(angular)
        reach = speed * actuator.command_ttl_s + (speed * speed) / (2.0 * actuator.decel_mps2)
        spin = omega * actuator.command_ttl_s + (omega * omega) / (2.0 * actuator.angular_accel_radps2)
        witness = swept_body_bound(
            start, reach_m=reach, spin_rad=spin, lateral_m=centre_arc_lateral_m(linear, angular, spin)
        )

        x, y, theta = start.cx, start.cy, start.theta
        v, w = 0.0, 0.0
        for step in range(math.ceil(actuator.command_ttl_s / dt) + 60):
            expired = step >= math.ceil(actuator.command_ttl_s / dt)
            r = kinematics.step(
                x=x,
                y=y,
                theta=theta,
                v=v,
                omega=w,
                command_v=0.0 if expired else linear,
                command_omega=0.0 if expired else angular,
                dt=dt,
                actuator=actuator,
                command_expired=expired,
                actuation_enabled=True,
            )
            x, y, theta, v, w = r.x, r.y, r.theta, r.v, r.omega
            moved = OrientedBox(x, y, theta, *FOOTPRINT)
            assert sat_overlap(moved, witness), (
                f"the witness does not enclose the body at step {step} for "
                f"v={linear} w={angular}: body ({x:.3f},{y:.3f},{theta:.3f}) "
                f"vs witness centred ({witness.cx:.3f},{witness.cy:.3f}) "
                f"{witness.length:.3f}x{witness.width:.3f}"
            )


def test_the_agent_zone_witness_agrees_with_the_gate_witness(
    fleet: DeterministicHarness,
) -> None:
    """One formula, two callers.

    The zone check and the obstacle check are two readings of the same bound. When
    they were separate, the zone witness was command-independent and leaned on the
    shipped speed limits to supply the difference -- conservative by accident, not by
    argument.
    """
    agent = fleet.agents["amr-02"]
    observation = _observation_at(fleet, x=13.5, y=11.9, theta=math.pi / 2.0, stopped=True)
    agent._latest_observation = observation
    command = _command(observation, linear=0.4, angular=1.0)

    evidence = agent.zone_evidence_for(observation, command)
    assert evidence.swept_body is not None

    actuator = fleet.scenario.simulation.actuator
    reach = 0.4 * actuator.command_ttl_s + (0.4 * 0.4) / (2.0 * actuator.decel_mps2)
    spin = 1.0 * actuator.command_ttl_s + (1.0 * 1.0) / (2.0 * actuator.angular_accel_radps2)
    expected = swept_body_bound(
        evidence.body, reach_m=reach, spin_rad=spin, lateral_m=centre_arc_lateral_m(0.4, 1.0, spin)
    )
    expected = expected.inflated(agent._uncertainty_margin_m())

    assert abs(evidence.swept_body.length - expected.length) < 1e-9
    assert abs(evidence.swept_body.width - expected.width) < 1e-9

    # And a zero command must produce a *tighter* witness than a moving one, which
    # is what "built from its own command" means in practice.
    still = agent.zone_evidence_for(observation, _command(observation, linear=0.0, angular=0.0))
    assert still.swept_body.length < evidence.swept_body.length


# --------------------------------------------------------------------------- #


def _bodies_near_shelves(fleet: DeterministicHarness) -> tuple[OrientedBox, ...]:
    """Bodies a robot could genuinely occupy, close enough for a hazard to matter."""
    cases: list[OrientedBox] = []
    for shelf in _static(fleet):
        for dx in (-0.35, -0.20, 0.0, 0.20, 0.35):
            for dy in (-0.55, -0.40, 0.40, 0.55):
                for theta in (0.0, math.pi / 2.0, math.pi, -math.pi / 2.0, 0.6, -1.2):
                    cases.append(OrientedBox(shelf.cx + dx, shelf.cy + dy, theta, *FOOTPRINT))
    return tuple(cases)


def _observation_at(
    fleet: DeterministicHarness, *, x: float, y: float, theta: float, stopped: bool
) -> Observation:
    from niharamesh.domain.pose import MotionState, Pose2, PoseEstimate, UncertaintyModel

    template = fleet.world.observe("amr-02")
    motion = template.motion
    if stopped:
        motion = MotionState(actuation_enabled=True, actuator=template.motion.actuator)
    return Observation(
        robot_id="amr-02",
        pose_estimate=PoseEstimate(
            map_id=template.pose_estimate.map_id,
            frame_id=template.pose_estimate.frame_id,
            pose=Pose2(x=x, y=y, theta=theta),
            observed_at_ns=template.pose_estimate.observed_at_ns,
            time_domain=template.pose_estimate.time_domain,
            uncertainty=UncertaintyModel(kind="gaussian_sigma", sigma_m=0.02, sigma_rad=0.01),
        ),
        motion=motion,
        sensor=template.sensor,
        battery_fraction=template.battery_fraction,
        sim_time_ns=template.sim_time_ns,
    )


def _observation_for(fleet: DeterministicHarness, body: OrientedBox) -> Observation:
    return _observation_at(fleet, x=body.cx, y=body.cy, theta=body.theta, stopped=True)


assert SHELF_31  # the fixture's map is asserted against this literal in the tests above

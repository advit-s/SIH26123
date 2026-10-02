"""The world applies commands. It never prevents them.

Every test in the first group is a guard against the failure mode the brief calls
out by name: *"The physics engine must not conceal unsafe control by refusing all
colliding motion or teleporting a robot away from an obstacle."* If any of these
regress, a clean-looking run no longer means a safe run.

The second group covers the authority boundary (invariant 3): a robot's
observation must not reveal another robot's exact pose, task ownership, or the
evaluator's verdict. The last group covers battery, services, payloads and
dynamic obstacles, where an invented number would be worse than a missing one.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from niharamesh.domain.config import SimulationConfig
from niharamesh.domain.geometry import sat_overlap
from niharamesh.domain.identity import Capability, RobotIdentity
from niharamesh.domain.map import MapBoundary, Station, StationKind, WarehouseMap
from niharamesh.domain.pose import ActuatorState, Footprint, MotionCommand, StopReason
from niharamesh.domain.scenario import (
    IntentDescription,
    RobotStart,
    RunPolicy,
    Scenario,
    ScenarioSnapshot,
)
from niharamesh.domain.task import Task
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import WorldPort
from niharamesh.safety.collision import (
    CollisionKind,
    resolve_collision_report,
    swept_body_overlap,
)
from niharamesh.simulator.world import World

_FOOTPRINT = Footprint(
    length_m=0.80,
    width_m=0.60,
    payload_length_m=0.70,
    payload_width_m=0.50,
    payload_offset_m=0.45,
)
_DT = 1.0 / 20.0


def _config(**overrides: object) -> SimulationConfig:
    base = SimulationConfig(
        physics_step_hz=20,
        physical_actuation_enabled=True,
    )
    return base.model_copy(update=dict(overrides)) if overrides else base


def _map(obstacles: tuple[object, ...] = ()) -> WarehouseMap:
    return WarehouseMap(
        map_id="world-test",
        boundary=MapBoundary(min_x=-10.0, min_y=-10.0, max_x=10.0, max_y=10.0),
        obstacles=obstacles,  # type: ignore[arg-type]
        grid_resolution_m=0.1,
        nominal_aisle_width_m=1.4,
    )


def _snapshot(
    starts: tuple[tuple[str, float, float, float], ...],
    *,
    tasks: tuple[Task, ...] = (),
    obstacles: tuple[object, ...] = (),
    config: SimulationConfig | None = None,
) -> ScenarioSnapshot:
    identities = tuple(
        RobotIdentity(
            robot_id=robot_id,
            capabilities=(Capability.CARRY_PAYLOAD,),
            footprint=_FOOTPRINT,
        )
        for robot_id, _, _, _ in starts
    )
    scenario = Scenario(
        scenario_id="world-test",
        name="world test",
        intent=IntentDescription(goal="exercise the world"),
        map=_map(obstacles),
        robots=identities,
        starts=tuple(
            RobotStart(robot_id=robot_id, pose=_pose2(x, y, theta)) for robot_id, x, y, theta in starts
        ),
        tasks=tasks,
        policy=RunPolicy(),
        simulation=config or _config(),
    )
    return ScenarioSnapshot.freeze(scenario, created_utc_ns=0)


def _pose2(x: float, y: float, theta: float = 0.0):  # type: ignore[no-untyped-def]
    from niharamesh.domain.pose import Pose2

    return Pose2(x=x, y=y, theta=theta)


def _command(
    robot_id: str,
    *,
    seq: int,
    linear: float,
    angular: float = 0.0,
    ttl_s: float = 0.4,
    at_ns: int = 0,
    domain: TimeDomain = TimeDomain.LOGICAL,
) -> MotionCommand:
    return MotionCommand(
        robot_id=robot_id,
        command_seq=seq,
        linear_mps=linear,
        angular_radps=angular,
        issued_at_ns=at_ns,
        expires_at_ns=at_ns + int(ttl_s * 1e9),
        time_domain=domain,
    )


# --------------------------------------------------------------------------- #
# The world does not prevent collisions
# --------------------------------------------------------------------------- #


def test_two_robots_commanded_into_each_other_actually_collide() -> None:
    """Head-on commands are applied, and the penetration is real when they meet.

    This is the acceptance test for the brief's central warning. A world that
    refuses, clamps or separates the bodies never produces a positive penetration,
    so a run that cannot collide also cannot produce evidence that the safety
    mechanisms work.

    The evidence is taken *across* the run, not at the end: an applied collision
    leaves both bodies still overlapping, whereas a world that quietly pushed them
    apart would show no penetration at any instant.
    """
    world = World(_snapshot((("r1", -3.0, 0.0, 0.0), ("r2", 3.0, 0.0, math.pi))))

    assert world.apply_command(_command("r1", seq=1, linear=0.4, at_ns=0))
    assert world.apply_command(_command("r2", seq=1, linear=0.4, at_ns=0))

    deepest = 0.0
    overlapped = False
    # Reissue every tick, exactly as a control loop does: a single 0.4 s command
    # would expire long before the robots covered the 6 m between them.
    for seq in range(2, 400):
        now = world.sim_time_ns
        world.apply_command(_command("r1", seq=seq, linear=0.4, at_ns=now))
        world.apply_command(_command("r2", seq=seq, linear=0.4, at_ns=now))
        world.step(_DT)

        bodies = world.bodies_for_evaluation()
        report = resolve_collision_report(
            bodies,
            sim_time_ns=world.sim_time_ns,
            static_boxes=world.static_boxes_for_evaluation(),
            boundary=world.map.boundary,
        )
        if report.collided:
            overlapped = True
            assert CollisionKind.ROBOT_ROBOT in report.kinds
            assert report.robot_ids == ("r1", "r2")
            deepest = max(deepest, report.penetration_m)
            if sat_overlap(bodies["r1"][0], bodies["r2"][0]):
                truth = world.truth()
                separation = math.hypot(
                    truth.robots["r1"].x - truth.robots["r2"].x,
                    truth.robots["r1"].y - truth.robots["r2"].y,
                )
                assert separation < _FOOTPRINT.length_m

    assert overlapped, "the world prevented a collision it should have applied"
    assert deepest > 0.0, "a reported collision with no penetration is not a collision"
    assert deepest < _FOOTPRINT.length_m, (
        f"penetration {deepest:.3f} m exceeds the chassis length; the bodies were "
        "teleported rather than driven"
    )


def test_a_robot_driven_into_a_wall_is_not_stopped_by_the_wall() -> None:
    """The world integrates the command into the obstacle and leaves it inside.

    A world that clamped the position at the wall would make every downstream
    clearance measurement meaningless, because the penetration would never appear.
    """
    wall = _map((_obstacle("shelf1", 2.0, 0.0, 0.2, 4.0),))
    world = World(_snapshot((("r1", -3.0, 0.0, 0.0),), obstacles=wall.obstacles))

    assert world.apply_command(_command("r1", seq=1, linear=0.4, at_ns=0))
    deepest = 0.0
    furthest_x = -3.0
    for seq in range(2, 300):
        world.apply_command(_command("r1", seq=seq, linear=0.4, at_ns=world.sim_time_ns))
        world.step(_DT)
        furthest_x = max(furthest_x, world.truth().robots["r1"].x)
        report = resolve_collision_report(
            world.bodies_for_evaluation(),
            sim_time_ns=world.sim_time_ns,
            static_boxes=world.static_boxes_for_evaluation(),
        )
        if CollisionKind.ROBOT_OBSTACLE in report.kinds:
            deepest = max(deepest, report.penetration_m)

    assert deepest > 0.0, "the robot stopped at the wall instead of entering it"
    assert furthest_x > 2.0, "the robot was held on the near side of the obstacle"


def _obstacle(obstacle_id: str, x: float, y: float, length: float, width: float):  # type: ignore[no-untyped-def]
    from niharamesh.domain.map import Obstacle

    return Obstacle(id=obstacle_id, pose=_pose2(x, y, 0.0), length_m=length, width_m=width)


def test_apply_command_refuses_nothing_about_safety() -> None:
    """A command aimed straight through a wall is accepted, not vetoed.

    Refusal is reserved for authority questions: unknown robot, wrong clock domain,
    a stale sequence, or actuation disabled.
    """
    wall = _map((_obstacle("shelf1", 2.0, 0.0, 0.2, 4.0),))
    world = World(_snapshot((("r1", -3.0, 0.0, 0.0),), obstacles=wall.obstacles))
    assert world.apply_command(_command("r1", seq=1, linear=0.4)) is True


def test_a_command_for_an_unknown_robot_is_refused() -> None:
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert world.apply_command(_command("r9", seq=1, linear=0.4)) is False


def test_a_command_in_the_wrong_clock_domain_is_refused() -> None:
    """Comparing a monotonic expiry against logical time is the mistake invariant 8 forbids."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert world.apply_command(_command("r1", seq=1, linear=0.4, domain=TimeDomain.MONOTONIC)) is False


def test_a_replayed_command_sequence_is_refused() -> None:
    """A reordered or replayed command is not a new instruction."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert world.apply_command(_command("r1", seq=5, linear=0.2)) is True
    assert world.apply_command(_command("r1", seq=5, linear=0.0)) is False
    assert world.apply_command(_command("r1", seq=4, linear=0.0)) is False
    assert world.apply_command(_command("r1", seq=6, linear=0.3)) is True


def test_actuation_is_disabled_by_default_and_commands_are_refused() -> None:
    """Physical actuation ships off. A disabled world must not move anything."""
    config = SimulationConfig(physics_step_hz=20)
    assert config.physical_actuation_enabled is False
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),), config=config))
    assert world.apply_command(_command("r1", seq=1, linear=0.4)) is False
    before = world.truth().robots["r1"]
    for _ in range(20):
        world.step(_DT)
    after = world.truth().robots["r1"]
    assert (after.x, after.y) == (before.x, before.y)


def test_the_world_satisfies_the_declared_port() -> None:
    """Structural check that the port contract is actually implemented."""
    assert isinstance(World(_snapshot((("r1", 0.0, 0.0, 0.0),))), WorldPort)


# --------------------------------------------------------------------------- #
# Watchdog
# --------------------------------------------------------------------------- #


def test_an_expired_command_triggers_watchdog_braking_and_a_coast_to_rest() -> None:
    """Momentum must decay over several steps, never vanish in one.

    The command is held live for ten ticks so the ramp reaches the speed limit,
    then simply not renewed. Nothing else changes: the robot must coast to rest on
    the declared deceleration and report the watchdog as its reason.
    """
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert world.apply_command(_command("r1", seq=1, linear=0.4, at_ns=0))

    speeds: list[float] = []
    live_ticks = 20
    for index in range(40):
        if index < live_ticks:
            world.apply_command(
                _command("r1", seq=index + 2, linear=0.4, at_ns=world.sim_time_ns)
            )
        world.step(_DT)
        speeds.append(world.truth().robots["r1"].v)

    assert max(speeds) == pytest.approx(0.4, abs=1e-9), "the ramp never reached the limit"
    assert speeds[-1] == 0.0, "the robot never stopped"
    intermediate = [v for v in speeds if 0.0 < v < max(speeds)]
    assert len(intermediate) >= 3, f"momentum vanished rather than decayed: {speeds}"

    # Only the coast is required to be monotone: the first ten ticks accelerate.
    coast = speeds[speeds.index(max(speeds)) :]
    assert coast == sorted(coast, reverse=True), f"the coast is not monotone: {coast}"
    assert coast[0] == pytest.approx(0.4, abs=1e-9)

    observation = world.observe("r1")
    assert observation.motion.actuator is ActuatorState.WATCHDOG_BRAKING
    assert observation.motion.stop_reason is StopReason.COMMAND_EXPIRED
    assert observation.motion.commanded_linear_mps == 0.4, "the issued command is still reported"


def test_a_robot_that_never_received_a_command_is_disabled_not_braking() -> None:
    """Watchdog braking means "a command went stale", which is not the same as idle."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    world.step(_DT)
    motion = world.observe("r1").motion
    assert motion.actuator is ActuatorState.DISABLED
    assert motion.stop_reason is StopReason.NONE


def test_the_watchdog_braking_distance_matches_the_analytic_value() -> None:
    """The coast after expiry must equal ``v**2 / (2a)`` for the speed actually held.

    Ramping 0 -> 0.4 m/s at 0.5 m/s^2 takes 0.8 s, so the command is held live for
    40 ticks (2 s) before being left to expire. Comparing against the *requested*
    speed limit rather than the held speed would make the assertion 10x too loose to
    catch anything; comparing from the start of the run rather than from expiry
    would include the ramp-up travel and never match.
    """
    config = _config()
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),), config=config))
    world.apply_command(_command("r1", seq=1, linear=config.actuator.max_linear_mps, at_ns=0))

    live_ticks = 40
    for index in range(live_ticks):
        world.apply_command(
            _command(
                "r1",
                seq=index + 2,
                linear=config.actuator.max_linear_mps,
                at_ns=world.sim_time_ns,
            )
        )
        world.step(_DT)

    # Step until the world itself reports the watchdog, remembering the last pose
    # at which the command was still live. That pose is the analytic starting point:
    # the step that trips the watchdog already applies the first decrement, so
    # measuring from *after* it would compare two different initial speeds.
    x_live = world.truth().robots["r1"].x
    v_live = world.truth().robots["r1"].v
    for _ in range(60):
        world.step(_DT)
        if world.observe("r1").motion.actuator is ActuatorState.WATCHDOG_BRAKING:
            break
        x_live = world.truth().robots["r1"].x
        v_live = world.truth().robots["r1"].v
    else:  # pragma: no cover - would mean the watchdog never fired
        raise AssertionError("the watchdog never fired")

    assert v_live == pytest.approx(config.actuator.max_linear_mps, abs=1e-9)

    for _ in range(60):
        world.step(_DT)
    coast = world.truth().robots["r1"].x - x_live

    analytic = v_live**2 / (2.0 * config.actuator.decel_mps2)
    assert analytic == pytest.approx(config.stopping.braking_distance_m, rel=1e-6)
    assert world.truth().robots["r1"].v == 0.0, "the robot never came to rest"
    assert coast == pytest.approx(analytic, rel=0.02)


# --------------------------------------------------------------------------- #
# Authority boundary
# --------------------------------------------------------------------------- #


def test_observe_exposes_no_other_robots_exact_pose() -> None:
    """Robot r1's observation must not reveal where r2 actually is.

    The assertion is on the observation's whole surface, not one field: a leak
    through a derived attribute or a nested object would slip past a single check.
    """
    world = World(_snapshot((("r1", -2.0, 0.0, 0.0), ("r2", 2.0, 0.5, 0.0))))
    world.apply_command(_command("r1", seq=1, linear=0.2))
    world.step(_DT)
    truth_r2 = world.truth().robots["r2"]
    observation = world.observe("r1")

    assert observation.robot_id == "r1"
    # There is no collection of peers anywhere on the result.
    for name in dir(observation):
        if name.startswith("_"):
            continue
        attribute = getattr(observation, name)
        if callable(attribute):
            continue
        assert not isinstance(attribute, (list, tuple, dict, set)), (
            f"Observation.{name} is a collection; it could carry peer state"
        )

    # The scan mentions a distance to the peer, never a position.
    assert observation.sensor.rays, "the scan should exist"
    for ray in observation.sensor.rays:
        assert not hasattr(ray, "x")
        assert not hasattr(ray, "y")
        assert not hasattr(ray, "theta")
    assert all(ray.kind in ("obstacle", "boundary", "robot", "free") for ray in observation.sensor.rays)

    # The self estimate is its own, and is explicitly uncertain rather than exact.
    assert observation.pose_estimate.pose.x != pytest.approx(truth_r2.x, abs=1e-9)
    assert observation.pose_estimate.uncertainty.kind == "gaussian_sigma"


def test_observe_does_not_leak_the_evaluators_collision_verdict() -> None:
    """r1 must not learn that it is in collision; only the evaluator may."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0), ("r2", 0.2, 0.0, 0.0))))
    observation = world.observe("r1")
    for name in dir(observation):
        if name.startswith("_"):
            continue
        assert "collision" not in name.lower()
        assert "penetration" not in name.lower()
    assert not hasattr(observation, "truth")
    assert not hasattr(observation, "bodies_for_evaluation")


def test_observe_reports_own_custody_but_not_a_peers() -> None:
    tasks = (
        Task(
            task_id="t1",
            pickup_station_id="s1",
            drop_station_id="s2",
            required_capabilities=("CARRY_PAYLOAD",),
        ),
    )
    world = World(
        _snapshot(
            (("r1", 0.0, 0.0, 0.0), ("r2", 2.0, 0.0, 0.0)),
            tasks=tasks,
        )
    )
    assert world.attach_payload("r1", "t1")
    assert world.carrying("r1") == "t1"
    assert world.carrying("r2") is None


def test_only_evaluation_accessors_reveal_exact_geometry() -> None:
    """The truth surface is small, named, and documented as evaluator-only."""
    doc = World.truth.__doc__ or ""
    assert "Evaluator" in doc
    doc_bodies = World.bodies_for_evaluation.__doc__ or ""
    assert "Evaluator" in doc_bodies


# --------------------------------------------------------------------------- #
# Battery, services, payloads, dynamic obstacles
# --------------------------------------------------------------------------- #


def test_battery_decreases_and_never_goes_below_zero() -> None:
    config = _config()
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),), config=config))
    start = world.truth().robots["r1"].battery
    assert start == pytest.approx(config.battery.start_fraction)

    world.apply_command(_command("r1", seq=1, linear=0.4, at_ns=0))
    fractions = []
    for seq in range(2, 200):
        world.apply_command(_command("r1", seq=seq, linear=0.4, at_ns=world.sim_time_ns))
        world.step(_DT)
        fractions.append(world.truth().robots["r1"].battery)

    assert all(0.0 <= f <= 1.0 for f in fractions), "battery left its declared range"
    assert fractions[-1] < fractions[0], "battery did not decrease while driving"
    assert all(
        later <= earlier for earlier, later in pairwise(fractions)
    ), "battery increased"
    # Driving drains more than idling: the per-metre term is a real term.
    idle = World(_snapshot((("r1", 0.0, 0.0, 0.0),), config=config))
    for _ in range(198):
        idle.step(_DT)
    assert idle.truth().robots["r1"].battery > fractions[-1]

    # The drain matches the declared model rather than an arbitrary curve.
    travelled = math.hypot(world.truth().robots["r1"].x, world.truth().robots["r1"].y)
    expected = config.battery.start_fraction - (
        travelled * config.battery.drain_per_metre_c
        + 198 * _DT * config.battery.drain_per_second_idle_c
    )
    assert fractions[-1] == pytest.approx(expected, abs=1e-9)


def test_battery_floors_at_zero_without_the_robot_vanishing() -> None:
    """An empty pack must not remove the robot; it still occupies space."""
    drained = _config(battery=_config().battery.model_copy(update={"drain_per_metre_c": 1.0}))
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),), config=drained))
    for seq in range(1, 60):
        world.apply_command(_command("r1", seq=seq, linear=0.4, at_ns=world.sim_time_ns))
        world.step(_DT)

    truth = world.truth()
    assert truth.robots["r1"].battery == 0.0
    assert "r1" in truth.robots
    assert world.bodies_for_evaluation()["r1"]


def test_a_station_service_completes_exactly_once() -> None:
    tasks = (
        Task(
            task_id="t1",
            pickup_station_id="pick",
            drop_station_id="drop",
            required_capabilities=("CARRY_PAYLOAD",),
        ),
    )
    world_map = _map().model_copy(
        update={
            "stations": (
                Station(id="pick", kind=StationKind.PICKUP, pose=_pose2(0.0, 0.0, 0.0)),
                Station(id="drop", kind=StationKind.DROP, pose=_pose2(1.0, 0.0, 0.0)),
            )
        }
    )
    scenario = Scenario(
        scenario_id="service-test",
        name="service",
        intent=IntentDescription(goal="service a station"),
        map=world_map,
        robots=(RobotIdentity(robot_id="r1", footprint=_FOOTPRINT),),
        starts=(RobotStart(robot_id="r1", pose=_pose2(0.0, 0.0, 0.0)),),
        tasks=tasks,
        simulation=_config(),
    )
    world = World(ScenarioSnapshot.freeze(scenario, created_utc_ns=0))

    assert world.begin_service("r1", "pick", 0.2)
    assert not world.begin_service("r1", "drop", 0.2), "a busy robot must not start twice"

    completions = 0
    for _ in range(20):
        world.step(_DT)
        completions += int(world.service_complete("r1"))
    assert completions == 1, "service completion must fire exactly once"
    assert world.observe("r1").motion.stop_reason is StopReason.WORKLOAD_COMPLETE


def test_service_is_refused_when_the_robot_is_not_at_the_station() -> None:
    """A world rule, not coordination: you cannot be served where you are not."""
    world_map = _map().model_copy(
        update={"stations": (Station(id="pick", kind=StationKind.PICKUP, pose=_pose2(5.0, 5.0, 0.0)),)}
    )
    scenario = Scenario(
        scenario_id="service-far",
        name="service",
        intent=IntentDescription(goal="service a station"),
        map=world_map,
        robots=(RobotIdentity(robot_id="r1", footprint=_FOOTPRINT),),
        starts=(RobotStart(robot_id="r1", pose=_pose2(0.0, 0.0, 0.0)),),
        simulation=_config(),
    )
    world = World(ScenarioSnapshot.freeze(scenario, created_utc_ns=0))
    assert not world.begin_service("r1", "pick", 0.2)


def test_payload_custody_is_physical_and_exclusive() -> None:
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert world.attach_payload("r1", "t1")
    assert not world.attach_payload("r1", "t2"), "a loaded robot cannot take a second load"
    assert world.detach_payload("r1") == "t1"
    assert world.detach_payload("r1") is None
    assert world.attach_payload("r1", "t2")


def test_a_carried_payload_adds_a_body_to_the_evaluator_geometry() -> None:
    """Loading a robot must change the geometry that collision checking sees."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    assert len(world.bodies_for_evaluation()["r1"]) == 1
    assert world.attach_payload("r1", "t1")
    assert len(world.bodies_for_evaluation()["r1"]) == 2


def test_dynamic_obstacles_insert_and_remove() -> None:
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    before = len(world.static_boxes_for_evaluation())

    assert world.insert_obstacle("spill", 1.0, 0.0, 0.0, 0.8, 0.8)
    assert not world.insert_obstacle("spill", 2.0, 0.0), "duplicate id must be refused"
    assert len(world.static_boxes_for_evaluation()) == before + 1
    assert len(world.truth().dynamic_obstacles) == 1

    assert world.remove_obstacle("spill")
    assert not world.remove_obstacle("spill")
    assert len(world.static_boxes_for_evaluation()) == before


def test_an_injected_obstacle_becomes_collidable_immediately() -> None:
    """Fault injection must change what collision checking can see."""
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    world.insert_obstacle("spill", 0.0, 0.0, 0.0, 1.0, 1.0)
    report = resolve_collision_report(
        world.bodies_for_evaluation(),
        sim_time_ns=world.sim_time_ns,
        static_boxes=world.static_boxes_for_evaluation(),
    )
    assert CollisionKind.ROBOT_OBSTACLE in report.kinds
    assert report.penetration_m > 0.0


def test_a_robot_driven_through_an_injected_obstacle_is_detected_by_the_swept_checker() -> None:
    """The swept checker sees the crossing the evaluator would otherwise miss."""
    world = World(_snapshot((("r1", -3.0, 0.0, 0.0),)))
    world.insert_obstacle("spill", -1.0, 0.0, 0.0, 0.05, 1.2)
    hit = False
    for seq in range(1, 300):
        world.apply_command(_command("r1", seq=seq, linear=0.4, at_ns=world.sim_time_ns))
        previous = world.truth().robots["r1"]
        world.step(_DT)
        current = world.truth().robots["r1"]
        for box in world.static_boxes_for_evaluation():
            if swept_body_overlap(_obb(previous), _obb(current), box):
                hit = True
    assert hit, "the robot passed through the injected obstacle undetected"


def _obb(truth: object) -> object:  # type: ignore[no-untyped-def]
    from niharamesh.domain.geometry import OrientedBox

    return OrientedBox(
        truth.x,
        truth.y,
        truth.theta,
        _FOOTPRINT.length_m,
        _FOOTPRINT.width_m,  # type: ignore[attr-defined]
    )


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_two_worlds_from_the_same_snapshot_produce_identical_runs() -> None:
    """Same snapshot, same commands, same observations -- byte for byte."""

    def run() -> list[tuple[object, ...]]:
        world = World(_snapshot((("r1", -1.0, 0.0, 0.0), ("r2", 1.5, 0.3, 0.2))))
        out: list[tuple[object, ...]] = []
        for seq in range(1, 61):
            now = world.sim_time_ns
            world.apply_command(_command("r1", seq=seq, linear=0.3, at_ns=now))
            world.apply_command(_command("r2", seq=seq, linear=0.2, angular=0.4, at_ns=now))
            world.step(_DT)
            for robot_id in ("r1", "r2"):
                observation = world.observe(robot_id)
                out.append(
                    (
                        robot_id,
                        round(observation.pose_estimate.pose.x, 12),
                        round(observation.pose_estimate.pose.y, 12),
                        round(observation.sensor.observed_at_ns, 12),
                        tuple(
                            (round(r.bearing_rad, 12), round(r.distance_m, 12), r.kind)
                            for r in observation.sensor.rays
                        ),
                    )
                )
        return out

    assert run() == run()


def test_the_world_clock_only_ever_moves_forward() -> None:
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    previous = world.sim_time_ns
    for _ in range(10):
        world.step(_DT)
        assert world.sim_time_ns > previous
        previous = world.sim_time_ns
    assert world.sim_time_ns == round(10 * _DT * 1e9)


def test_a_negative_step_is_rejected() -> None:
    world = World(_snapshot((("r1", 0.0, 0.0, 0.0),)))
    with pytest.raises(ValueError, match="dt_s"):
        world.step(-_DT)


def test_reset_returns_the_world_to_its_snapshot_state() -> None:
    """Editing the scenario afterwards must never change a launched run."""
    snapshot = _snapshot((("r1", 0.0, 0.0, 0.0),))
    world = World(snapshot)
    world.apply_command(_command("r1", seq=1, linear=0.4))
    for _ in range(30):
        world.step(_DT)
    assert world.sim_time_ns > 0

    world.reset(snapshot)
    assert world.sim_time_ns == 0
    assert world.step_index == 0
    truth = world.truth().robots["r1"]
    assert (truth.x, truth.y, truth.v) == (0.0, 0.0, 0.0)

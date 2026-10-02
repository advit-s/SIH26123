"""Actuation semantics: two switches, not one (contract section A1).

``SimulationConfig`` used to carry a single ``physical_actuation_enabled`` flag and
answer two unrelated questions with it:

1. *May this command integrate against the declared actuator model?* (physics)
2. *May this command energise a real drive train?* (hardware boundary)

Question 2 must stay ``False`` in this repository, forever, unless a human opts
in. Question 1 must be ``True`` in the laboratory or the simulation cannot
demonstrate anything. Conflating them made ``World.apply_command`` refuse every
command, ``MotionState.actuation_enabled`` report ``False`` at boot, and the
safety gate's very first check veto every tick with ``ACTUATOR_FAULT`` /
``actuation_disabled`` -- so no robot could ever start.

Every test here names the invariant it defends. Tests 1 and 2 were the two
sides of the single reproduced defect; tests 3 and 4 defend the boundaries the
split must *not* erode.
"""

from __future__ import annotations

import math

import pydantic
import pytest

from niharamesh.domain.config import FeatureFlags, SimulationConfig
from niharamesh.domain.identity import Capability, RobotIdentity
from niharamesh.domain.map import MapBoundary, WarehouseMap
from niharamesh.domain.pose import Footprint, MotionCommand, Pose2
from niharamesh.domain.scenario import (
    IntentDescription,
    RobotStart,
    RunPolicy,
    Scenario,
    ScenarioSnapshot,
)
from niharamesh.domain.units import TimeDomain
from niharamesh.simulator.world import World

_FOOTPRINT = Footprint(length_m=0.60, width_m=0.40)
_DT = 1.0 / 20.0


def _map() -> WarehouseMap:
    return WarehouseMap(
        map_id="actuation-test",
        boundary=MapBoundary(min_x=-10.0, min_y=-10.0, max_x=10.0, max_y=10.0),
        grid_resolution_m=0.1,
        nominal_aisle_width_m=1.4,
    )


def _snapshot(config: SimulationConfig) -> ScenarioSnapshot:
    scenario = Scenario(
        scenario_id="actuation-test",
        name="actuation semantics",
        intent=IntentDescription(goal="exercise the two actuation switches"),
        map=_map(),
        robots=(
            RobotIdentity(robot_id="r1", capabilities=(Capability.CARRY_PAYLOAD,), footprint=_FOOTPRINT),
        ),
        starts=(RobotStart(robot_id="r1", pose=Pose2(x=-4.0, y=0.0, theta=0.0)),),
        policy=RunPolicy(),
        simulation=config,
    )
    return ScenarioSnapshot.freeze(scenario, created_utc_ns=0)


def _command(seq: int, *, linear: float, at_ns: int = 0) -> MotionCommand:
    return MotionCommand(
        robot_id="r1",
        command_seq=seq,
        linear_mps=linear,
        angular_radps=0.0,
        issued_at_ns=at_ns,
        expires_at_ns=at_ns + int(0.4 * 1e9),
        time_domain=TimeDomain.LOGICAL,
    )


# --------------------------------------------------------------------------- #
# The two switches exist and mean different things
# --------------------------------------------------------------------------- #


def test_default_config_declares_the_two_switches_separately() -> None:
    """The contract's exact defaults: simulated live, physical off."""
    config = SimulationConfig()
    assert config.simulated_actuation_enabled is True
    assert config.physical_actuation_enabled is False


def test_actuator_chain_live_is_the_only_thing_the_simulator_may_ask() -> None:
    """The derived helper, and the two combinations that produce it."""
    simulated_only = SimulationConfig()
    physical_only = SimulationConfig(simulated_actuation_enabled=False, physical_actuation_enabled=True)
    both = SimulationConfig(physical_actuation_enabled=True)
    neither = SimulationConfig(simulated_actuation_enabled=False)

    assert simulated_only.actuator_chain_live is True
    assert physical_only.actuator_chain_live is True
    assert both.actuator_chain_live is True
    assert neither.actuator_chain_live is False


def test_the_world_only_ever_consults_the_derived_helper() -> None:
    """Structural guard against the conflation creeping back in.

    A world that read the *hardware* switch anywhere would refuse every command
    in the laboratory again. This inspects the module's own code for that exact
    pattern rather than trusting review to keep noticing; prose in docstrings is
    deliberately not matched, because the module must be free to *describe* both
    switches.
    """
    import inspect

    from niharamesh.simulator import world as world_module

    source = inspect.getsource(world_module)
    assert "_config.physical_actuation_enabled" not in source
    assert "_config.actuator_chain_live" in source


# --------------------------------------------------------------------------- #
# Reproduced defect: the default laboratory run could not move a robot
# --------------------------------------------------------------------------- #


def test_the_default_config_moves_a_simulated_robot() -> None:
    """The defect itself, with nothing overridden.

    With the *default* ``SimulationConfig()`` -- ``physical_actuation_enabled``
    still ``False``, exactly as it must stay -- a valid command must be accepted
    and must integrate against the declared actuator model.

    Before the split this failed at ``world.apply_command(...) is True``: the
    world refused because the *hardware* switch was off, and the gate vetoed
    every tick with ``actuation_disabled`` because
    ``MotionState.actuation_enabled`` was ``False`` at boot.
    """
    config = SimulationConfig()
    world = World(_snapshot(config))
    start = world.truth().robots["r1"]

    assert world.apply_command(_command(1, linear=config.actuator.max_linear_mps, at_ns=0)) is True

    speeds: list[float] = []
    for seq in range(2, 200):
        world.apply_command(
            _command(
                seq,
                linear=config.actuator.max_linear_mps,
                at_ns=world.sim_time_ns,
            )
        )
        world.step(_DT)
        speeds.append(world.truth().robots["r1"].v)

    assert max(speeds) == pytest.approx(config.actuator.max_linear_mps, abs=1e-9), (
        "the declared actuator model never reached its own speed limit: the "
        f"commanded robot did not move ({max(speeds):.6f} m/s peak)"
    )
    moved = math.hypot(world.truth().robots["r1"].x - start.x, world.truth().robots["r1"].y - start.y)
    assert moved > 1.0, f"a commanded robot travelled only {moved:.3f} m"


def test_physical_actuation_still_refuses_when_the_simulated_chain_is_off() -> None:
    """Turning the *physics* switch off stops motion; the hardware one is untouched.

    ``simulated_actuation_enabled=False`` is the only supported way to freeze the
    fleet, and it must not require a human to opt into physical actuation to do it.
    """
    config = SimulationConfig(simulated_actuation_enabled=False)
    assert config.physical_actuation_enabled is False, "this test must not enable hardware"
    assert config.actuator_chain_live is False

    world = World(_snapshot(config))
    assert world.apply_command(_command(1, linear=0.4, at_ns=0)) is False

    before = world.truth().robots["r1"]
    for seq in range(2, 20):
        world.apply_command(_command(seq, linear=0.4, at_ns=world.sim_time_ns))
        world.step(_DT)
    after = world.truth().robots["r1"]
    assert (after.x, after.y, after.v) == (before.x, before.y, before.v)


# --------------------------------------------------------------------------- #
# Boundaries the split must not erode
# --------------------------------------------------------------------------- #


def test_physical_opt_in_with_an_unsafe_research_flag_still_raises() -> None:
    """Unchanged validator: hardware is never gated by a safety-weakening ablation."""
    with pytest.raises(pydantic.ValidationError, match="unsafe research flag"):
        SimulationConfig(
            physical_actuation_enabled=True,
            features=FeatureFlags(disable_safety_gate=True),
        )


def test_physical_opt_in_with_timer_expiry_ablation_still_raises() -> None:
    """The second unsafe flag must be refused too, not only the first one."""
    with pytest.raises(pydantic.ValidationError, match="unsafe research flag"):
        SimulationConfig(
            physical_actuation_enabled=True,
            features=FeatureFlags(timer_expiry_occupancy=True),
        )


def test_physical_opt_in_alone_is_still_accepted() -> None:
    """A human may still opt into hardware. The switch was not removed, only split."""
    config = SimulationConfig(physical_actuation_enabled=True)
    assert config.physical_actuation_enabled is True
    assert config.features.physical_actuation_permitted() is True
    assert config.actuator_chain_live is True


def test_the_hardware_switch_alone_makes_the_chain_live() -> None:
    """Opting into hardware without the simulated chain still accepts commands.

    Both switches feed one derived answer on purpose: a hardware-enabled drive
    train is obviously a live chain. What the world may *do* with real hardware
    is the hardware boundary's business, not the physics question's.
    """
    config = SimulationConfig(simulated_actuation_enabled=False, physical_actuation_enabled=True)
    world = World(_snapshot(config))
    assert world.apply_command(_command(1, linear=0.4, at_ns=0)) is True


def test_motion_state_reports_a_live_chain_at_boot() -> None:
    """``actuation_enabled`` is about the drive-train chain, not about history.

    Rationale in the contract: the gate's *first* check reads this field. If it
    were false until the first accepted command, the gate could never accept the
    first command, and no robot could ever start. The assertion is deliberately
    made before a single command exists.
    """
    world = World(_snapshot(SimulationConfig()))
    motion = world.observe("r1").motion
    assert motion.actuation_enabled is True
    assert motion.command_seq == 0, "the assertion must run before any command"
    assert motion.commanded_linear_mps == 0.0


def test_motion_state_reports_a_dead_chain_at_boot_when_both_switches_are_off() -> None:
    """The mirror image: with no live chain the gate must see it immediately."""
    world = World(_snapshot(SimulationConfig(simulated_actuation_enabled=False)))
    motion = world.observe("r1").motion
    assert motion.actuation_enabled is False
    assert motion.command_seq == 0


def test_the_world_never_refuses_a_colliding_command() -> None:
    """The world applies unsafe motion; it never conceals it (invariants 1 and 7).

    The rejection set is about *authority over the actuator*, not about safety.
    This is the invariant ADR 0006 names: a world that refuses colliding motion
    makes a clean-looking run meaningless.
    """
    from niharamesh.domain.geometry import sat_overlap

    world = World(_snapshot(SimulationConfig()))
    # Two robots, one shared map, driven into each other on purpose.
    scenario = Scenario(
        scenario_id="actuation-collide",
        name="actuation collide",
        intent=IntentDescription(goal="apply colliding motion"),
        map=_map(),
        robots=(
            RobotIdentity(robot_id="r1", footprint=_FOOTPRINT),
            RobotIdentity(robot_id="r2", footprint=_FOOTPRINT),
        ),
        starts=(
            RobotStart(robot_id="r1", pose=Pose2(x=-3.0, y=0.0, theta=0.0)),
            RobotStart(robot_id="r2", pose=Pose2(x=3.0, y=0.0, theta=math.pi)),
        ),
        policy=RunPolicy(),
        simulation=SimulationConfig(),
    )
    world.reset(ScenarioSnapshot.freeze(scenario, created_utc_ns=0))

    def drive(robot_id: str, seq: int) -> None:
        world.apply_command(
            MotionCommand(
                robot_id=robot_id,
                command_seq=seq,
                linear_mps=0.4,
                angular_radps=0.0,
                issued_at_ns=world.sim_time_ns,
                expires_at_ns=world.sim_time_ns + int(0.4 * 1e9),
                time_domain=TimeDomain.LOGICAL,
            )
        )

    overlapped = False
    for seq in range(1, 400):
        drive("r1", seq)
        drive("r2", seq)
        world.step(_DT)
        bodies = world.bodies_for_evaluation()
        if sat_overlap(bodies["r1"][0], bodies["r2"][0]):
            overlapped = True

    assert overlapped, "the world prevented a collision it should have applied"
    # The pose is whatever the actuator model produced, however unsafe.
    assert world.truth().robots["r1"].x > -3.0
    assert world.truth().robots["r2"].x < 3.0


def test_a_replayed_or_reordered_command_sequence_is_still_refused() -> None:
    """The other refusal reasons survive the split unchanged."""
    world = World(_snapshot(SimulationConfig()))
    assert world.apply_command(_command(5, linear=0.2)) is True
    assert world.apply_command(_command(5, linear=0.0)) is False
    assert world.apply_command(_command(4, linear=0.0)) is False
    assert world.apply_command(_command(6, linear=0.3)) is True


def test_an_unknown_robot_and_a_foreign_clock_domain_are_still_refused() -> None:
    """Unknown robot and wrong clock domain remain refusals, for invariant 8."""
    world = World(_snapshot(SimulationConfig()))
    unknown = MotionCommand(
        robot_id="r9",
        command_seq=1,
        linear_mps=0.2,
        angular_radps=0.0,
        issued_at_ns=0,
        expires_at_ns=1,
        time_domain=TimeDomain.LOGICAL,
    )
    foreign = MotionCommand(
        robot_id="r1",
        command_seq=1,
        linear_mps=0.2,
        angular_radps=0.0,
        issued_at_ns=0,
        expires_at_ns=1,
        time_domain=TimeDomain.MONOTONIC,
    )
    assert world.apply_command(unknown) is False
    assert world.apply_command(foreign) is False


def test_the_chain_stays_live_across_a_reset() -> None:
    """``reset`` rebuilds every robot, so the boot value must be recomputed."""
    snapshot = _snapshot(SimulationConfig())
    world = World(snapshot)
    world.apply_command(_command(1, linear=0.4))
    world.step(_DT)
    world.reset(snapshot)
    assert world.sim_time_ns == 0
    assert world.observe("r1").motion.actuation_enabled is True
    assert world.observe("r1").motion.command_seq == 0


def test_a_dead_chain_never_becomes_live_through_a_command() -> None:
    """With both switches off the chain stays dead even if a command is somehow held."""
    world = World(_snapshot(SimulationConfig(simulated_actuation_enabled=False)))
    assert world.apply_command(_command(1, linear=0.4)) is False
    assert world.observe("r1").motion.actuation_enabled is False

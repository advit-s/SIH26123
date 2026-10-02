"""Differential-drive kinematics: momentum, braking and declared limits.

The behaviour under test is the behaviour the project's stopping-distance
reasoning depends on. If a command could stop a robot instantly, the entire
``v**2 / (2a)`` argument in the safety gate would be fiction, so these tests
check the physics rather than the arithmetic alone.
"""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from niharamesh.domain.config import ActuatorModel, StoppingBudget
from niharamesh.domain.pose import ActuatorState
from niharamesh.simulator.kinematics import (
    KinematicResult,
    braking_distance_m,
    clamp_command,
    ramp_towards,
    step,
)

_DT = 1.0 / 20.0  # the configured 20 Hz physics step
_ACTUATOR = ActuatorModel(
    max_linear_mps=0.4,
    max_angular_radps=1.0,
    accel_mps2=0.5,
    decel_mps2=0.8,
    angular_accel_radps2=1.5,
    command_ttl_s=0.4,
)


def _run(
    *,
    steps: int,
    command_v: float,
    command_omega: float = 0.0,
    v: float = 0.0,
    omega: float = 0.0,
    expire_after: int | None = None,
    actuation_enabled: bool = True,
) -> list[KinematicResult]:
    """Integrate a body for *steps* ticks, optionally expiring the command."""
    history: list[KinematicResult] = []
    x = y = theta = 0.0
    for index in range(steps):
        expired = expire_after is not None and index >= expire_after
        result = step(
            x=x,
            y=y,
            theta=theta,
            v=v,
            omega=omega,
            command_v=0.0 if expired else command_v,
            command_omega=0.0 if expired else command_omega,
            dt=_DT,
            actuator=_ACTUATOR,
            command_expired=expired,
            actuation_enabled=actuation_enabled,
        )
        history.append(result)
        # Feed the *whole* state forward. Leaving v/omega at their initial values
        # would silently reset momentum every step, which makes any test that
        # integrates over time meaningless.
        x, y, theta = result.x, result.y, result.theta
        v, omega = result.v, result.omega
    return history


# --------------------------------------------------------------------------- #
# Analytic braking distance
# --------------------------------------------------------------------------- #


def test_measured_braking_distance_matches_the_analytic_v_squared_over_2a() -> None:
    """Run up to the speed limit, expire the command, measure the coast."""
    budget = StoppingBudget()
    assert budget.max_speed_mps == pytest.approx(_ACTUATOR.max_linear_mps)

    history = _run(
        steps=40,
        command_v=_ACTUATOR.max_linear_mps,
        expire_after=20,
        v=_ACTUATOR.max_linear_mps,
    )
    cruise_x = history[19].x
    final_x = history[-1].x
    measured = final_x - cruise_x
    analytic = braking_distance_m(_ACTUATOR.max_linear_mps, _ACTUATOR.decel_mps2)

    assert history[-1].v == 0.0, "the run must actually come to rest"
    assert measured == pytest.approx(analytic, rel=0.02), (
        f"measured {measured:.5f} m vs analytic v^2/(2a) = {analytic:.5f} m"
    )


def test_braking_distance_matches_the_configured_stopping_budget() -> None:
    """The brief's worked example must fall out of the same physics, not a constant."""
    budget = StoppingBudget(
        max_speed_mps=0.4, reaction_time_s=0.30, braking_decel_mps2=0.8, extra_margin_m=0.10
    )
    assert budget.braking_distance_m == pytest.approx(0.10, abs=1e-9)
    assert budget.total_distance_m == pytest.approx(0.32, abs=1e-9)
    assert braking_distance_m(budget.max_speed_mps, budget.braking_decel_mps2) == pytest.approx(
        budget.braking_distance_m
    )


def test_braking_distance_rejects_a_nonpositive_deceleration() -> None:
    with pytest.raises(ValueError, match="decel"):
        braking_distance_m(0.4, 0.0)


# --------------------------------------------------------------------------- #
# Command expiry: momentum decays, it does not vanish
# --------------------------------------------------------------------------- #


def test_command_expiry_decays_momentum_over_several_steps() -> None:
    """The watchdog brakes. It never teleports the body to zero velocity."""
    history = _run(
        steps=12,
        command_v=_ACTUATOR.max_linear_mps,
        expire_after=0,
        v=_ACTUATOR.max_linear_mps,
    )
    # The body *starts* the watchdog window at full speed, but the first step
    # already spends one deceleration step, so history[0].v is one step down.
    start_v = _ACTUATOR.max_linear_mps
    assert history[0].v == pytest.approx(start_v - _ACTUATOR.decel_mps2 * _DT, abs=1e-9)

    # At least three distinct intermediate speeds before rest: one step could not
    # have consumed 0.4 m/s at 0.8 m/s^2.
    intermediate = [r.v for r in history[:-1] if 0.0 < r.v < start_v]
    assert len(intermediate) >= 3, f"momentum vanished: speeds were {[r.v for r in history]}"
    for earlier, later in pairwise(history):
        assert later.v <= earlier.v + 1e-12, "watchdog braking must not accelerate the body"
        assert later.v >= earlier.v - _ACTUATOR.decel_mps2 * _DT - 1e-9

    assert history[-1].v == 0.0
    assert all(r.actuator is ActuatorState.WATCHDOG_BRAKING for r in history)
    # Reported per-step distance must agree with the integrated pose change, or
    # the evaluator would be quoting a number the robot did not actually travel.
    assert sum(r.distance_m for r in history) == pytest.approx(history[-1].x, abs=1e-12)


def test_watchdog_braking_distance_is_the_analytic_value() -> None:
    """Expiring at full speed must travel exactly the analytic braking distance.

    The measurement starts at the moment of expiry (x == 0), so the total travel
    is the final position -- not ``history[-1].x - history[0].x``, which would
    silently discard the first, partially-braked step.
    """
    history = _run(
        steps=40,
        command_v=_ACTUATOR.max_linear_mps,
        expire_after=0,
        v=_ACTUATOR.max_linear_mps,
    )
    travelled = history[-1].x
    assert travelled == pytest.approx(
        braking_distance_m(_ACTUATOR.max_linear_mps, _ACTUATOR.decel_mps2), rel=0.02
    ), f"measured {travelled:.5f} m vs analytic {0.4**2 / (2 * 0.8):.5f} m"


def test_angular_momentum_also_decays_and_stops() -> None:
    history = _run(
        steps=30,
        command_v=0.0,
        command_omega=_ACTUATOR.max_angular_radps,
        omega=_ACTUATOR.max_angular_radps,
        expire_after=0,
    )
    assert history[0].omega < _ACTUATOR.max_angular_radps
    assert history[-1].omega == 0.0
    assert all(r.actuator is ActuatorState.WATCHDOG_BRAKING for r in history)


def test_pivot_turn_keeps_the_position_fixed() -> None:
    """A pivot turn is allowed: omega with v == 0, centre unmoved.

    ``command_omega`` is already in rad/s. The heading also ramps at
    ``angular_accel_radps2``, so the expectation integrates the ramp rather than
    assuming the commanded rate was reached on step one -- otherwise the
    assertion is wrong by ~25 %.
    """
    steps = 20
    history = _run(steps=steps, command_v=0.0, command_omega=0.8)
    assert history[-1].omega == pytest.approx(0.8, abs=1e-6)
    assert history[-1].x == pytest.approx(0.0, abs=1e-12)
    assert history[-1].y == pytest.approx(0.0, abs=1e-12)

    # The integrator contract: heading is the integral of the recorded rate.
    integrated = sum(r.omega * _DT for r in history)
    assert history[-1].theta == pytest.approx(integrated, abs=1e-12)

    # And the ramp really is in effect: the achieved heading is materially less
    # than a no-ramp turn at the commanded rate.
    unramped = 0.8 * steps * _DT
    assert history[-1].theta < unramped
    assert history[-1].theta == pytest.approx(unramped, rel=0.30)

    # Reaching the commanded rate took the number of steps the ramp implies: the
    # final partial step lands exactly on the target rather than overshooting it.
    per_step = _ACTUATOR.angular_accel_radps2 * _DT
    reached_at = next(i for i, r in enumerate(history) if abs(r.omega - 0.8) < 1e-9)
    assert reached_at == math.ceil(0.8 / per_step) - 1
    assert all(r.omega <= 0.8 + 1e-12 for r in history), "the ramp must never overshoot the target"


# --------------------------------------------------------------------------- #
# Declared limits
# --------------------------------------------------------------------------- #


def test_velocity_never_exceeds_the_configured_maximum() -> None:
    """Even with a command far above the actuator limit, the body stays bounded."""
    history = _run(steps=60, command_v=5.0)
    assert max(abs(r.v) for r in history) <= _ACTUATOR.max_linear_mps + 1e-12
    assert history[-1].v == pytest.approx(_ACTUATOR.max_linear_mps, abs=1e-6)

    turning = _run(steps=60, command_v=0.0, command_omega=9.0)
    assert max(abs(r.omega) for r in turning) <= _ACTUATOR.max_angular_radps + 1e-12


def test_clamp_command_bounds_the_request_without_discarding_it() -> None:
    v, omega = clamp_command(3.0, -4.0, _ACTUATOR)
    assert v == pytest.approx(_ACTUATOR.max_linear_mps)
    assert omega == pytest.approx(-_ACTUATOR.max_angular_radps)


def test_acceleration_respects_the_declared_ramp() -> None:
    """Spinning up to the limit must not exceed ``accel_mps2`` on any tick."""
    history = _run(steps=40, command_v=_ACTUATOR.max_linear_mps)
    for earlier, later in pairwise(history):
        dv = later.v - earlier.v
        assert dv <= _ACTUATOR.accel_mps2 * _DT + 1e-9
    # Reaching the limit takes v/a seconds; nothing may arrive sooner.
    time_to_limit = _ACTUATOR.max_linear_mps / _ACTUATOR.accel_mps2
    first_at_limit = next(i for i, r in enumerate(history) if r.v == _ACTUATOR.max_linear_mps)
    assert (first_at_limit + 1) * _DT >= time_to_limit - _DT


def test_slowing_down_uses_the_deceleration_limit_not_the_acceleration_limit() -> None:
    """Halving the speed uses ``decel_mps2``; a decel-based stop is not symmetric."""
    history = _run(steps=40, command_v=0.2, v=0.4)
    for earlier, later in pairwise(history):
        assert earlier.v - later.v <= _ACTUATOR.decel_mps2 * _DT + 1e-9
    assert history[-1].v == pytest.approx(0.2, abs=1e-9)


def test_step_travels_at_most_the_commanded_distance() -> None:
    """Displacement per tick must be bounded by the speed limit, as a property."""
    history = _run(steps=100, command_v=_ACTUATOR.max_linear_mps)
    previous = 0.0
    for result in history:
        step_distance = abs(result.x - previous)
        assert step_distance <= _ACTUATOR.max_linear_mps * _DT + 1e-9
        previous = result.x


# --------------------------------------------------------------------------- #
# Ramp primitive and disabled actuation
# --------------------------------------------------------------------------- #


def test_ramp_reaches_the_target_exactly_and_never_overshoots() -> None:
    assert ramp_towards(0.0, 0.4, 0.5, 0.8, 10.0) == 0.4
    assert ramp_towards(0.4, 0.1, 0.5, 0.8, 10.0) == 0.1
    assert ramp_towards(0.1, 0.4, 0.5, 0.8, 0.01) == pytest.approx(0.105)
    assert ramp_towards(0.4, -0.4, 0.5, 0.8, 10.0) == -0.4
    assert ramp_towards(0.4, 0.0, 0.5, 0.8, 0.0) == 0.4


def test_disabled_actuation_coasts_to_rest_and_reports_disabled() -> None:
    history = _run(
        steps=20,
        command_v=_ACTUATOR.max_linear_mps,
        v=_ACTUATOR.max_linear_mps,
        actuation_enabled=False,
    )
    assert history[0].v < _ACTUATOR.max_linear_mps
    assert history[-1].v == 0.0
    assert all(r.actuator is ActuatorState.DISABLED for r in history)


def test_negative_dt_is_rejected() -> None:
    with pytest.raises(ValueError, match="dt"):
        step(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -_DT, _ACTUATOR)


def test_result_poses_stay_finite_over_a_long_run() -> None:
    for result in _run(steps=500, command_v=_ACTUATOR.max_linear_mps, command_omega=0.5):
        assert math.isfinite(result.x)
        assert math.isfinite(result.y)
        assert math.isfinite(result.theta)
        assert -math.pi <= result.theta <= math.pi

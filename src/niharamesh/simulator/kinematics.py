"""Differential-drive kinematics with declared acceleration and deceleration.

Why the ramp exists
-------------------
Setting ``v = command_v`` instantly would let a robot stop or start in zero
time, which quietly removes the entire stopping-distance problem the project's
safety reasoning depends on. A command that ends must therefore leave the robot
coasting at ``decel_mps2`` until the momentum is gone, and a command that starts
must take ``accel_mps2`` to reach the requested speed. Both are modelled here so
that the safety gate and the evaluator can compare *requested* motion against
*actual* motion instead of assuming they are the same thing.

Integration is explicit midpoint: velocity is ramped to its end-of-step value,
then the pose is advanced using the heading at the half step. That is stable for
the constant-twist differential-drive model at a 20 Hz step and needs no solver,
which matters because the deterministic path must stay reproducible.

The watchdog is part of the physics, not part of the command. When a command has
expired the *requested* velocities become zero; the *actual* velocities decay at
the configured deceleration. Nothing here ever sets a velocity to zero directly,
so a crashed control loop leaves a coasting robot rather than a teleporting one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.geometry import Pose
from niharamesh.domain.pose import ActuatorState
from niharamesh.domain.units import wrap_angle

__all__ = [
    "KinematicResult",
    "braking_distance_m",
    "clamp_command",
    "ramp_towards",
    "step",
]

#: Velocities below this are treated as zero. A differential drive cannot hold a
#: 1e-9 m/s creep physically, and letting a ramp asymptote forever would keep a
#: robot nominally "moving" for the rest of a run.
REST_EPSILON_MPS: Final[float] = 1e-6
REST_EPSILON_RADPS: Final[float] = 1e-6


@dataclass(frozen=True, slots=True)
class KinematicResult:
    """State after one fixed step, plus the actuator story that produced it."""

    x: float
    y: float
    theta: float
    v: float
    omega: float
    actuator: ActuatorState
    #: Signed? No: unsigned path length this step, from the trapezoidal rule on
    #: |v|. Equals the chord for straight motion and is zero for a pivot turn,
    #: whose energy is charged through the idle term of the battery model instead.
    distance_m: float
    #: True while the body is decelerating toward a zero command, watchdog or not.
    braking: bool

    @property
    def pose(self) -> Pose:
        return Pose(self.x, self.y, self.theta)

    @property
    def speed_mps(self) -> float:
        return abs(self.v)


def clamp_command(command_v: float, command_omega: float, actuator: ActuatorModel) -> tuple[float, float]:
    """Clamp a requested twist into the actuator model's declared envelope.

    Clamping is honest (the request is still recorded, just not achievable);
    silently *ignoring* an out-of-range command and letting the robot keep its
    old velocity is what we avoid, so the clamp is always to the nearest
    achievable value.
    """
    v = max(-actuator.max_linear_mps, min(actuator.max_linear_mps, command_v))
    omega = max(-actuator.max_angular_radps, min(actuator.max_angular_radps, command_omega))
    return v, omega


def ramp_towards(current: float, target: float, rate_up: float, rate_down: float, dt: float) -> float:
    """Move *current* toward *target* by at most one rate-limited step.

    A zero target always decelerates: that is the watchdog, the operator stop and
    the end of a trajectory all sharing one physical rule. Otherwise the rate
    depends on whether the magnitude is increasing or decreasing, so a robot that
    is already going 0.4 m/s and is asked for 0.2 m/s uses the deceleration
    limit rather than the acceleration limit.
    """
    if dt <= 0.0:
        return current
    if target == 0.0:
        limit = rate_down * dt
    else:
        rate = rate_up if abs(target) > abs(current) else rate_down
        limit = rate * dt
    delta = target - current
    if delta > limit:
        return current + limit
    if delta < -limit:
        return current - limit
    return target


def braking_distance_m(speed_mps: float, decel_mps2: float) -> float:
    """Analytic braking distance ``v**2 / (2 a)`` in metres.

    Exposed so the evaluator can compare a *measured* stop against the analytic
    one instead of assuming they match.
    """
    if decel_mps2 <= 0.0:
        raise ValueError("decel_mps2 must be positive")
    return (speed_mps * speed_mps) / (2.0 * decel_mps2)


def step(
    x: float,
    y: float,
    theta: float,
    v: float,
    omega: float,
    command_v: float,
    command_omega: float,
    dt: float,
    actuator: ActuatorModel,
    *,
    command_expired: bool = False,
    actuation_enabled: bool = False,
) -> KinematicResult:
    """Advance one differential-drive body by ``dt`` seconds.

    ``command_expired`` means no live command exists for this step. The request
    becomes zero and the actuator reports ``WATCHDOG_BRAKING``; the actual
    velocities decay at ``decel_mps2`` over as many steps as that takes.

    ``actuation_enabled`` gates motion on the physical-actuation switch. With it
    off the requested velocities are zero, so the body still coasts to a stop
    under the same deceleration rather than freezing, which is what a real
    disabled drive train does.
    """
    if dt < 0.0:
        raise ValueError("dt must be non-negative")

    requested_v, requested_omega = clamp_command(command_v, command_omega, actuator)
    if not actuation_enabled:
        requested_v, requested_omega = 0.0, 0.0

    if command_expired or not actuation_enabled:
        actuator_state = ActuatorState.WATCHDOG_BRAKING if command_expired else ActuatorState.DISABLED
    else:
        actuator_state = ActuatorState.ENABLED

    next_v = ramp_towards(v, requested_v, actuator.accel_mps2, actuator.decel_mps2, dt)
    next_omega = ramp_towards(
        omega, requested_omega, actuator.angular_accel_radps2, actuator.angular_accel_radps2, dt
    )
    if abs(next_v) < REST_EPSILON_MPS:
        next_v = 0.0
    if abs(next_omega) < REST_EPSILON_RADPS:
        next_omega = 0.0

    # A body that reaches rest *mid-step* must stop moving for the remainder of the
    # step. Without this the trapezoid below integrates a non-zero velocity across
    # the whole step, so a 0.25 m/s body with a 0.25 s tick would coast 0.00625 m
    # instead of 0.0015625 m -- a fourfold over-travel, and the analytic
    # v**2/(2a) budget would stop matching the measured stop. Shortening the ramp
    # to the true stop time keeps the trapezoid exact at any step size.
    travel_s = dt
    if next_v == 0.0 and v != 0.0:
        rate = actuator.decel_mps2 if abs(next_v) <= abs(v) else actuator.accel_mps2
        stop_time = abs(v) / rate
        if stop_time < dt:
            travel_s = stop_time
    else:
        travel_s = dt

    # Explicit midpoint, with a trapezoidal position increment.
    #
    # The trapezoid matters and is not cosmetic: a rectangle rule on the
    # end-of-step velocity systematically *under*-travels a braking ramp, because
    # the first step of a stop already discards half a step of momentum. Over a
    # full 0.4 m/s stop at 0.8 m/s^2 that error is ~10 %, which is larger than the
    # tolerance of any test comparing a measured stop against the analytic
    # ``v**2 / (2a)``. Integrating position with the same trapezoid used for
    # ``distance_m`` keeps the reported and travelled distances identical.
    theta_mid = wrap_angle(theta + 0.5 * next_omega * travel_s)
    travel_m = 0.5 * (v + next_v) * travel_s
    nx = x + travel_m * math.cos(theta_mid)
    ny = y + travel_m * math.sin(theta_mid)
    ntheta = wrap_angle(theta + next_omega * dt)

    braking = requested_v == 0.0 and abs(v) > abs(next_v) + 1e-12
    return KinematicResult(
        x=nx,
        y=ny,
        theta=ntheta,
        v=next_v,
        omega=next_omega,
        actuator=actuator_state,
        distance_m=0.5 * (abs(v) + abs(next_v)) * travel_s,
        braking=braking,
    )

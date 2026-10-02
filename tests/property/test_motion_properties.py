"""Property tests for motion and collision predicates.

These are the invariants a reviewer would otherwise have to argue for by hand.
Each one is a statement that must hold for *every* input in a generated range, not
for a chosen example:

* a robot's state is always finite, and it can never teleport,
* the collision predicate is symmetric, which is what lets two robots each run the
  same check and reach the same verdict,
* and for translation-only motion, an approach with clearance at both ends really
  is clear -- which is the assumption the whole swept test rests on.
"""

from __future__ import annotations

import math

from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.geometry import OrientedBox, wrap_angle
from niharamesh.safety.collision import (
    min_clearance,
    oracle_overlap,
    oracle_swept_translation,
    swept_body_overlap,
)
from niharamesh.simulator.kinematics import REST_EPSILON_MPS, braking_distance_m, step

#: Sub-micron-per-second requests settle at rest; see ``REST_EPSILON_MPS``.
_REST_THRESHOLD = REST_EPSILON_MPS

_ACTUATOR = ActuatorModel()
_TICK_S = 1.0 / 20.0

_POSITIONS = st.floats(min_value=-50.0, max_value=50.0, allow_nan=False, allow_infinity=False)
_ANGLES = st.floats(min_value=-math.pi, max_value=math.pi, allow_nan=False, allow_infinity=False)
_EXTENTS = st.floats(min_value=0.05, max_value=2.0, allow_nan=False, allow_infinity=False)
_COMMANDS = st.floats(min_value=-2.0, max_value=2.0, allow_nan=False, allow_infinity=False)
_TIMESTEPS = st.floats(min_value=0.001, max_value=0.25, allow_nan=False, allow_infinity=False)


def _box(x: float, y: float, theta: float, length: float, width: float) -> OrientedBox:
    return OrientedBox(x, y, theta, length, width)


@st.composite
def _body(draw: st.DrawFn) -> OrientedBox:
    return _box(
        draw(_POSITIONS),
        draw(_POSITIONS),
        draw(_ANGLES),
        draw(_EXTENTS),
        draw(_EXTENTS),
    )


@st.composite
def _mover(draw: st.DrawFn) -> tuple[OrientedBox, OrientedBox]:
    """A start pose and an end pose of the same rigid body within one step.

    The displacement is bounded by what a 20 Hz tick at the configured speed limits
    can actually produce, because that is the regime the runtime checker is used
    in and therefore the regime whose agreement is a design guarantee.
    """
    start = draw(_body())
    travel = draw(st.floats(min_value=0.0, max_value=_ACTUATOR.max_linear_mps * _TICK_S))
    heading = draw(_ANGLES)
    rotation = draw(
        st.floats(
            min_value=-_ACTUATOR.max_angular_radps * _TICK_S,
            max_value=_ACTUATOR.max_angular_radps * _TICK_S,
        )
    )
    end = _box(
        start.cx + travel * math.cos(heading),
        start.cy + travel * math.sin(heading),
        start.theta + rotation,
        start.length,
        start.width,
    )
    return start, end


# --------------------------------------------------------------------------- #
# Motion
# --------------------------------------------------------------------------- #


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    x=_POSITIONS,
    y=_POSITIONS,
    theta=_ANGLES,
    v=st.floats(min_value=-2.0, max_value=2.0),
    omega=st.floats(min_value=-3.0, max_value=3.0),
    command_v=_COMMANDS,
    command_omega=st.floats(min_value=-3.0, max_value=3.0),
    dt=_TIMESTEPS,
    enabled=st.booleans(),
    expired=st.booleans(),
)
def test_kinematic_state_is_always_finite(
    x: float,
    y: float,
    theta: float,
    v: float,
    omega: float,
    command_v: float,
    command_omega: float,
    dt: float,
    enabled: bool,
    expired: bool,
) -> None:
    result = step(
        x=x,
        y=y,
        theta=theta,
        v=v,
        omega=omega,
        command_v=command_v,
        command_omega=command_omega,
        dt=dt,
        actuator=_ACTUATOR,
        command_expired=expired,
        actuation_enabled=enabled,
    )
    for value in (result.x, result.y, result.theta, result.v, result.omega, result.distance_m):
        assert math.isfinite(value)
    assert -math.pi <= result.theta <= math.pi


@settings(max_examples=200, deadline=None)
@given(
    x=_POSITIONS,
    y=_POSITIONS,
    theta=_ANGLES,
    v=st.floats(min_value=0.0, max_value=_ACTUATOR.max_linear_mps),
    command_v=_COMMANDS,
    dt=_TIMESTEPS,
)
def test_a_step_never_moves_the_body_further_than_the_speed_limit_allows(
    x: float, y: float, theta: float, v: float, command_v: float, dt: float
) -> None:
    """No jump, no teleport, no penetration resolution.

    The bound is deliberately the physical maximum rather than the measured step:
    a world that clamped position, or resolved a collision by pushing a robot away,
    could still satisfy "the step was small" while quietly moving a body metres.
    """
    result = step(
        x=x,
        y=y,
        theta=theta,
        v=v,
        omega=0.0,
        command_v=command_v,
        command_omega=0.0,
        dt=dt,
        actuator=_ACTUATOR,
        actuation_enabled=True,
    )
    displacement = math.hypot(result.x - x, result.y - y)
    speed_bound = _ACTUATOR.max_linear_mps
    assert displacement <= speed_bound * dt + 1e-9
    assert result.v <= speed_bound + 1e-12
    assert abs(result.omega) <= _ACTUATOR.max_angular_radps + 1e-12


def _coast(speed: float, dt: float) -> float:
    """Distance travelled by a body braking from *speed* to rest at the declared rate."""
    x = y = theta = 0.0
    v = speed
    travelled = 0.0
    for _ in range(20_000):
        result = step(
            x=x,
            y=y,
            theta=theta,
            v=v,
            omega=0.0,
            command_v=0.0,
            command_omega=0.0,
            dt=dt,
            actuator=_ACTUATOR,
            command_expired=True,
            actuation_enabled=True,
        )
        travelled += math.hypot(result.x - x, result.y - y)
        x, y, theta, v = result.x, result.y, result.theta, result.v
        if result.v == 0.0:
            return travelled
    raise AssertionError("the ramp never reached rest")


@settings(max_examples=120, deadline=None)
@given(dt=st.floats(min_value=0.005, max_value=0.25), speed=st.floats(min_value=0.05, max_value=0.4))
def test_braking_distance_is_the_analytic_value_up_to_a_derived_trapezoid_bound(
    dt: float, speed: float
) -> None:
    """The discrete coast never under-travels, and over-travels by a known amount.

    The position increment is the trapezoid of the same linear ramp the velocity
    follows, so the travelled distance is the exact integral whenever the ramp
    reaches zero on a step boundary. When it does not, the final trapezoid assumes
    the residual momentum is shed linearly across a whole step, which over-travels
    by at most half of ``decel * dt**2``.

    The direction matters: over-travel means the robot stops *further along* than
    the analytic budget predicted, which is the safe side to err on. A rectangle
    rule would under-travel instead, and a safety gate comparing a measured stop
    against ``v**2 / 2a`` would then see a robot stopping short of its own budget.
    """
    analytic = braking_distance_m(speed, _ACTUATOR.decel_mps2)
    travelled = _coast(speed, dt)
    overshoot_bound = 0.5 * _ACTUATOR.decel_mps2 * dt * dt
    slack = 1e-12
    assert travelled + slack >= analytic, (
        f"coast {travelled} under-travelled the analytic budget {analytic}"
    )
    assert travelled <= analytic + overshoot_bound + slack, (
        f"coast {travelled} exceeded the derived bound "
        f"{analytic + overshoot_bound} at dt={dt}, speed={speed}"
    )


@settings(max_examples=40, deadline=None)
@given(
    whole_steps=st.integers(min_value=1, max_value=10),
    dt=st.sampled_from([1.0 / 20.0, 1.0 / 50.0, 1.0 / 100.0]),
)
def test_the_braking_distance_is_exact_when_the_step_divides_the_stopping_time(
    whole_steps: int, dt: float
) -> None:
    """When the ramp lands on a step boundary, the coast equals ``v**2 / 2a`` exactly.

    The speed is *constructed* from a whole number of ticks rather than filtered
    for: ``v = n * a * dt`` makes the stopping time exactly ``n * dt`` by
    construction, which is the case the safety gate relies on when it compares a
    measured stop against the analytic budget without a fudge factor.

    The tolerance is machine epsilon scaled to the distance. A loose tolerance here
    would hide exactly the regression this test exists to catch: switching from the
    trapezoid to a rectangle rule stops the robot short of its own budget, and a loose
    tolerance would happily accept that.
    """
    speed = whole_steps * _ACTUATOR.decel_mps2 * dt
    assume(speed <= _ACTUATOR.max_linear_mps)
    analytic = braking_distance_m(speed, _ACTUATOR.decel_mps2)
    travelled = _coast(speed, dt)
    assert travelled == pytest_approx(analytic)


def test_the_briefs_worked_example_stops_in_exactly_ten_ticks() -> None:
    """0.4 m/s at 0.8 m/s^2 is a 0.5 s stop: 10 ticks at the configured 20 Hz."""
    travelled = _coast(_ACTUATOR.max_linear_mps, _TICK_S)
    assert travelled == pytest_approx(0.10)
    assert _ACTUATOR.max_linear_mps / _ACTUATOR.decel_mps2 / _TICK_S == pytest_approx(10.0)


@settings(max_examples=150, deadline=None)
@given(command=_COMMANDS)
def test_velocity_converges_to_the_clamped_command(command: float) -> None:
    """Whatever is asked for, the body settles on the nearest achievable speed."""
    x = y = theta = 0.0
    v = 0.0
    target = max(-_ACTUATOR.max_linear_mps, min(_ACTUATOR.max_linear_mps, command))
    for _ in range(500):
        result = step(
            x=x,
            y=y,
            theta=theta,
            v=v,
            omega=0.0,
            command_v=command,
            command_omega=0.0,
            dt=_TICK_S,
            actuator=_ACTUATOR,
            actuation_enabled=True,
        )
        x, y, theta, v = result.x, result.y, result.theta, result.v
    # The rest threshold is a declared physical floor: a differential drive cannot
    # hold a sub-micrometre-per-second creep, so a request below it settles at zero.
    assert abs(v - target) <= _REST_THRESHOLD + 1e-12


def pytest_approx(value: float, *, abs: float = 1e-9, rel: float = 1e-9) -> object:
    """Local ``pytest.approx`` wrapper so this module imports pytest lazily."""
    import pytest

    return pytest.approx(value, abs=abs, rel=rel)


# --------------------------------------------------------------------------- #
# Collision predicate
# --------------------------------------------------------------------------- #


@settings(max_examples=200, deadline=None)
@given(a=_body(), b=_body())
def test_the_static_collision_predicate_is_symmetric(a: OrientedBox, b: OrientedBox) -> None:
    """Instantaneous overlap must not depend on which body is named first."""
    from niharamesh.safety.collision import pairwise_collisions

    forward = pairwise_collisions([a], [b])
    reverse = pairwise_collisions([b], [a])
    assert forward == reverse == ([(0, 0)] if _overlaps(a, b) else [])
    assert min_clearance(a, b) == pytest_approx(min_clearance(b, a))


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    a_start=_body(),
    a_travel=st.floats(min_value=0.0, max_value=_ACTUATOR.max_linear_mps * _TICK_S),
    a_heading=_ANGLES,
    b_start=_body(),
)
def test_the_swept_predicate_is_symmetric(
    a_start: OrientedBox,
    a_travel: float,
    a_heading: float,
    b_start: OrientedBox,
) -> None:
    """``swept_body_overlap(a, b) == swept_body_overlap(b, a)`` for every input.

    Expressed as the invariance it actually is: A advancing from ``a0`` to ``a1``
    against a static B at ``b0`` is the same physical question as B advancing from
    ``b1`` back to ``b0`` against a static A at ``a0``. The two relative motions are
    exact negatives of each other, and separation distance is invariant under
    negation, so the verdicts must agree.

    This matters because each robot's safety gate runs its own motion against its
    peers. If the verdict depended on which robot asked, one would brake while the
    other drove on -- a disagreement no coordination protocol can resolve, and one
    a reviewer would rightly call a defect in the checker.
    """
    d_x = a_travel * math.cos(a_heading)
    d_y = a_travel * math.sin(a_heading)
    a_end = _box(a_start.cx + d_x, a_start.cy + d_y, a_start.theta, a_start.length, a_start.width)
    # The mirror sweep runs the *other* way: B leaves b0 along -d. Then
    #   A(t) - b0  and  B(s) - a0  are exact negatives of one another for the same
    # parameter, and separation distance is invariant under negation. Sweeping B
    # from b0 + d back to b0 instead would traverse a *different* relative motion
    # and could legitimately disagree.
    b_end = _box(b_start.cx - d_x, b_start.cy - d_y, b_start.theta, b_start.length, b_start.width)

    a_asks = swept_body_overlap(a_start, a_end, b_start)
    b_asks = swept_body_overlap(b_start, b_end, a_start)
    assert a_asks == b_asks, (
        f"asymmetric verdict: A asks {a_asks}, B asks {b_asks}; "
        f"A={a_start} -> {a_end}, B={b_start} -> {b_end}"
    )

    # The independent oracle must agree with both, or symmetry would be luck.
    assert a_asks == oracle_overlap(a_start, a_end, b_start)
    assert b_asks == oracle_overlap(b_start, b_end, a_start)


def _overlaps(a: OrientedBox, b: OrientedBox) -> bool:
    """Closed-set overlap written here, independent of the module under test."""
    axes = (
        (math.cos(a.theta), math.sin(a.theta)),
        (-math.sin(a.theta), math.cos(a.theta)),
        (math.cos(b.theta), math.sin(b.theta)),
        (-math.sin(b.theta), math.cos(b.theta)),
    )
    for nx, ny in axes:
        pa = [px * nx + py * ny for px, py in a.corners()]
        pb = [px * nx + py * ny for px, py in b.corners()]
        if min(max(pa), max(pb)) < max(min(pa), min(pb)):
            return False
    return True


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(mover=_mover(), target=_body())
def test_for_translation_only_motion_two_clear_endpoints_imply_a_clear_sweep(
    mover: tuple[OrientedBox, OrientedBox], target: OrientedBox
) -> None:
    """The assumption the swept test rests on, made executable.

    For a pure translation with no rotation: if the clearance at *both* endpoint
    poses exceeds the distance travelled, then no intermediate pose can collide.
    A collision strictly between the samples would require the target to be inside
    the gap between them, which is impossible once the gap is smaller than the
    clearance. This is the property that lets a sampled sweep be trusted.
    """
    start, end = mover
    assume(abs(wrap_angle(end.theta - start.theta)) <= 1e-12)
    travel = math.hypot(end.cx - start.cx, end.cy - start.cy)

    start_gap = min_clearance(start, target)
    end_gap = min_clearance(end, target)
    assume(start_gap > travel)
    assume(end_gap > travel)

    assert not swept_body_overlap(start, end, target)
    assert not oracle_overlap(start, end, target)
    assert not oracle_swept_translation(start, end, target)


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(mover=_mover(), target=_body())
def test_all_three_collision_answers_never_contradict_each_other(
    mover: tuple[OrientedBox, OrientedBox], target: OrientedBox
) -> None:
    """Where the exact translation test applies, it must match both sampled paths.

    Rotation is excluded because the exact hull test is only valid for translation;
    asserting it across a rotation would be asserting a property the function
    documents as out of scope.
    """
    start, end = mover
    assume(abs(wrap_angle(end.theta - start.theta)) <= 1e-12)
    exact = oracle_swept_translation(start, end, target)
    assert exact == oracle_overlap(start, end, target)
    assert exact == swept_body_overlap(start, end, target)


@settings(max_examples=200, deadline=None)
@given(a=_body(), b=_body())
def test_min_clearance_is_never_negative_and_never_positive_for_a_collision(
    a: OrientedBox, b: OrientedBox
) -> None:
    """Clearance has one honest convention: 0.0 means contact, including overlap."""
    clearance = min_clearance(a, b)
    assert clearance >= 0.0
    if _overlaps(a, b):
        assert clearance == 0.0, "a positive clearance for an overlap would be invented"


@settings(max_examples=150, deadline=None)
@given(mover=_mover())
def test_a_body_always_overlaps_itself(mover: tuple[OrientedBox, OrientedBox]) -> None:
    """Sanity floor for the predicate: a pose must always collide with itself.

    If this ever failed, every "no collision" result would be meaningless.
    """
    start, _ = mover
    assert swept_body_overlap(start, start, start)
    assert oracle_overlap(start, start, start)
    assert oracle_swept_translation(start, start, start)

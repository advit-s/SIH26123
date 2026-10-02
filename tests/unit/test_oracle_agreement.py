"""Randomised evidence that the fast swept checker agrees with the oracle.

This file is the load-bearing safety evidence for the whole simulator. A single
continuous-collision routine cannot audit itself, so the runtime checker and the
reference oracle are written against different algorithms. If they disagree on a
case, the runtime checker is the one at fault -- the fix belongs in
``src/niharamesh/safety/collision.py`` and never in relaxing the oracle.

Two claims are separated here, because they are different claims:

**Soundness** (never miss a collision). Asserted over the full randomised sweep,
including motions far larger than any 20 Hz tick can produce and therefore
exercising the substep cap. This is the direction that matters: a missed collision
hides a real one.

**Exact agreement.** Asserted over one-tick motions, which is the regime the
runtime checker actually sees, where the substep budget is never exhausted.
Outside that regime the cap forces conservative inflation, which may report a
near miss as an overlap; asserting exact agreement there would be asserting a
property the documented design does not claim.

A final group compares each checker's *documented residual bound*, so the gap
between them is a measured quantity in the suite rather than a claim in prose.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterator

import pytest

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.geometry import OrientedBox
from niharamesh.safety.collision import (
    ORACLE_MAX_ROTATION_RAD,
    RUNTIME_MAX_ROTATION_RAD,
    oracle_overlap,
    oracle_residual_bound_m,
    swept_body_overlap,
    swept_residual_bound_m,
)

_CASE_COUNT = 300
_SEED = 20260102

#: The configured operating point. One physics tick at the declared actuator limits
#: is the largest relative motion the runtime checker ever has to resolve, so it
#: defines the regime in which exact agreement is a design guarantee.
_ACTUATOR = ActuatorModel()
_TICK_S = 1.0 / 20.0
_MAX_TICK_TRAVEL_M = _ACTUATOR.max_linear_mps * _TICK_S
_MAX_TICK_ROTATION_RAD = _ACTUATOR.max_angular_radps * _TICK_S


def _box(x: float, y: float, theta: float, length: float, width: float) -> OrientedBox:
    return OrientedBox(x, y, theta, length, width)


def _describe(start: OrientedBox, end: OrientedBox, target: OrientedBox) -> str:
    return (
        f"start=({start.cx:.6f}, {start.cy:.6f}, {start.theta:.6f}, "
        f"{start.length:.6f}x{start.width:.6f}) "
        f"end=({end.cx:.6f}, {end.cy:.6f}, {end.theta:.6f}) "
        f"target=({target.cx:.6f}, {target.cy:.6f}, {target.theta:.6f}, "
        f"{target.length:.6f}x{target.width:.6f}) "
        f"travel={math.hypot(end.cx - start.cx, end.cy - start.cy):.4f} "
        f"dtheta={end.theta - start.theta:+.4f}"
    )


def _endpoints(start: OrientedBox, travel: float, d_theta: float, heading: float) -> OrientedBox:
    return _box(
        start.cx + travel * math.cos(heading),
        start.cy + travel * math.sin(heading),
        start.theta + d_theta,
        start.length,
        start.width,
    )


def _random_body(rng: random.Random, x_range: float) -> OrientedBox:
    """One randomised body. Extents span 50 mm to 1.2 m.

    The 50 mm end is deliberate: a naive fixed-step swept checker misses thin
    bodies, and the whole purpose of the substep budget is that this one does not.
    """
    return _box(
        rng.uniform(-x_range, x_range),
        rng.uniform(-x_range, x_range),
        rng.uniform(-math.pi, math.pi),
        rng.uniform(0.05, 1.2),
        rng.uniform(0.05, 0.9),
    )


def _tick_case(rng: random.Random) -> tuple[OrientedBox, OrientedBox, OrientedBox]:
    """A realistic single 20 Hz tick: up to 20 mm of travel and 50 mrad of turn."""
    start = _random_body(rng, 2.0)
    end = _endpoints(
        start,
        rng.uniform(0.0, _MAX_TICK_TRAVEL_M),
        rng.uniform(-_MAX_TICK_ROTATION_RAD, _MAX_TICK_ROTATION_RAD),
        rng.uniform(-math.pi, math.pi),
    )
    return start, end, _random_body(rng, 2.5)


def _stress_case(rng: random.Random) -> tuple[OrientedBox, OrientedBox, OrientedBox]:
    """A motion far beyond one tick, used to probe soundness at the substep cap."""
    start = _random_body(rng, 2.0)
    end = _endpoints(
        start,
        rng.uniform(0.0, 1.5),
        rng.uniform(-0.6, 0.6),
        rng.uniform(-math.pi, math.pi),
    )
    return start, end, _random_body(rng, 2.5)


# --------------------------------------------------------------------------- #
# Soundness: the fast path must never miss a collision
# --------------------------------------------------------------------------- #


def test_fast_checker_never_misses_a_collision_in_the_stress_regime() -> None:
    """300 stress cases with up to 1.5 m of travel per step.

    These motions exhaust the 64-substep budget, so the runtime checker inflates
    and may over-report. What it must never do is under-report: a missed collision
    is the one failure mode that makes a clean-looking run unsafe.
    """
    rng = random.Random(_SEED)
    misses: list[str] = []
    collisions = 0
    for _ in range(_CASE_COUNT):
        start, end, target = _stress_case(rng)
        if oracle_overlap(start, end, target):
            collisions += 1
            if not swept_body_overlap(start, end, target):
                misses.append(_describe(start, end, target))
    assert not misses, (
        f"{len(misses)} collisions the fast checker MISSED; the fast checker is wrong, "
        f"the oracle is not:\n" + "\n".join(misses[:5])
    )
    assert collisions > 10, f"only {collisions} colliding cases; the sweep is degenerate"


# --------------------------------------------------------------------------- #
# Exact agreement in the operating regime
# --------------------------------------------------------------------------- #


def test_randomised_cases_agree() -> None:
    """The 300-case acceptance sweep, in the regime the runtime checker is used in.

    Failure output names the exact geometry so a disagreement can be reproduced on
    its own rather than by rerunning the whole suite.
    """
    rng = random.Random(_SEED)
    disagreements: list[str] = []
    collisions = 0
    clears = 0
    for _ in range(_CASE_COUNT):
        start, end, target = _tick_case(rng)
        fast = swept_body_overlap(start, end, target)
        if fast:
            collisions += 1
        else:
            clears += 1
        if fast != oracle_overlap(start, end, target):
            disagreements.append(f"fast={fast} {_describe(start, end, target)}")

    assert not disagreements, (
        f"{len(disagreements)} of {_CASE_COUNT} cases disagreed; the fast checker is "
        f"wrong, the oracle is not:\n" + "\n".join(disagreements[:5])
    )
    # Guard against a vacuous sweep: a suite that only ever found collisions would
    # pass the assertion above while testing nothing about clearance.
    assert collisions > 5, f"only {collisions} colliding cases; sweep is degenerate"
    assert clears > 5, f"only {clears} clear cases; sweep is degenerate"


def test_adversarial_high_rotation_with_high_translation() -> None:
    """Maximum per-tick rotation combined with maximum per-tick translation."""
    rng = random.Random(_SEED + 1)
    disagreements: list[str] = []
    for _ in range(120):
        start = _box(
            rng.uniform(-1.0, 1.0),
            rng.uniform(-1.0, 1.0),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.4, 1.0),
            rng.uniform(0.3, 0.8),
        )
        end = _endpoints(
            start,
            rng.uniform(-_MAX_TICK_TRAVEL_M, _MAX_TICK_TRAVEL_M),
            rng.uniform(-_MAX_TICK_ROTATION_RAD, _MAX_TICK_ROTATION_RAD),
            rng.uniform(-math.pi, math.pi),
        )
        target = _box(
            rng.uniform(-1.5, 1.5),
            rng.uniform(-1.5, 1.5),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.3, 1.0),
            rng.uniform(0.3, 0.8),
        )
        fast = swept_body_overlap(start, end, target)
        if fast != oracle_overlap(start, end, target):
            disagreements.append(_describe(start, end, target))
    assert not disagreements, "high rotation + high translation:\n" + "\n".join(disagreements)


def test_adversarial_very_thin_bodies() -> None:
    """50 mm bodies at full tick motion: the classic swept-checker blind spot."""
    rng = random.Random(_SEED + 2)
    disagreements: list[str] = []
    misses: list[str] = []
    detected = 0
    for _ in range(120):
        thin = rng.choice([0.05, 0.08, 0.12])
        start = _box(
            rng.uniform(-1.0, 1.0),
            rng.uniform(-1.0, 1.0),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.05, 0.4),
            thin,
        )
        end = _endpoints(
            start,
            rng.uniform(-_MAX_TICK_TRAVEL_M, _MAX_TICK_TRAVEL_M),
            rng.uniform(-_MAX_TICK_ROTATION_RAD, _MAX_TICK_ROTATION_RAD),
            rng.uniform(-math.pi, math.pi),
        )
        target = _box(
            rng.uniform(-1.2, 1.2),
            rng.uniform(-1.2, 1.2),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.05, 0.3),
            thin,
        )
        fast = swept_body_overlap(start, end, target)
        if fast:
            detected += 1
        if oracle_overlap(start, end, target):
            if not fast:
                misses.append(_describe(start, end, target))
        elif fast:
            disagreements.append("over-reported " + _describe(start, end, target))
    assert not misses, "thin-body collisions MISSED:\n" + "\n".join(misses)
    assert not disagreements, "thin bodies:\n" + "\n".join(disagreements)
    assert detected > 0, "no thin-body collisions were generated; the case set is degenerate"


def test_adversarial_near_tangential_approach() -> None:
    """Approaches engineered to graze: the post straddles the swept boundary.

    The body is 600 mm wide, so its side edge sits at y = 0.300. The post is 100 mm deep, so its
    near edge lands 1 mm either side of that line, alternating, and both outcomes must
    appear. A
    checker that passed by always answering one way would be testing nothing, and
    one that answered with a tolerance rather than the exact closed-set rule would
    collapse the two cases together.
    """
    disagreements: list[str] = []
    detected = 0
    for index in range(60):
        start = _box(0.0, 0.0, 0.0, 0.80, 0.60)
        end = _endpoints(start, _MAX_TICK_TRAVEL_M, 0.0, 0.0)
        target = _box(0.0, 0.350 + (0.001 if index % 2 == 0 else -0.001), 0.0, 0.10, 0.10)
        fast = swept_body_overlap(start, end, target)
        if fast:
            detected += 1
        if fast != oracle_overlap(start, end, target):
            disagreements.append(f"fast={fast} {_describe(start, end, target)}")
    assert not disagreements, "near tangential:\n" + "\n".join(disagreements)
    assert detected == 30, (
        f"expected exactly 30 grazing collisions and 30 clearances, got {detected}; "
        "the case set no longer straddles the boundary"
    )


def test_near_tangential_approach_is_decided_by_the_exact_edge_not_a_tolerance() -> None:
    """One millimetre is the whole margin; a fat epsilon would collapse these cases."""
    start = _box(0.0, 0.0, 0.0, 0.80, 0.60)
    end = _endpoints(start, _MAX_TICK_TRAVEL_M, 0.0, 0.0)

    inside = _box(0.0, 0.349, 0.0, 0.10, 0.10)
    outside = _box(0.0, 0.351, 0.0, 0.10, 0.10)
    touching = _box(0.0, 0.350, 0.0, 0.10, 0.10)

    assert swept_body_overlap(start, end, inside)
    assert oracle_overlap(start, end, inside)
    assert not swept_body_overlap(start, end, outside)
    assert not oracle_overlap(start, end, outside)
    assert swept_body_overlap(start, end, touching)
    assert oracle_overlap(start, end, touching)


def test_pivot_turn_sweep_agrees_across_the_supported_arc() -> None:
    """Pivoting in place: the case where translation substepping cannot help.

    Probes sit on a circle just outside the body's corner radius, so each one is
    grazed by a different part of the rotation. Both checkers must decide each
    identically.
    """
    for degrees in (5.0, 15.0, 45.0, 90.0):
        start = _box(0.0, 0.0, 0.0, 0.80, 0.50)
        end = _box(0.0, 0.0, math.radians(degrees), 0.80, 0.50)
        for angle_deg in range(0, 360, 15):
            probe = _box(
                0.45 * math.cos(math.radians(angle_deg)),
                0.45 * math.sin(math.radians(angle_deg)),
                0.0,
                0.08,
                0.08,
            )
            fast = swept_body_overlap(start, end, probe)
            assert fast == oracle_overlap(start, end, probe), f"{degrees} deg pivot, probe at {angle_deg} deg"


# --------------------------------------------------------------------------- #
# Truncation behaviour
# --------------------------------------------------------------------------- #


def test_substep_cap_never_turns_a_collision_into_a_clear_result() -> None:
    """Forcing the runtime cap must not make the checker less conservative.

    A long translation over a narrow target collides however few substeps are
    allowed. If the cap silently dropped the middle of the sweep this would report
    clear, which is the exact failure mode the inflation exists to prevent.
    """
    target = _box(0.0, 0.0, 0.0, 0.05, 0.05)
    start = _box(-1.5, 0.0, 0.0, 0.4, 0.4)
    end = _box(1.5, 0.0, 0.0, 0.4, 0.4)
    assert oracle_overlap(start, end, target)
    assert swept_body_overlap(start, end, target)
    assert swept_body_overlap(start, end, target, max_substeps=1)
    assert swept_body_overlap(start, end, target, max_substeps=2)


def test_cap_inflation_clears_a_corridor_far_outside_its_own_bound() -> None:
    """The inflation is bounded by the residual, so a distant target stays clear.

    This is the test that stops the conservative inflation from quietly becoming
    "everything collides". The target is placed well beyond the largest residual
    the capped checker can claim, so no budget setting may drag it in.
    """
    start = _box(-1.5, 0.0, 0.0, 0.4, 0.4)
    end = _box(1.5, 0.0, 0.0, 0.4, 0.4)
    for max_substeps in (2, 4, 8, 64):
        target = _box(0.0, 2.5, 0.0, 0.05, 0.05)
        assert not swept_body_overlap(start, end, target, max_substeps=max_substeps)
    assert not oracle_overlap(start, end, _box(0.0, 2.5, 0.0, 0.05, 0.05))


def test_max_substeps_of_one_is_endpoint_only_and_the_caller_owns_that_risk() -> None:
    """``max_substeps=1`` is accepted, and its consequence is documented, not hidden.

    With a single substep a body is only tested at its two endpoints, so a target
    strictly between them is missed. That is the caller's stated trade, and the
    test pins the behaviour so it cannot change silently.
    """
    start = _box(0.0, 0.0, 0.0, 0.4, 0.4)
    end = _box(1.0, 0.0, 0.0, 0.4, 0.4)
    target = _box(0.5, 0.0, 0.0, 0.05, 0.05)

    assert oracle_overlap(start, end, target)
    assert swept_body_overlap(start, end, target)
    # Documented weakness: a tiny budget really is endpoint-only.
    assert swept_body_overlap(start, end, target, max_substeps=1)


def test_oracle_refuses_instead_of_coarsening_itself() -> None:
    """Too much motion to sample honestly must raise, not quietly sample coarsely.

    An oracle that reduced its resolution under load would stop being an
    independent check at exactly the moment it is most needed.
    """
    start = _box(0.0, 0.0, 0.0, 0.05, 0.05)
    end = _box(3.0, 0.0, 0.0, 0.05, 0.05)
    target = _box(1.5, 0.0, 0.0, 0.05, 0.05)
    with pytest.raises(ValueError, match="oracle needs"):
        oracle_overlap(start, end, target, max_samples=100)


def test_invalid_substep_budgets_are_rejected() -> None:
    start = _box(0.0, 0.0, 0.0, 0.4, 0.4)
    with pytest.raises(ValueError, match="max_substeps"):
        swept_body_overlap(start, start, start, max_substeps=0)
    with pytest.raises(ValueError, match="at least two samples"):
        oracle_overlap(start, start, start, max_samples=1)


def test_changing_extents_during_a_step_is_rejected_by_both_checkers() -> None:
    """A rigid body cannot deform; accepting one would silently test the wrong thing."""
    start = _box(0.0, 0.0, 0.0, 0.4, 0.4)
    end = _box(1.0, 0.0, 0.0, 0.4, 0.6)
    with pytest.raises(ValueError, match="extents"):
        swept_body_overlap(start, end, start)
    with pytest.raises(ValueError, match="extents"):
        oracle_overlap(start, end, start)


# --------------------------------------------------------------------------- #
# Documented residuals
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("rotation_deg", [0.0, 1.0, 10.0, 45.0, 50.0])
@pytest.mark.parametrize("extent", [0.025, 0.10, 0.25, 0.45])
def test_documented_residual_bounds_are_ordered(rotation_deg: float, extent: float) -> None:
    """The oracle's residual must be strictly smaller than the runtime checker's.

    This is the executable form of the module docstring's claim. If a future retune
    made the fast path's blind spot as large as the oracle's, the oracle could no
    longer cross-check anything, and this test says so.
    """
    radius = math.hypot(2 * extent, 2 * extent)
    travel = _MAX_TICK_TRAVEL_M
    d_theta = math.radians(rotation_deg)
    runtime_samples = max(
        1,
        math.ceil(travel / (0.1 * extent)),
        math.ceil(abs(d_theta) / RUNTIME_MAX_ROTATION_RAD) if d_theta else 1,
    )
    fast = swept_residual_bound_m(
        travel=travel, d_theta=d_theta, n_samples=runtime_samples, radius=radius
    )
    reference = oracle_residual_bound_m(
        travel=travel, d_theta=d_theta, radius=radius, half_extent=extent
    )
    assert 0.0 < reference < fast, (
        f"oracle residual {reference} not strictly below runtime {fast} "
        f"(rotation {rotation_deg} deg, extent {extent} m)"
    )


@pytest.mark.parametrize("extent", [0.025, 0.10, 0.25, 0.45])
def test_oracle_samples_at_least_five_times_finer_than_the_runtime_checker(extent: float) -> None:
    """The documented resolution ratio, asserted rather than merely described."""
    radius = math.hypot(2 * extent, 2 * extent)
    for d_theta in (0.0, 0.01, 0.05, 0.5):
        fast = swept_residual_bound_m(
            travel=_MAX_TICK_TRAVEL_M,
            d_theta=d_theta,
            n_samples=max(1, math.ceil(_MAX_TICK_TRAVEL_M / (0.1 * extent))),
            radius=radius,
        )
        oracle = oracle_residual_bound_m(
            travel=_MAX_TICK_TRAVEL_M,
            d_theta=d_theta,
            radius=radius,
            half_extent=extent,
        )
        assert fast / oracle >= 5.0, (
            f"resolution ratio {fast / oracle:.2f} below the documented 5x "
            f"(extent {extent}, rotation {d_theta})"
        )


def test_oracle_residual_is_non_zero_so_it_can_still_falsify() -> None:
    """The oracle must retain a genuine blind spot.

    It is *allowed* to be coarser than the runtime path -- being an independent
    algorithm is worth that price. What it must not do is become equally blind: if
    both checkers shared a blind spot, agreement between them would prove nothing.
    """
    for extent in (0.025, 0.10, 0.25, 0.45):
        radius = math.hypot(2 * extent, 2 * extent)
        for d_theta in (0.0, 0.05, 0.5):
            oracle = oracle_residual_bound_m(
                travel=_MAX_TICK_TRAVEL_M,
                d_theta=d_theta,
                radius=radius,
                half_extent=extent,
            )
            assert oracle > 0.0, (
                f"oracle residual collapsed to {oracle} for extent {extent}, "
                f"rotation {d_theta}; it can no longer falsify the runtime path"
            )



def test_rotation_component_of_the_residual_is_negligible_at_the_tick_regime() -> None:
    """Rotation is what makes the fast path approximate at all; translation is exact.

    The rotation sagitta is the only genuine approximation in the runtime checker,
    and at one degree per substep it stays under 50 micrometres for warehouse geometry.
    """
    worst = 0.0
    for radius in (0.05, 0.2, 0.36, 0.5):
        for degrees in (0.0, 1.0, 10.0, 50.0):
            n_samples = max(1, math.ceil(math.radians(degrees) / RUNTIME_MAX_ROTATION_RAD))
            phi = math.radians(degrees) / n_samples
            worst = max(worst, radius * phi * phi / 8.0)
    assert worst < 5e-5, f"rotation sagitta bound reached {worst} m, not micrometre-scale"


def test_oracle_rotation_step_is_finer_than_the_runtime_one() -> None:
    """Constants are compared directly so retuning one side cannot go unnoticed."""
    assert ORACLE_MAX_ROTATION_RAD < RUNTIME_MAX_ROTATION_RAD


def test_oversized_single_step_rotation_is_rejected() -> None:
    """Interpolating across a quarter turn would cross the angle wrap.

    Both checkers refuse rather than guess, because a wrong answer here would be
    invisible: the swept volume would simply be in the wrong place.
    """
    start = _box(0.0, 0.0, 0.0, 0.8, 0.6)
    end = _box(0.0, 0.0, math.radians(200.0), 0.8, 0.6)
    target = _box(2.0, 0.0, 0.0, 0.2, 0.2)
    with pytest.raises(ValueError, match="single-step rotation"):
        swept_body_overlap(start, end, target)
    with pytest.raises(ValueError, match="single-step rotation"):
        oracle_overlap(start, end, target)


def _iter_parameter_cases() -> Iterator[tuple[OrientedBox, OrientedBox, OrientedBox]]:
    yield (
        _box(0.0, 0.0, 0.0, 0.8, 0.6),
        _box(0.02, 0.0, 0.0, 0.8, 0.6),
        _box(0.01, 0.45, 0.0, 0.05, 0.05),
    )
    yield (
        _box(1.0, 1.0, math.radians(90.0), 0.05, 0.9),
        _box(1.0, 0.98, math.radians(90.0), 0.05, 0.9),
        _box(1.0, 0.99, 0.0, 0.4, 0.4),
    )
    yield (
        _box(-0.5, -0.5, math.radians(-135.0), 1.2, 0.5),
        _box(-0.48, -0.52, math.radians(-120.0), 1.2, 0.5),
        _box(0.30, 0.30, math.radians(45.0), 0.2, 0.2),
    )


@pytest.mark.parametrize(("start", "end", "target"), list(_iter_parameter_cases()))
def test_parameterised_edge_geometry_agrees(
    start: OrientedBox, end: OrientedBox, target: OrientedBox
) -> None:
    assert swept_body_overlap(start, end, target) == oracle_overlap(start, end, target)
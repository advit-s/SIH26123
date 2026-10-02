"""Runtime swept checker vs. the independent reference oracle.

Every case here comes from a failure mode the brief names explicitly: thin
obstacles hidden between integration samples, opposing motion where both
endpoints are clear but the paths cross, corner cutting during a turn, and a
payload overhanging a chassis that is otherwise clear.

Each case asserts that the fast path and the oracle agree, and each states the
premise it depends on -- "the endpoints are clear" or "the chassis alone never
reaches the post" -- as an assertion of its own. A swept test whose premise is
only a comment is a swept test that can pass for the wrong reason.

Where the two ever disagree the fast path is the wrong one; the fix belongs in
``src/niharamesh/safety/collision.py`` and never in loosening the oracle.
"""

from __future__ import annotations

import math
import random

import pytest

from niharamesh.domain.geometry import OrientedBox
from niharamesh.domain.map import MapBoundary
from niharamesh.safety.collision import (
    min_clearance,
    oracle_overlap,
    oracle_swept_translation,
    pairwise_collisions,
    resolve_collision_report,
    swept_body_overlap,
)


def _box(x: float, y: float, theta: float, length: float, width: float) -> OrientedBox:
    return OrientedBox(x, y, theta, length, width)


# --------------------------------------------------------------------------- #
# Thin obstacle crossed between two integration samples
# --------------------------------------------------------------------------- #


def test_thin_obstacle_between_samples_is_detected_by_both_checkers() -> None:
    """A 20 mm post the body leaps over in one 20 Hz step, endpoints both clear.

    The body sweeps from x in [-0.90, -0.10] to x in [0.10, 0.90] in one tick. The
    post occupies x in [-0.01, 0.01]. No integration sample lands on it, which is
    precisely the miss the swept check exists to prevent.
    """
    post = _box(0.0, 0.0, 0.0, 0.02, 4.0)
    body_start = _box(-0.50, 0.0, 0.0, 0.80, 0.60)
    body_end = _box(0.50, 0.0, 0.0, 0.80, 0.60)

    assert not _touches(body_start, post)
    assert not _touches(body_end, post)

    assert swept_body_overlap(body_start, body_end, post)
    assert oracle_overlap(body_start, body_end, post)
    assert oracle_swept_translation(body_start, body_end, post)


def test_thin_obstacle_just_beyond_the_path_is_not_a_collision() -> None:
    """The same post, moved past the body's furthest reach: must stay clear.

    Guards the case above against being "fixed" by inflating until everything
    collides, which would make the checker useless rather than conservative.
    """
    post = _box(0.95, 0.0, 0.0, 0.02, 4.0)
    body_start = _box(-0.50, 0.0, 0.0, 0.80, 0.60)
    body_end = _box(0.50, 0.0, 0.0, 0.80, 0.60)

    assert not swept_body_overlap(body_start, body_end, post)
    assert not oracle_overlap(body_start, body_end, post)
    assert not oracle_swept_translation(body_start, body_end, post)
    assert min_clearance(body_end, post) == pytest.approx(0.04, abs=1e-9)


# --------------------------------------------------------------------------- #
# Opposing motion between ticks
# --------------------------------------------------------------------------- #


def test_opposing_motion_crossing_between_ticks_is_detected() -> None:
    """Both robots are clear at every endpoint, but their swept paths cross.

    Robot A occupies x in [-0.95, -0.65] at one tick end and [-0.65, -0.35] at the
    other; robot B occupies [0.35, 0.65] then [0.65, 0.95]. Every one of the four
    endpoint pairings is separated by at least 70 mm, which is exactly what a naive
    endpoint-only collision test computes, and it would call this safe.

    Over the same tick B's own body sweeps the corridor between them, so modelling
    B's motion as the static volume it swept makes the crossing visible.
    """
    a_start = _box(-0.80, 0.0, 0.0, 0.30, 0.50)
    a_end = _box(-0.50, 0.0, 0.0, 0.30, 0.50)
    b_start = _box(0.50, 0.0, 0.0, 0.30, 0.50)
    b_end = _box(0.80, 0.0, 0.0, 0.30, 0.50)

    for left in (a_start, a_end):
        for right in (b_start, b_end):
            assert not _touches(left, right)

    corridor = _box(0.0, 0.0, 0.0, 1.30, 0.50)
    assert swept_body_overlap(a_start, a_end, corridor)
    assert oracle_overlap(a_start, a_end, corridor)
    assert swept_body_overlap(b_start, b_end, corridor)
    assert oracle_overlap(b_start, b_end, corridor)
    assert oracle_swept_translation(a_start, a_end, corridor)


def test_opposing_motion_overlapping_at_an_endpoint_is_detected() -> None:
    """Head-on approach that ends overlapping: the simple case must still work."""
    a_start = _box(-0.60, 0.0, 0.0, 0.80, 0.60)
    a_end = _box(0.20, 0.0, 0.0, 0.80, 0.60)
    b = _box(0.80, 0.0, 0.0, 0.80, 0.60)

    assert _touches(a_end, b)
    assert swept_body_overlap(a_start, a_end, b)
    assert oracle_overlap(a_start, a_end, b)


def test_opposing_motion_that_stops_short_is_not_a_collision() -> None:
    """The complement: the same corridor with the bodies stopping well clear."""
    a_start = _box(-0.60, 0.0, 0.0, 0.60, 0.50)
    a_end = _box(-0.30, 0.0, 0.0, 0.60, 0.50)
    corridor = _box(0.60, 0.0, 0.0, 0.20, 0.50)

    assert not swept_body_overlap(a_start, a_end, corridor)
    assert not oracle_overlap(a_start, a_end, corridor)


# --------------------------------------------------------------------------- #
# Corner cutting during a turn
# --------------------------------------------------------------------------- #


def test_corner_cut_during_turn_is_detected() -> None:
    """A 90 degree pivot sweeps the corner outward onto a post that misses both poses.

    The body's corner radius is hypot(0.40, 0.25) = 0.4707 m. A post at y = 0.45
    with a 50 mm face sits inside that circle, so the rotation must find it, while
    the 0-degree and 90-degree poses both clear it. This is the case a purely
    translational swept test misses entirely.
    """
    post = _box(0.0, 0.45, 0.0, 0.05, 0.05)
    robot_start = _box(0.0, 0.0, 0.0, 0.80, 0.50)
    robot_end = _box(0.0, 0.0, math.radians(90.0), 0.80, 0.50)

    assert not _touches(robot_start, post)
    assert not _touches(robot_end, post)

    assert swept_body_overlap(robot_start, robot_end, post)
    assert oracle_overlap(robot_start, robot_end, post)


def test_turn_that_stays_clear_is_not_a_collision() -> None:
    """The same 90 degree pivot with the post moved outside the swept circle."""
    post = _box(0.0, 0.55, 0.0, 0.05, 0.05)
    robot_start = _box(0.0, 0.0, 0.0, 0.80, 0.50)
    robot_end = _box(0.0, 0.0, math.radians(90.0), 0.80, 0.50)

    assert not swept_body_overlap(robot_start, robot_end, post)
    assert not oracle_overlap(robot_start, robot_end, post)


def test_arc_sweep_of_a_pivot_turn_matches_the_oracle() -> None:
    """The same pivot, probed just inside and well outside the swept envelope."""
    robot_start = _box(0.0, 0.0, 0.0, 0.80, 0.50)
    robot_end = _box(0.0, 0.0, math.radians(90.0), 0.80, 0.50)

    for x_pos in (0.40, 0.45):
        probe = _box(x_pos, 0.0, 0.0, 0.10, 0.10)
        assert swept_body_overlap(robot_start, robot_end, probe)
        assert oracle_overlap(robot_start, robot_end, probe)

    for x_pos in (0.60, 0.80):
        probe = _box(x_pos, 0.0, 0.0, 0.10, 0.10)
        assert not swept_body_overlap(robot_start, robot_end, probe)
        assert not oracle_overlap(robot_start, robot_end, probe)


def test_turn_with_translation_sweeps_more_than_either_endpoint() -> None:
    """An arc drive, the case that combines both limits of the substep rule.

    The body arcs from (-1.0, -0.5) facing +x to (0.0, 0.0) turned 60 degrees.
    The probe at (-1.20, -0.20) misses both endpoint poses but is inside the arc,
    which is the case neither a translational nor a rotational sweep test alone
    would catch.
    """
    start = _box(-1.0, -0.5, 0.0, 0.80, 0.50)
    end = _box(0.0, 0.0, math.radians(60.0), 0.80, 0.50)

    inner = _box(-1.20, -0.20, 0.0, 0.06, 0.06)
    assert not _touches(start, inner)
    assert not _touches(end, inner)
    assert swept_body_overlap(start, end, inner)
    assert oracle_overlap(start, end, inner)

    far = _box(-1.20, 0.60, 0.0, 0.06, 0.06)
    assert not swept_body_overlap(start, end, far)
    assert not oracle_overlap(start, end, far)


# --------------------------------------------------------------------------- #
# Payload overhang
# --------------------------------------------------------------------------- #


def test_payload_overhang_collision_detected_while_chassis_is_clear() -> None:
    """Chassis reaches x = 0.40; a load overhanging to x = 0.80 hits a post at x = 0.55.

    The chassis box and the chassis-plus-payload box are both fed to the checkers,
    which is the only way a reviewer can see that the overhang is what mattered.
    """
    post = _box(0.55, 0.0, 0.0, 0.10, 1.20)
    chassis = _box(0.0, 0.0, 0.0, 0.80, 0.60)
    payload = _box(0.45, 0.0, 0.0, 0.70, 0.50)

    assert not _touches(chassis, post)
    assert not swept_body_overlap(chassis, chassis, post)
    assert not oracle_overlap(chassis, chassis, post)

    assert swept_body_overlap(payload, payload, post)
    assert oracle_overlap(payload, payload, post)


def test_payload_overhang_during_translation_is_detected() -> None:
    """The overhang reaches a post that the swept chassis alone passes beside.

    The chassis sweeps to x = 0.70; the payload box, offset 0.45 m ahead of the
    chassis centre, sweeps to x = 1.10. A post at x = 0.90 is inside the payload's
    swept volume and entirely outside the chassis's.
    """
    post = _box(0.90, 0.0, 0.0, 0.10, 1.20)
    chassis_start = _box(-0.30, 0.0, 0.0, 0.80, 0.60)
    chassis_end = _box(0.30, 0.0, 0.0, 0.80, 0.60)
    payload_start = _box(0.15, 0.0, 0.0, 0.70, 0.50)
    payload_end = _box(0.75, 0.0, 0.0, 0.70, 0.50)

    assert not swept_body_overlap(chassis_start, chassis_end, post)
    assert not oracle_overlap(chassis_start, chassis_end, post)
    assert swept_body_overlap(payload_start, payload_end, post)
    assert oracle_overlap(payload_start, payload_end, post)


def test_payload_overhang_cleared_by_moving_the_post_beyond_the_sweep() -> None:
    """The complement of the case above: no collision is invented past the overhang."""
    post = _box(1.20, 0.0, 0.0, 0.10, 1.20)
    payload_start = _box(0.15, 0.0, 0.0, 0.70, 0.50)
    payload_end = _box(0.75, 0.0, 0.0, 0.70, 0.50)

    assert not swept_body_overlap(payload_start, payload_end, post)
    assert not oracle_overlap(payload_start, payload_end, post)


def test_payload_overhang_matters_even_though_it_is_narrower_than_the_chassis() -> None:
    """The overhang is longer, not wider: a width-only inflation would miss it.

    Payload width is 0.50 against the chassis's 0.60, so an implementation that
    inflated by a radius derived from width alone would under-protect the front.
    """
    payload = _box(0.45, 0.0, 0.0, 0.70, 0.50)
    assert payload.width < 0.60
    post = _box(0.72, 0.0, 0.0, 0.06, 0.60)
    assert payload.half_length + 0.45 > post.cx
    assert swept_body_overlap(payload, payload, post)
    assert oracle_overlap(payload, payload, post)


# --------------------------------------------------------------------------- #
# Exact swept translation vs. brute-force fine sampling
# --------------------------------------------------------------------------- #


def test_oracle_swept_translation_matches_brute_force_sampling() -> None:
    """The hull-based exact test agrees with dense sampling on random translations.

    This is the third algorithm: no substep limits, no inflation, just the Minkowski
    sum with the translation segment. Disagreement would mean one of the two swept
    models is wrong, and the failure output names each offending case.
    """
    rng = random.Random(20260102)
    disagreements: list[str] = []
    for _ in range(200):
        start = _box(
            rng.uniform(-2.0, 2.0),
            rng.uniform(-2.0, 2.0),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.05, 1.5),
            rng.uniform(0.05, 1.0),
        )
        dx, dy = rng.uniform(-0.3, 0.3), rng.uniform(-0.3, 0.3)
        end = OrientedBox(start.cx + dx, start.cy + dy, start.theta, start.length, start.width)
        target = _box(
            rng.uniform(-2.5, 2.5),
            rng.uniform(-2.5, 2.5),
            rng.uniform(-math.pi, math.pi),
            rng.uniform(0.05, 1.2),
            rng.uniform(0.05, 1.0),
        )
        exact = oracle_swept_translation(start, end, target)
        sampled = oracle_overlap(start, end, target)
        fast = swept_body_overlap(start, end, target)
        if not (exact == sampled == fast):
            disagreements.append(f"exact={exact} sampled={sampled} fast={fast} start={start} end={end}")
    assert not disagreements, f"{len(disagreements)}/200 translation cases disagreed:\n" + "\n".join(
        disagreements[:5]
    )


def test_oracle_swept_translation_is_exact_for_a_zero_length_motion() -> None:
    """A null translation degenerates to the body itself, so it is a static test."""
    a = _box(0.0, 0.0, math.radians(30.0), 0.8, 0.6)
    for target in (_box(0.5, 0.0, 0.0, 0.2, 0.2), _box(2.0, 0.0, 0.0, 0.2, 0.2)):
        assert oracle_swept_translation(a, a, target) == _touches(a, target)


def test_oracle_swept_translation_rejects_rotation() -> None:
    """Asking for a translation-exact test on a rotating body is an error, not a guess."""
    start = _box(0.0, 0.0, 0.0, 0.8, 0.6)
    end = _box(0.5, 0.0, math.radians(30.0), 0.8, 0.6)
    with pytest.raises(ValueError, match="zero rotation"):
        oracle_swept_translation(start, end, _box(0.0, 1.0, 0.0, 0.2, 0.2))


# --------------------------------------------------------------------------- #
# Boundary conditions
# --------------------------------------------------------------------------- #


def test_touching_exactly_is_reported_as_overlap() -> None:
    """A clearance of exactly zero is not a safe clearance in this system.

    Both checkers and both static tests must say so. The alternative -- reporting
    zero penetration as clear -- would let a planner pack bodies to the millimetre
    on the strength of a rounding error.
    """
    a = _box(0.0, 0.0, 0.0, 1.0, 1.0)  # spans [-0.5, 0.5] on both axes
    b = _box(1.0, 0.0, 0.0, 1.0, 1.0)  # spans [ 0.5, 1.5]: faces meet at x = 0.5
    assert a.corners()[1][0] == -0.5
    assert b.corners()[2][0] == 0.5

    assert oracle_overlap(a, a, b)
    assert swept_body_overlap(a, a, b)
    assert oracle_swept_translation(a, a, b)
    assert min_clearance(a, b) == 0.0
    assert pairwise_collisions([a], [b]) == [(0, 0)]


def test_touching_after_translation_is_reported_as_overlap() -> None:
    """The touching case must survive motion too, not just a frozen pose.

    The body travels 1.0 m and arrives exactly face to face at x = 1.0. Only the
    final sample touches, so a checker that skipped its endpoints would call it
    clear.
    """
    a_start = _box(0.0, 0.0, 0.0, 1.0, 1.0)
    a_end = _box(1.0, 0.0, 0.0, 1.0, 1.0)
    b = _box(2.0, 0.0, 0.0, 1.0, 1.0)

    assert not _touches(a_start, b)
    assert _touches(a_end, b)

    assert swept_body_overlap(a_start, a_end, b)
    assert oracle_overlap(a_start, a_end, b)
    assert oracle_swept_translation(a_start, a_end, b)


def test_one_millimetre_of_clearance_is_not_a_collision() -> None:
    """Guards the touching case against being implemented as a fat tolerance.

    Also pins ``min_clearance``: a checker that reported a positive clearance for
    every disjoint pair would look precise and be wrong.
    """
    a = _box(0.0, 0.0, 0.0, 1.0, 1.0)
    b = _box(1.001, 0.0, 0.0, 1.0, 1.0)
    assert not swept_body_overlap(a, a, b)
    assert not oracle_overlap(a, a, b)
    assert not oracle_swept_translation(a, a, b)
    assert min_clearance(a, b) == pytest.approx(0.001, abs=1e-9)


def test_min_clearance_reports_a_positive_value_for_clearly_separated_bodies() -> None:
    """A disjoint pair must never be reported as zero clearance.

    Regression guard: skipping only the *separating* axes matters, because every
    non-separating axis has a negative gap that must be ignored rather than
    clamped to zero.
    """
    a = _box(0.0, 0.0, 0.0, 1.0, 1.0)
    b = _box(3.0, 0.0, 0.0, 1.0, 1.0)
    assert min_clearance(a, b) == pytest.approx(2.0, abs=1e-9)


def test_min_clearance_never_invents_clearance_for_a_collision() -> None:
    """A deep overlap reports 0.0, not the penetration depth and not a positive gap."""
    a = _box(0.0, 0.0, 0.0, 1.0, 1.0)
    b = _box(0.10, 0.0, 0.0, 1.0, 1.0)  # 0.40 m of interpenetration
    assert min_clearance(a, b) == 0.0


def test_min_clearance_is_a_lower_bound_not_the_exact_distance() -> None:
    """For a rotated pair the returned value must not exceed the true distance.

    The four box normals do not always contain the optimal separating direction,
    so the reported value is a lower bound and the sampled surface distance is the
    reference it must not exceed.
    """
    a = _box(0.0, 0.0, 0.0, 2.0, 0.5)
    b = _box(2.4, 0.4, math.radians(35.0), 2.0, 0.5)
    reported = min_clearance(a, b)
    assert reported > 0.0, "this geometry is disjoint, so clearance must be positive"
    assert reported <= _sample_surface_distance(a, b, 240) + 1e-9


# --------------------------------------------------------------------------- #
# Reporting helpers
# --------------------------------------------------------------------------- #


def test_pairwise_collisions_reports_every_overlapping_index_pair() -> None:
    a_boxes = [_box(0.0, 0.0, 0.0, 1.0, 1.0), _box(5.0, 0.0, 0.0, 1.0, 1.0)]
    b_boxes = [_box(0.2, 0.0, 0.0, 1.0, 1.0), _box(9.0, 0.0, 0.0, 1.0, 1.0)]
    assert pairwise_collisions(a_boxes, b_boxes) == [(0, 0)]
    assert pairwise_collisions(b_boxes, a_boxes) == [(0, 0)]
    assert pairwise_collisions(a_boxes, []) == []


def test_resolve_collision_report_names_both_robots_and_the_kind() -> None:
    report = resolve_collision_report(
        {
            "r2": (_box(0.0, 0.0, 0.0, 0.8, 0.6),),
            "r1": (_box(0.30, 0.0, 0.0, 0.8, 0.6),),
        },
        sim_time_ns=1_000_000_000,
    )
    assert report.collided
    assert bool(report) is True
    assert report.robot_ids == ("r1", "r2")
    assert [k.value for k in report.kinds] == ["robot_robot"]
    assert report.penetration_m > 0.0
    assert report.sim_time_ns == 1_000_000_000


def test_resolve_collision_report_separates_obstacle_and_boundary_kinds() -> None:
    """One robot overlapping both a shelf and the envelope must report both kinds."""
    boundary = MapBoundary(min_x=-1.0, min_y=-1.0, max_x=1.0, max_y=1.0)
    report = resolve_collision_report(
        {"r1": (_box(1.30, 0.0, 0.0, 0.8, 0.6),)},
        sim_time_ns=0,
        static_boxes=[_box(0.95, 0.0, 0.0, 0.2, 0.4)],
        boundary=boundary,
    )
    assert {k.value for k in report.kinds} == {"robot_obstacle", "robot_boundary"}
    assert report.robot_ids == ("r1",)


def test_boundary_penetration_is_the_deepest_corner_excursion() -> None:
    """The envelope is convex, so the corner excursion is exact, not an estimate."""
    boundary = MapBoundary(min_x=-1.0, min_y=-1.0, max_x=1.0, max_y=1.0)
    report = resolve_collision_report(
        {"r1": (_box(1.30, 0.0, 0.0, 0.8, 0.6),)},
        sim_time_ns=0,
        boundary=boundary,
    )
    # Body spans x in [0.90, 1.70]; the deepest excursion past x = 1.0 is 0.70.
    assert report.penetration_m == pytest.approx(0.70, abs=1e-9)


def test_resolve_collision_report_is_empty_for_a_clear_world() -> None:
    report = resolve_collision_report(
        {"r1": (_box(-0.5, 0.0, 0.0, 0.8, 0.6),), "r2": (_box(0.5, 0.0, 0.0, 0.8, 0.6),)},
        sim_time_ns=42,
        boundary=MapBoundary(min_x=-5.0, min_y=-5.0, max_x=5.0, max_y=5.0),
    )
    assert not report.collided
    assert bool(report) is False
    assert report.robot_ids == ()
    assert report.kinds == ()
    assert report.penetration_m == 0.0


def test_resolve_collision_report_is_stable_across_dict_orderings() -> None:
    """Two equal states must produce equal reports regardless of insertion order."""
    bodies = {
        "r1": (_box(0.0, 0.0, 0.0, 0.8, 0.6),),
        "r3": (_box(0.10, 0.0, 0.0, 0.8, 0.6),),
    }
    reordered = {key: bodies[key] for key in ("r3", "r1")}
    assert resolve_collision_report(bodies, sim_time_ns=7) == resolve_collision_report(
        reordered, sim_time_ns=7
    )


def test_resolve_collision_report_rejects_a_negative_timestamp() -> None:
    with pytest.raises(ValueError, match="sim_time_ns"):
        resolve_collision_report({}, sim_time_ns=-1)


# --------------------------------------------------------------------------- #
# Local helpers (never shared with the module under test)
# --------------------------------------------------------------------------- #


def _touches(a: OrientedBox, b: OrientedBox) -> bool:
    """Static closed-set overlap written here, independent of the module under test."""
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


def _sample_surface_distance(a: OrientedBox, b: OrientedBox, samples: int) -> float:
    """Brute-force surface-to-surface distance, for the lower-bound check.

    Samples every edge of one rectangle and measures to the other. It over-estimates
    the true minimum slightly, which is the right direction for a test that asserts
    ``reported <= true``: the reference must not be understated.
    """
    best = math.inf
    for source, target in ((a, b), (b, a)):
        corners = source.corners()
        for edge in range(4):
            p0 = corners[edge]
            p1 = corners[(edge + 1) % 4]
            for step in range(samples):
                t = step / (samples - 1)
                px = p0[0] + (p1[0] - p0[0]) * t
                py = p0[1] + (p1[1] - p0[1]) * t
                best = min(best, _point_to_rect_distance((px, py), target))
    return best


def _point_to_rect_distance(point: tuple[float, float], rect: OrientedBox) -> float:
    px, py = point
    c, s = math.cos(-rect.theta), math.sin(-rect.theta)
    dx, dy = px - rect.cx, py - rect.cy
    lx, ly = dx * c - dy * s, dx * s + dy * c
    qx = max(-rect.half_length, min(rect.half_length, lx))
    qy = max(-rect.half_width, min(rect.half_width, ly))
    return math.hypot(lx - qx, ly - qy)

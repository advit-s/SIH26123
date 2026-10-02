"""Collision checking: one fast runtime path and one independent oracle.

Why two algorithms
------------------
A single continuous-collision routine cannot audit itself. If the same code decides
both "the command was safe to apply" and "the run was collision free", one geometry
bug is invisible: the fleet looks safe because the auditor is wrong in the same
direction as the planner. The runtime checker and the oracle below are therefore
written against *different* algorithms and share only the exact discrete primitive
``domain.geometry.sat_overlap``:

* the runtime checker **samples** the rigid-body motion at substeps chosen so no
  substep translates a body more than 10% of the smaller half extent, nor rotates
  it more than 1 degree;
* the oracle **fine-samples** the same motion ~50x tighter in translation
  (``min(2 mm, 0.2% of the smaller body half extent)``) and 5x tighter in rotation
  (0.2 degrees);
* :func:`oracle_swept_translation` does neither -- for pure translation it computes
  the exact Minkowski sum with the translation segment and runs polygon-vs-box
  separating axes on it.

Neither the motion interpolation nor the projection arithmetic is shared between
the two checkers. A shared routine is exactly how one bug could make both agree
incorrectly, so the runtime path deliberately does *not* use the hull trick: it
would make the runtime checker and the oracle share a single algorithm for
translation instead of two.

The documented residual
-----------------------
Sampling-based continuous checks share one blind spot: a contact that begins and
ends entirely between two consecutive samples. :func:`swept_residual_bound_m`
states its size rather than pretending it is zero -- ``t + r * phi**2 / 8``, the
endpoint sampling error plus the sagitta of the rotation arc.
:func:`oracle_residual_bound_m` evaluates the same expression at the oracle's
constants and is 5x to 50x smaller, which is what makes the cross-check meaningful.

``tests/unit/test_oracle_agreement.py`` separates two claims that are easy to blur:
**soundness** (the fast path never reports clear for a collision the oracle finds),
asserted over motions far beyond one tick including the truncated regime; and
**exact agreement**, asserted over one-tick motions, the regime the runtime checker
actually sees and where the substep budget is never exhausted. When they disagree
the fast path is wrong; the oracle is never relaxed.

Truncation, and why it over-reports
-----------------------------------
When the substep count would exceed ``max_substeps`` the runtime checker does not
quietly sample more coarsely. It inflates both bodies by half the residual motion
bound, which keeps it conservative: it may report a near miss as an overlap. That
direction is deliberate, because inventing an overlap marks a clean run unsafe
while inventing a clearance hides a real collision.

Both checkers use the *closed-set* convention: a clearance of exactly zero is
reported as overlap, because a zero clearance is not a safe clearance in this
system. ``domain.geometry.sat_overlap`` reports only strictly positive
penetration, so the touching case is recovered explicitly here rather than silently
differing between the two.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from niharamesh.domain.geometry import (
    OrientedBox,
    Polygon,
    Vec2,
    convex_hull,
    sat_overlap,
    sat_penetration,
)
from niharamesh.domain.map import MapBoundary
from niharamesh.domain.units import wrap_angle

__all__ = [
    "MAX_RUNTIME_SUBSTEPS",
    "ORACLE_MAX_ROTATION_RAD",
    "ORACLE_MAX_SAMPLES",
    "RUNTIME_MAX_ROTATION_RAD",
    "RUNTIME_TRANSLATION_FRACTION",
    "CollisionKind",
    "CollisionReport",
    "min_clearance",
    "oracle_overlap",
    "oracle_residual_bound_m",
    "oracle_swept_translation",
    "pairwise_collisions",
    "resolve_collision_report",
    "swept_body_overlap",
    "swept_residual_bound_m",
]

#: Runtime sub-sampling limits: a tenth of the smaller body half extent of
#: translation per substep, and one degree of rotation per substep.
RUNTIME_TRANSLATION_FRACTION: Final[float] = 0.1
RUNTIME_MAX_ROTATION_RAD: Final[float] = math.radians(1.0)
#: Never spend an unbounded amount of time inside one control tick. A 20 Hz tick
#: needs at most ~50 substeps for a 50 mrad turn, so 64 leaves headroom.
MAX_RUNTIME_SUBSTEPS: Final[int] = 64
#: A single integration step may not rotate a body by a quarter turn; a larger
#: value means the caller violated the physics step, not that the geometry is
#: hard. Failing loudly beats interpolating across an angle wrap.
MAX_STEP_ROTATION_RAD: Final[float] = math.pi / 2.0

#: Oracle sampling limits.
ORACLE_STEP_M: Final[float] = 0.002
ORACLE_STEP_FRACTION: Final[float] = 0.002
ORACLE_MAX_ROTATION_RAD: Final[float] = math.radians(0.2)
#: Above this the oracle refuses rather than silently coarsening itself.
ORACLE_MAX_SAMPLES: Final[int] = 200_000


# --------------------------------------------------------------------------- #
# Runtime checker
# --------------------------------------------------------------------------- #


def swept_body_overlap(
    a_start: OrientedBox,
    a_end: OrientedBox,
    b: OrientedBox,
    *,
    max_substeps: int = MAX_RUNTIME_SUBSTEPS,
) -> bool:
    """Conservative continuous overlap test used at runtime.

    ``a_start``/``a_end`` are the moving body's poses at the two ends of one
    integration step; ``b`` is a static body (obstacle, wall, or another robot's
    body, which is static relative to this body over the step). The motion is
    modelled as constant twist. Returns ``True`` if the bodies overlap at *any*
    sampled instant, both endpoints included.
    """
    if max_substeps < 1:
        raise ValueError("max_substeps must be at least 1")
    if a_start.length != a_end.length or a_start.width != a_end.width:
        raise ValueError("a rigid body cannot change its extents during a step")

    d_theta = wrap_angle(a_end.theta - a_start.theta)
    if abs(d_theta) > MAX_STEP_ROTATION_RAD:
        raise ValueError(
            f"single-step rotation of {d_theta:.3f} rad exceeds the supported "
            f"{MAX_STEP_ROTATION_RAD:.3f} rad; reduce the physics step size"
        )

    extent = min(a_start.half_length, a_start.half_width, b.half_length, b.half_width)
    travel = math.hypot(a_end.cx - a_start.cx, a_end.cy - a_start.cy)

    n_steps = 1
    if travel > 0.0:
        n_steps = max(n_steps, math.ceil(travel / (RUNTIME_TRANSLATION_FRACTION * extent)))
    if d_theta != 0.0:
        n_steps = max(n_steps, math.ceil(abs(d_theta) / RUNTIME_MAX_ROTATION_RAD))

    if n_steps > max_substeps:
        n_steps = max_substeps
        residual = swept_residual_bound_m(
            travel=travel,
            d_theta=d_theta,
            n_samples=n_steps,
            radius=max(a_start.radius, b.radius),
        )
        # Half the residual on each body: the un-sampled gap belongs to the moving
        # body's path alone, so closing it by the full residual on both would
        # manufacture a penetration twice as deep as the actual uncertainty.
        half = residual / 2.0
        a_start = a_start.inflated(half)
        a_end = a_end.inflated(half)
        b = b.inflated(half)

    for i in range(n_steps + 1):
        s = i / n_steps
        probe = OrientedBox(
            a_start.cx + (a_end.cx - a_start.cx) * s,
            a_start.cy + (a_end.cy - a_start.cy) * s,
            a_start.theta + d_theta * s,
            a_start.length,
            a_start.width,
        )
        if sat_overlap(probe, b) or _runtime_touching(probe, b):
            return True
    return False


def swept_residual_bound_m(
    *, travel: float, d_theta: float, n_samples: int, radius: float
) -> float:
    """Worst-case unsampled excursion of the runtime checker, in metres.

    With the untruncated substep count the translation term is capped by
    ``RUNTIME_TRANSLATION_FRACTION`` of the smaller body half extent, which is why
    no body can fit inside an unsampled gap.
    """
    if n_samples < 1:
        raise ValueError("n_samples must be at least 1")
    t = travel / n_samples
    phi = abs(d_theta) / n_samples
    return t + radius * phi * phi / 8.0


def _runtime_touching(a: OrientedBox, b: OrientedBox) -> bool:
    """Closed-set separating-axis overlap for the runtime checker.

    ``sat_overlap`` accepts only strictly positive penetration, so it cannot
    express "exactly touching", which this system treats as a collision. The axis
    set is written out here rather than shared with the oracle: a shared projection
    routine is precisely the kind of common bug the two algorithms exist to
    cross-check.
    """
    axes: tuple[Vec2, ...] = (
        (math.cos(a.theta), math.sin(a.theta)),
        (-math.sin(a.theta), math.cos(a.theta)),
        (math.cos(b.theta), math.sin(b.theta)),
        (-math.sin(b.theta), math.cos(b.theta)),
    )
    corners_a = a.corners()
    corners_b = b.corners()
    for nx, ny in axes:
        proj_a = [px * nx + py * ny for px, py in corners_a]
        proj_b = [px * nx + py * ny for px, py in corners_b]
        if min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b)) < 0.0:
            return False
    return True


def min_clearance(a: OrientedBox, b: OrientedBox) -> float:
    """Approximate distance between two oriented rectangles, in metres.

    Overlapping or touching bodies report ``0.0``: a positive clearance for an
    actual collision would be an invented measurement (AGENTS.md rule 2).

    For separated bodies this is a **lower bound**: the smallest gap over the box
    normals that actually separate. A non-separating axis has a negative gap and
    says nothing about distance, so it is skipped rather than clamped -- treating it
    as zero would report "no clearance" for nearly every disjoint pair.
    """
    if sat_penetration(a, b) > 0.0:
        return 0.0
    separating: list[float] = []
    for nx, ny in (
        (math.cos(a.theta), math.sin(a.theta)),
        (-math.sin(a.theta), math.cos(a.theta)),
        (math.cos(b.theta), math.sin(b.theta)),
        (-math.sin(b.theta), math.cos(b.theta)),
    ):
        proj_a = [px * nx + py * ny for px, py in a.corners()]
        proj_b = [px * nx + py * ny for px, py in b.corners()]
        gap = max(min(proj_a), min(pb := proj_b)) - min(max(proj_a), max(pb))
        if gap >= 0.0:
            separating.append(gap)
    if not separating:
        # Every axis overlaps: the bodies intersect, so there is no clearance.
        return 0.0
    return min(separating)


def pairwise_collisions(
    boxes_a: Sequence[OrientedBox],
    boxes_b: Sequence[OrientedBox],
) -> list[tuple[int, int]]:
    """Index pairs whose rectangles overlap (touching counts).

    Exact closed-set test, reported in ascending index order so a sweep over the
    same two fleets produces a byte-identical list on every run.
    """
    hits: list[tuple[int, int]] = []
    for i, first in enumerate(boxes_a):
        for j, second in enumerate(boxes_b):
            if sat_overlap(first, second) or _runtime_touching(first, second):
                hits.append((i, j))
    return hits


# --------------------------------------------------------------------------- #
# Reference oracle
# --------------------------------------------------------------------------- #


def oracle_overlap(
    a_start: OrientedBox,
    a_end: OrientedBox,
    b: OrientedBox,
    *,
    max_samples: int = ORACLE_MAX_SAMPLES,
) -> bool:
    """Fine-sampled reference answer for one moving body against one static body.

    Raises rather than coarsening itself when ``max_samples`` would be exceeded:
    quietly reducing its resolution under load would stop it being an independent
    check at exactly the moment it is most needed.
    """
    if max_samples < 2:
        raise ValueError("the oracle needs at least two samples")
    if a_start.length != a_end.length or a_start.width != a_end.width:
        raise ValueError("a rigid body cannot change its extents during a step")

    extent = min(a_start.half_length, a_start.half_width, b.half_length, b.half_width)
    step_m = min(ORACLE_STEP_M, ORACLE_STEP_FRACTION * extent)
    d_theta = wrap_angle(a_end.theta - a_start.theta)
    if abs(d_theta) > MAX_STEP_ROTATION_RAD:
        raise ValueError(
            f"single-step rotation of {d_theta:.3f} rad exceeds the supported "
            f"{MAX_STEP_ROTATION_RAD:.3f} rad; reduce the physics step size"
        )

    travel = math.hypot(a_end.cx - a_start.cx, a_end.cy - a_start.cy)
    n_steps = 1
    if travel > 0.0:
        n_steps = max(n_steps, math.ceil(travel / step_m))
    if d_theta != 0.0:
        n_steps = max(n_steps, math.ceil(abs(d_theta) / ORACLE_MAX_ROTATION_RAD))
    if n_steps + 1 > max_samples:
        raise ValueError(
            f"oracle needs {n_steps + 1} samples but the limit is {max_samples}; "
            "reduce the motion, enlarge the bodies, or raise the limit explicitly"
        )

    for i in range(n_steps + 1):
        s = i / n_steps
        probe = OrientedBox(
            a_start.cx + (a_end.cx - a_start.cx) * s,
            a_start.cy + (a_end.cy - a_start.cy) * s,
            a_start.theta + d_theta * s,
            a_start.length,
            a_start.width,
        )
        if _oracle_boxes_overlap(probe, b):
            return True
    return False


def oracle_residual_bound_m(
    *, travel: float, d_theta: float, radius: float, half_extent: float
) -> float:
    """The oracle's own unsampled excursion bound, for comparison with the fast path.

    Written from the oracle's constants and not derived from
    :func:`swept_residual_bound_m`, so the two numbers can be compared honestly.
    """
    step_m = min(ORACLE_STEP_M, ORACLE_STEP_FRACTION * half_extent)
    n_steps = max(
        1,
        math.ceil(travel / step_m) if travel > 0.0 else 1,
        math.ceil(abs(d_theta) / ORACLE_MAX_ROTATION_RAD) if d_theta != 0.0 else 1,
    )
    phi = abs(d_theta) / n_steps
    return (travel / n_steps) + radius * phi * phi / 8.0


def oracle_swept_translation(a_start: OrientedBox, a_end: OrientedBox, b: OrientedBox) -> bool:
    """Exact swept test for pure translation -- no sampling at all.

    A different computation from :func:`oracle_overlap` (a hull, not a sample set)
    and from :func:`swept_body_overlap` (exact, not sampled), which is what makes it
    useful as a third opinion on translation-only cases.
    """
    if abs(wrap_angle(a_end.theta - a_start.theta)) > 1e-12:
        raise ValueError("oracle_swept_translation requires zero rotation")
    if a_start.length != a_end.length or a_start.width != a_end.width:
        raise ValueError("oracle_swept_translation requires identical extents")

    hull = convex_hull((*a_start.corners(), *a_end.corners()))
    return _oracle_polygon_overlap_box(Polygon(hull), b)


def _oracle_boxes_overlap(a: OrientedBox, b: OrientedBox) -> bool:
    """Closed-set box/box overlap for the oracle, implemented independently.

    Projections are accumulated with an explicit min/max scan over both corner sets
    rather than the closed form used by the runtime path. Redundant on purpose:
    agreement between the two must come from the geometry, not a shared expression.
    """
    cos_a, sin_a = math.cos(a.theta), math.sin(a.theta)
    cos_b, sin_b = math.cos(b.theta), math.sin(b.theta)
    corners_a = a.corners()
    corners_b = b.corners()
    for nx, ny in ((cos_a, sin_a), (-sin_a, cos_a), (cos_b, sin_b), (-sin_b, cos_b)):
        proj_a = [px * nx + py * ny for px, py in corners_a]
        proj_b = [px * nx + py * ny for px, py in corners_b]
        if min(max(proj_a), max(proj_b)) < max(min(proj_a), min(proj_b)):
            return False
    return True


def _oracle_polygon_overlap_box(poly: Polygon, b: OrientedBox) -> bool:
    """Separating-axis overlap of a convex polygon against an oriented box.

    Axis set: both of the box's normals plus one normal per hull edge. For two
    convex bodies the separating axis, if any, is normal to an edge of one of them,
    so this set is complete and the result is exact.
    """
    pts = poly.points
    cos_b, sin_b = math.cos(b.theta), math.sin(b.theta)
    axes: list[tuple[float, float]] = [(cos_b, sin_b), (-sin_b, cos_b)]
    count = len(pts)
    for i in range(count):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % count]
        norm = math.hypot(x1 - x0, y1 - y0)
        if norm > 0.0:
            axes.append(((y1 - y0) / norm, -(x1 - x0) / norm))

    box_corners = b.corners()
    for nx, ny in axes:
        proj_poly = [px * nx + py * ny for px, py in pts]
        proj_box = [px * nx + py * ny for px, py in box_corners]
        if min(max(proj_poly), max(proj_box)) < max(min(proj_poly), min(proj_box)):
            return False
    return True


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


class CollisionKind(StrEnum):
    """What kind of body pair collided. Never a bare string in a report."""

    ROBOT_ROBOT = "robot_robot"
    ROBOT_OBSTACLE = "robot_obstacle"
    ROBOT_BOUNDARY = "robot_boundary"


@dataclass(frozen=True, slots=True)
class CollisionReport:
    """Outcome of resolving one instant of the world against every other body.

    An empty ``robot_ids``/``kinds`` pair means no overlap was found *at this
    instant*, which is never a safety claim about the run.
    """

    robot_ids: tuple[str, ...]
    sim_time_ns: int
    penetration_m: float
    kinds: tuple[CollisionKind, ...]

    @property
    def collided(self) -> bool:
        return bool(self.kinds)

    def __bool__(self) -> bool:
        return self.collided


def resolve_collision_report(
    bodies: Mapping[str, Sequence[OrientedBox]],
    *,
    sim_time_ns: int,
    static_boxes: Sequence[OrientedBox] = (),
    boundary: MapBoundary | None = None,
) -> CollisionReport:
    """Find every overlap at one instant and summarise it.

    Robot ids are visited in sorted order so the report for the same world state is
    identical on every run, which is what lets an evaluator diff two runs. This is
    instantaneous overlap of settled poses; the swept check covers motion between
    integration samples.
    """
    if sim_time_ns < 0:
        raise ValueError("sim_time_ns must be non-negative")

    ids = sorted(bodies)
    involved: set[str] = set()
    kinds: set[CollisionKind] = set()
    deepest = 0.0

    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            left, right = ids[i], ids[j]
            for box_a in bodies[left]:
                for box_b in bodies[right]:
                    depth = sat_penetration(box_a, box_b)
                    if depth > 0.0:
                        involved.update((left, right))
                        kinds.add(CollisionKind.ROBOT_ROBOT)
                        deepest = max(deepest, depth)

    for robot_id in ids:
        for box in bodies[robot_id]:
            for other in static_boxes:
                depth = sat_penetration(box, other)
                if depth > 0.0:
                    involved.add(robot_id)
                    kinds.add(CollisionKind.ROBOT_OBSTACLE)
                    deepest = max(deepest, depth)
            if boundary is not None:
                depth = _boundary_penetration_m(box, boundary)
                if depth > 0.0:
                    involved.add(robot_id)
                    kinds.add(CollisionKind.ROBOT_BOUNDARY)
                    deepest = max(deepest, depth)

    return CollisionReport(
        robot_ids=tuple(sorted(involved)),
        sim_time_ns=sim_time_ns,
        penetration_m=deepest,
        kinds=tuple(sorted(kinds, key=lambda k: k.value)),
    )


def _boundary_penetration_m(box: OrientedBox, boundary: MapBoundary) -> float:
    """How far *box* reaches outside the usable envelope.

    The envelope is convex, so if all four corners are inside then the whole
    rectangle is inside; the deepest corner excursion is therefore exact rather than
    an estimate.
    """
    worst = 0.0
    for px, py in box.corners():
        over = max(
            boundary.min_x - px,
            px - boundary.max_x,
            boundary.min_y - py,
            py - boundary.max_y,
            0.0,
        )
        worst = max(worst, over)
    return worst
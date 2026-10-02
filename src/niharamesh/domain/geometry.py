"""Explicit 2D geometry primitives.

The whole system is planar. Every type here is a frozen, hashable value so it
can be used inside set-based occupancy tests and scenario hashes.

Conventions
-----------
* Coordinates are metres in a right-handed frame (``x`` forward/east,
  ``y`` left/north) with headings in radians measured CCW from ``+x``.
* An :class:`OrientedBox` is described by its centre, heading, length (along
  the local ``+x`` axis) and width (along the local ``+y`` axis).
* All predicates are conservative: a body is *inflated* by adding to its half
  extents, never by shrinking the obstacle.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from niharamesh.domain.units import require_finite, wrap_angle

__all__ = [
    "OrientedBox",
    "Polygon",
    "Pose",
    "Vec2",
    "aabb_contains_point",
    "aabb_overlap",
    "bbox_of",
    "box_corners",
    "circle_rect_overlap",
    "point_in_polygon",
    "rotate",
    "sat_overlap",
    "sat_penetration",
    "segment_intersects_segment",
    "segment_point_distance",
]

Vec2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Pose:
    """A planar pose. Lightweight, frozen, hashable, no pydantic dependency."""

    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0

    def __post_init__(self) -> None:
        require_finite(self.x, field="pose.x")
        require_finite(self.y, field="pose.y")
        object.__setattr__(
            self, "theta", wrap_angle(require_finite(self.theta, field="pose.theta"))
        )

    def translated(self, dx: float, dy: float) -> Pose:
        return Pose(self.x + dx, self.y + dy, self.theta)

    def distance_to(self, other: Pose | Vec2) -> float:
        ox, oy = (other.x, other.y) if isinstance(other, Pose) else other
        return math.hypot(self.x - ox, self.y - oy)

    def forward(self) -> Vec2:
        return math.cos(self.theta), math.sin(self.theta)

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.theta)


@dataclass(frozen=True, slots=True)
class OrientedBox:
    """A rectangle with a pose: robot bodies, shelves, payloads, obstacles."""

    cx: float
    cy: float
    theta: float
    length: float
    width: float

    def __post_init__(self) -> None:
        require_finite(self.cx, field="obb.cx")
        require_finite(self.cy, field="obb.cy")
        object.__setattr__(self, "theta", wrap_angle(require_finite(self.theta, field="obb.theta")))
        require_finite(self.length, field="obb.length")
        require_finite(self.width, field="obb.width")
        if self.length <= 0.0 or self.width <= 0.0:
            raise ValueError(
                f"OrientedBox extents must be positive, got {self.length}x{self.width}"
            )

    @property
    def half_length(self) -> float:
        return self.length / 2.0

    @property
    def half_width(self) -> float:
        return self.width / 2.0

    @property
    def radius(self) -> float:
        """Circumscribed radius - used only for coarse broad-phase rejection."""
        return math.hypot(self.half_length, self.half_width)

    def at(self, pose: Pose) -> OrientedBox:
        return OrientedBox(pose.x, pose.y, pose.theta, self.length, self.width)

    def inflated(self, margin: float) -> OrientedBox:
        if margin < 0.0:
            raise ValueError("inflation margin must be non-negative")
        return OrientedBox(
            self.cx, self.cy, self.theta, self.length + 2 * margin, self.width + 2 * margin
        )

    def corners(self) -> tuple[Vec2, Vec2, Vec2, Vec2]:
        """Corner points counter-clockwise starting at ``(+half_length, +half_width)``."""
        return box_corners(self.cx, self.cy, self.theta, self.length, self.width)

    def contains_point(self, px: float, py: float) -> bool:
        c, s = math.cos(-self.theta), math.sin(-self.theta)
        dx, dy = px - self.cx, py - self.cy
        lx, ly = dx * c - dy * s, dx * s + dy * c
        return abs(lx) <= self.half_length and abs(ly) <= self.half_width


@dataclass(frozen=True, slots=True)
class Polygon:
    """A closed simple polygon given in counter-clockwise order."""

    points: tuple[Vec2, ...]

    def __post_init__(self) -> None:
        if len(self.points) < 3:
            raise ValueError("Polygon requires at least three vertices")
        for x, y in self.points:
            require_finite(x, field="polygon.x")
            require_finite(y, field="polygon.y")
        object.__setattr__(self, "points", tuple((float(a), float(b)) for a, b in self.points))

    def contains_point(self, px: float, py: float) -> bool:
        return point_in_polygon(px, py, self.points)

    def bounds(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs), max(ys)

    def as_tuple(self) -> tuple[Vec2, ...]:
        return self.points


def rotate(vx: float, vy: float, theta: float) -> Vec2:
    c, s = math.cos(theta), math.sin(theta)
    return vx * c - vy * s, vx * s + vy * c


def box_corners(
    cx: float, cy: float, theta: float, length: float, width: float
) -> tuple[Vec2, Vec2, Vec2, Vec2]:
    hl, hw = length / 2.0, width / 2.0
    c, s = math.cos(theta), math.sin(theta)
    out: list[Vec2] = []
    for lx, ly in ((hl, hw), (-hl, hw), (-hl, -hw), (hl, -hw)):
        out.append((cx + lx * c - ly * s, cy + lx * s + ly * c))
    return (out[0], out[1], out[2], out[3])


def bbox_of(box: OrientedBox) -> tuple[float, float, float, float]:
    """Axis-aligned bounds of an oriented box: ``(min_x, min_y, max_x, max_y)``."""
    hx, hy = box.half_length, box.half_width
    ex = abs(hx * math.cos(box.theta)) + abs(hy * math.sin(box.theta))
    ey = abs(hx * math.sin(box.theta)) + abs(hy * math.cos(box.theta))
    return (box.cx - ex, box.cy - ey, box.cx + ex, box.cy + ey)


def aabb_overlap(
    a: tuple[float, float, float, float], b: tuple[float, float, float, float]
) -> bool:
    """Touching counts as overlap - we are testing safety, not nice graphics."""
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def aabb_contains_point(b: tuple[float, float, float, float], px: float, py: float) -> bool:
    return b[0] <= px <= b[2] and b[1] <= py <= b[3]


def sat_penetration(a: OrientedBox, b: OrientedBox) -> float:
    """Minimum translation distance along the best separating axis.

    Returns ``0.0`` when the boxes are disjoint. For disjoint boxes the exact
    swept test is ``convex_hull_swept(a0, a1, b)`` - see
    :mod:`niharamesh.safety.collision`.
    """
    ba, bb = bbox_of(a), bbox_of(b)
    if not aabb_overlap(ba, bb):
        return 0.0
    axes: tuple[Vec2, ...] = (
        (math.cos(a.theta), math.sin(a.theta)),
        (-math.sin(a.theta), math.cos(a.theta)),
        (math.cos(b.theta), math.sin(b.theta)),
        (-math.sin(b.theta), math.cos(b.theta)),
    )
    ca, cb = a.corners(), b.corners()
    best = math.inf
    for nx, ny in axes:
        proj_a = [px * nx + py * ny for px, py in ca]
        proj_b = [px * nx + py * ny for px, py in cb]
        overlap = min(max(proj_a), max(proj_b)) - max(min(proj_a), min(proj_b))
        if overlap <= 0.0:
            return 0.0
        best = min(best, overlap)
    return best


def sat_overlap(a: OrientedBox, b: OrientedBox) -> bool:
    """Exact overlap test for two oriented rectangles via the separating axis theorem.

    Touching (zero penetration) is reported as *overlap* because a clearance of
    exactly zero between two bodies is not a safe clearance in this system.
    """
    return sat_penetration(a, b) > 0.0


def point_in_polygon(px: float, py: float, points: Iterable[Vec2]) -> bool:
    """Ray-crossing point-in-polygon. Boundary behaviour is unspecified; inflate."""
    pts = tuple(points)
    inside = False
    n = len(pts)
    j = n - 1
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > py) != (yj > py):
            x_cross = (xj - xi) * (py - yi) / (yj - yi) + xi
            if px < x_cross:
                inside = not inside
        j = i
    return inside


def segment_point_distance(
    ax: float, ay: float, bx: float, by: float, px: float, py: float
) -> float:
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-18 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


def segment_intersects_segment(a0: Vec2, a1: Vec2, b0: Vec2, b1: Vec2) -> bool:
    """Proper or improper intersection test for two closed segments."""

    def orient(p: Vec2, q: Vec2, r: Vec2) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = orient(a0, a1, b0)
    d2 = orient(a0, a1, b1)
    d3 = orient(b0, b1, a0)
    d4 = orient(b0, b1, a1)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True

    def on_segment(p: Vec2, q: Vec2, r: Vec2) -> bool:
        return (
            min(p[0], r[0]) - 1e-12 <= q[0] <= max(p[0], r[0]) + 1e-12
            and min(p[1], r[1]) - 1e-12 <= q[1] <= max(p[1], r[1]) + 1e-12
        )

    return (
        (abs(d1) < 1e-12 and on_segment(a0, b0, a1))
        or (abs(d2) < 1e-12 and on_segment(a0, b1, a1))
        or (abs(d3) < 1e-12 and on_segment(b0, a0, b1))
        or (abs(d4) < 1e-12 and on_segment(b0, a1, b1))
    )


def circle_rect_overlap(cx: float, cy: float, radius: float, rect: OrientedBox) -> bool:
    """Overlap of a disc and an oriented box (used for sensor range checks)."""
    local = rotate(cx - rect.cx, cy - rect.cy, -rect.theta)
    qx = max(-rect.half_length, min(rect.half_length, local[0]))
    qy = max(-rect.half_width, min(rect.half_width, local[1]))
    return math.hypot(local[0] - qx, local[1] - qy) <= radius


def convex_hull(points: Sequence[Vec2]) -> tuple[Vec2, ...]:
    """Monotone-chain convex hull, counter-clockwise."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return tuple(pts)

    def cross(o: Vec2, a: Vec2, b: Vec2) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Vec2] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Vec2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return tuple(lower[:-1] + upper[:-1])

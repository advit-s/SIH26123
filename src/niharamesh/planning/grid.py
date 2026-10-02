"""Uniform occupancy grid built from the immutable shared map *alone*.

Authority boundary (AGENTS.md rules 1 and 3): this grid is derived only from
:class:`~niharamesh.domain.map.WarehouseMap` plus an explicit list of extra
blocked circles supplied by the caller. It never reads the simulator's occupancy
tracker, another robot's pose or any evaluator state. If dynamic occupancy is
needed, the caller must hand over the blocked circles *it was told about* (a
peer obstruction report, its own sensor rays) - which is exactly why
:attr:`OccupancyGrid.cells_inflated_count` and the ``static_blocked`` mask are
exposed separately: a robot can distinguish "the map says so" from "a peer said
so, and here is how old that claim is".

Inflation semantics
-------------------
A cell is *blocked* when any of the following holds:

1. its centre lies within ``inflation_m`` of any obstacle (oriented box),
# A cell is *blocked* when any of the following holds:

1. its centre lies within ``inflation_m`` of any obstacle (oriented box),
2. its centre lies outside the map boundary shrunk by ``inflation_m`` (the
   boundary is a wall, and an inflated body may not place its reference point
   inside it - shrinking, never growing, so a plan can never leave the map), or
3. ``zones_blocking=True`` and its centre lies inside a zone's already-inflated
   ``protected_bounds``.

The grid rectangle is exactly the map boundary: there are no cells outside it.

``static_blocked`` is the same test with ``inflation_m = 0``. Comparing the two
masks is what lets :mod:`niharamesh.planning.astar` distinguish
``blocked_goal`` (a shelf is in the way) from ``insufficient_clearance`` (the
shelf is fine, this robot is too fat).

Complexity: obstacles are stamped over their own inflated bounding box only, so
building is ``O(sum over obstacles of cells_in_bbox)`` rather than
``O(cells x obstacles)``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import Footprint

__all__ = ["Circle", "GridTooLargeError", "OccupancyGrid", "Vec2"]

Vec2 = tuple[float, float]
#: ``(cx, cy, radius_m)`` - a blocked disc, normally a *claim* rather than truth.
Circle = tuple[float, float, float]

#: Hard refusal threshold. A 500 m map at the minimum legal 0.02 m resolution
#: would need 625 million cells; we refuse instead of exhausting memory, and say
#: so rather than silently degrading the resolution.
MAX_CELLS: Final[int] = 4_000_000


class GridTooLargeError(ValueError):
    """Raised when the requested resolution would need an unreasonable grid."""


def _obstacle_half_extents(length_m: float, width_m: float, theta: float) -> tuple[float, float]:
    c, s = abs(math.cos(theta)), abs(math.sin(theta))
    hl, hw = length_m / 2.0, width_m / 2.0
    return hl * c + hw * s, hl * s + hw * c


def _point_box_distance(
    px: float, py: float, cx: float, cy: float, theta: float, length_m: float, width_m: float
) -> float:
    """Distance from a point to an oriented box (0 when inside)."""
    cos_t, sin_t = math.cos(-theta), math.sin(-theta)
    dx, dy = px - cx, py - cy
    lx = dx * cos_t - dy * sin_t
    ly = dx * sin_t + dy * cos_t
    ex = max(0.0, abs(lx) - length_m / 2.0)
    ey = max(0.0, abs(ly) - width_m / 2.0)
    return math.hypot(ex, ey)


class OccupancyGrid:
    """Immutable uniform grid. Built once, queried many times, never mutated."""

    __slots__ = (
        "_blocked",
        "_inflation_m",
        "_map_id",
        "_nx",
        "_ny",
        "_obstacle_count",
        "_origin_x",
        "_origin_y",
        "_res",
        "_static",
        "_zones_blocking",
    )

    def __init__(
        self,
        *,
        origin_x: float,
        origin_y: float,
        resolution: float,
        nx: int,
        ny: int,
        blocked: bytearray,
        static_blocked: bytearray,
        inflation_m: float,
        zones_blocking: bool,
        map_id: str,
        obstacle_count: int,
    ) -> None:
        if nx <= 0 or ny <= 0:
            raise ValueError("grid must have at least one cell on each axis")
        if len(blocked) != nx * ny or len(static_blocked) != nx * ny:
            raise ValueError("occupancy masks do not match the declared grid shape")
        if inflation_m < 0.0:
            raise ValueError("inflation_m must be non-negative")
        self._origin_x = origin_x
        self._origin_y = origin_y
        self._res = resolution
        self._nx = nx
        self._ny = ny
        self._blocked = blocked
        self._static = static_blocked
        self._inflation_m = inflation_m
        self._zones_blocking = zones_blocking
        self._map_id = map_id
        self._obstacle_count = obstacle_count

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    @classmethod
    def from_map(
        cls,
        warehouse_map: WarehouseMap,
        clearance_m: float,
        extra_blocked: Sequence[Circle] = (),
        *,
        zones_blocking: bool = False,
        resolution_m: float | None = None,
    ) -> OccupancyGrid:
        """Build a grid for one robot's conservative planning inflation.

        Parameters
        ----------
        clearance_m:
            Planning inflation radius. Pass
            ``footprint.clearance_radius_m()`` to plan for that robot; it
            already accounts for a carried payload's overhang.
        extra_blocked:
            Additional circular blocked regions ``(cx, cy, radius_m)``. These
            are *claims*, not truth: they become part of the inflated mask only
            (never of ``static_blocked``) so the planner can keep telling a
            static obstacle apart from a reported obstruction.
        zones_blocking:
            ``True`` to also block zone ``protected_bounds`` (plan *around*
            exclusive zones). ``False`` (default) leaves zones passable, because
            zone entry is authorised by the grant protocol and not by geometry.
        """
        if clearance_m < 0.0:
            raise ValueError("clearance_m must be non-negative")
        res = warehouse_map.grid_resolution_m if resolution_m is None else resolution_m
        if res <= 0.0:
            raise ValueError("resolution must be positive")

        b = warehouse_map.boundary
        origin_x = b.min_x
        origin_y = b.min_y
        nx = math.ceil((b.max_x - b.min_x) / res)
        ny = math.ceil((b.max_y - b.min_y) / res)
        if nx * ny > MAX_CELLS:
            raise GridTooLargeError(
                f"grid {nx}x{ny} = {nx * ny} cells exceeds the {MAX_CELLS} cell budget; "
                f"raise map.grid_resolution_m above {res} m or shrink the map"
            )
        if b.max_x - b.min_x <= 2.0 * clearance_m or b.max_y - b.min_y <= 2.0 * clearance_m:
            raise GridTooLargeError(
                f"map {b.max_x - b.min_x:.2f} x {b.max_y - b.min_y:.2f} m is not wider than "
                f"2 x {clearance_m:.3f} m; there is no free space for this footprint"
            )
        blocked = bytearray(nx * ny)
        static = bytearray(nx * ny)

        _stamp_obstacles(warehouse_map, origin_x, origin_y, res, nx, ny, clearance_m, blocked, static)
        _stamp_boundary(
            b.min_x,
            b.min_y,
            b.max_x,
            b.max_y,
            origin_x,
            origin_y,
            res,
            nx,
            ny,
            clearance_m,
            blocked,
            static,
        )
        if zones_blocking:
            _stamp_zones(warehouse_map, origin_x, origin_y, res, nx, ny, blocked, static)
        _stamp_circles(extra_blocked, origin_x, origin_y, res, nx, ny, blocked)

        return cls(
            origin_x=origin_x,
            origin_y=origin_y,
            resolution=res,
            nx=nx,
            ny=ny,
            blocked=blocked,
            static_blocked=static,
            inflation_m=clearance_m,
            zones_blocking=zones_blocking,
            map_id=warehouse_map.map_id,
            obstacle_count=len(warehouse_map.obstacles),
        )

    def with_extra_blocked(self, circles: Sequence[Circle]) -> OccupancyGrid:
        """Return a new grid with additional blocked discs.

        The receiver is never mutated: an agent keeps its static grid for the
        whole run and derives a temporary one per replan.
        """
        if not circles:
            return self
        blocked = bytearray(self._blocked)
        _stamp_circles(circles, self._origin_x, self._origin_y, self._res, self._nx, self._ny, blocked)
        return OccupancyGrid(
            origin_x=self._origin_x,
            origin_y=self._origin_y,
            resolution=self._res,
            nx=self._nx,
            ny=self._ny,
            blocked=blocked,
            static_blocked=bytearray(self._static),
            inflation_m=self._inflation_m,
            zones_blocking=self._zones_blocking,
            map_id=self._map_id,
            obstacle_count=self._obstacle_count,
        )

    def required_clearance_m(self, footprint: Footprint) -> float:
        """Planning inflation a footprint needs (chassis or payload, whichever)."""
        return footprint.clearance_radius_m()

    def serves(self, footprint: Footprint) -> bool:
        """True when this grid was inflated enough for *footprint*."""
        return self._inflation_m + 1e-9 >= footprint.clearance_radius_m()

    # ------------------------------------------------------------------
    # geometry
    # ------------------------------------------------------------------

    @property
    def resolution(self) -> float:
        return self._res

    @property
    def shape(self) -> tuple[int, int]:
        """``(nx, ny)`` cells."""
        return (self._nx, self._ny)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """Grid rectangle ``(min_x, min_y, max_x, max_y)`` - the map boundary.

        Every cell centre lies inside it. Note the difference from
        :attr:`inflation_m`: the rectangle is the *building*, while the usable
        area is the rectangle shrunk by the inflation on all four sides.
        """
        return (
            self._origin_x,
            self._origin_y,
            self._origin_x + self._nx * self._res,
            self._origin_y + self._ny * self._res,
        )

    @property
    def usable_bounds(self) -> tuple[float, float, float, float]:
        """The rectangle a robot with this inflation may place its centre in."""
        inset = self._inflation_m
        return (
            self._origin_x + inset,
            self._origin_y + inset,
            self._origin_x + self._nx * self._res - inset,
            self._origin_y + self._ny * self._res - inset,
        )

    @property
    def inflation_m(self) -> float:
        return self._inflation_m

    @property
    def zones_blocking(self) -> bool:
        return self._zones_blocking

    @property
    def map_id(self) -> str:
        return self._map_id

    @property
    def obstacle_count(self) -> int:
        return self._obstacle_count

    @property
    def cells_total(self) -> int:
        return self._nx * self._ny

    @property
    def cells_blocked_count(self) -> int:
        return sum(self._blocked)

    @property
    def cells_inflated_count(self) -> int:
        """Cells blocked only because of inflation, not by static geometry.

        A large value means the robot's footprint is squeezing real aisle width
        out of the map - a planner diagnostic, reported, never hidden.
        """
        inflated = 0
        blocked, static = self._blocked, self._static
        for i, flag in enumerate(blocked):
            if flag and not static[i]:
                inflated += 1
        return inflated

    def inside(self, x: float, y: float) -> bool:
        """True when ``(x, y)`` falls inside the grid rectangle (not the map)."""
        i = math.floor((x - self._origin_x) / self._res)
        j = math.floor((y - self._origin_y) / self._res)
        return 0 <= i < self._nx and 0 <= j < self._ny

    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        """Cell indices of the centre-nearest cell, clamped into the grid."""
        i = math.floor((x - self._origin_x) / self._res)
        j = math.floor((y - self._origin_y) / self._res)
        if i < 0:
            i = 0
        elif i >= self._nx:
            i = self._nx - 1
        if j < 0:
            j = 0
        elif j >= self._ny:
            j = self._ny - 1
        return i, j

    def cell_centre(self, i: int, j: int) -> Vec2:
        return (
            self._origin_x + (i + 0.5) * self._res,
            self._origin_y + (j + 0.5) * self._res,
        )

    def is_free(self, x: float, y: float) -> bool:
        """True when ``(x, y)`` is inside the grid and not blocked."""
        if not self.inside(x, y):
            return False
        i, j = self.cell_of(x, y)
        return self._blocked[i * self._ny + j] == 0

    def blocked(self, x: float, y: float) -> bool:
        """Conservative inverse of :meth:`is_free`. Outside the grid is blocked."""
        return not self.is_free(x, y)

    def blocked_by_static_geometry(self, x: float, y: float) -> bool:
        """True when blocked even at zero inflation (obstacle / boundary / zone)."""
        if not self.inside(x, y):
            return True
        i, j = self.cell_of(x, y)
        return self._static[i * self._ny + j] != 0

    def nearest_free(self, x: float, y: float) -> Vec2:
        """Centre of the nearest free cell, found by expanding rings.

        Deterministic: rings grow outward and each ring is scanned in ascending
        cell index, so the answer does not depend on any iteration order.
        Raises :class:`ValueError` when the grid has no free cell at all.
        """
        i0, j0 = self.cell_of(x, y)
        limit = max(self._nx, self._ny)
        for radius in range(limit):
            best: tuple[float, int, int] | None = None
            for i in range(max(0, i0 - radius), min(self._nx, i0 + radius + 1)):
                for j in range(max(0, j0 - radius), min(self._ny, j0 + radius + 1)):
                    if abs(i - i0) != radius and abs(j - j0) != radius:
                        continue
                    if self._blocked[i * self._ny + j]:
                        continue
                    cx, cy = self.cell_centre(i, j)
                    d = math.hypot(cx - x, cy - y)
                    key = (d, i, j)
                    if best is None or key < best:
                        best = key
            if best is not None:
                return self.cell_centre(best[1], best[2])
        raise ValueError("occupancy grid contains no free cell")

    def segment_free(self, a: Vec2, b: Vec2, samples: int = 0) -> bool:
        """Sampled line-of-sight test on the inflated mask.

        ``samples`` is the number of equidistant probe points including both
        endpoints; ``0`` means "choose a spacing of at most half a cell", which
        is dense enough that a diagonal cannot cut an uninflated-blocked corner
        between two probes. This is a *discrete* test, not a continuous
        clearance certificate - the safety gate remains the authority.
        """
        ax, ay = a
        bx, by = b
        length = math.hypot(bx - ax, by - ay)
        if samples < 2:
            spacing = self._res / 2.0
            samples = max(2, math.ceil(length / spacing) + 1)
        last = samples - 1
        for k in range(samples):
            t = k / last
            if not self.is_free(ax + (bx - ax) * t, ay + (by - ay) * t):
                return False
        return True


def _stamp_box(
    boxes: Sequence[tuple[float, float, float, float, float]],
    origin_x: float,
    origin_y: float,
    res: float,
    nx: int,
    ny: int,
    inflation_m: float,
    blocked: bytearray,
    static: bytearray,
) -> None:
    """Stamp a batch of ``(cx, cy, theta, length, width)`` oriented boxes."""
    for cx, cy, theta, length_m, width_m in boxes:
        ex, ey = _obstacle_half_extents(length_m, width_m, theta)
        i0 = math.floor((cx - ex - inflation_m - origin_x) / res)
        i1 = math.ceil((cx + ex + inflation_m - origin_x) / res)
        j0 = math.floor((cy - ey - inflation_m - origin_y) / res)
        j1 = math.ceil((cy + ey + inflation_m - origin_y) / res)
        if i1 < 0 or j1 < 0 or i0 >= nx or j0 >= ny:
            continue
        lo_i, hi_i = max(0, i0), min(nx - 1, i1)
        lo_j, hi_j = max(0, j0), min(ny - 1, j1)
        for i in range(lo_i, hi_i + 1):
            px = origin_x + (i + 0.5) * res
            base = i * ny
            for j in range(lo_j, hi_j + 1):
                py = origin_y + (j + 0.5) * res
                d = _point_box_distance(px, py, cx, cy, theta, length_m, width_m)
                k = base + j
                if d <= 1e-12:
                    static[k] = 1
                if d <= inflation_m + 1e-12:
                    blocked[k] = 1


def _stamp_obstacles(
    warehouse_map: WarehouseMap,
    origin_x: float,
    origin_y: float,
    res: float,
    nx: int,
    ny: int,
    inflation_m: float,
    blocked: bytearray,
    static: bytearray,
) -> None:
    boxes = [(o.pose.x, o.pose.y, o.pose.theta, o.length_m, o.width_m) for o in warehouse_map.obstacles]
    _stamp_box(boxes, origin_x, origin_y, res, nx, ny, inflation_m, blocked, static)


def _stamp_zones(
    warehouse_map: WarehouseMap,
    origin_x: float,
    origin_y: float,
    res: float,
    nx: int,
    ny: int,
    blocked: bytearray,
    static: bytearray,
) -> None:
    """Zone protected geometry is already inflated; stamp it at zero margin."""
    boxes = []
    for zone in warehouse_map.zones:
        x0, y0, x1, y1 = zone.protected_bounds
        cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        boxes.append((cx, cy, 0.0, max(1e-9, x1 - x0), max(1e-9, y1 - y0)))
    _stamp_box(boxes, origin_x, origin_y, res, nx, ny, 0.0, blocked, static)


def _stamp_boundary(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    origin_x: float,
    origin_y: float,
    res: float,
    nx: int,
    ny: int,
    inflation_m: float,
    blocked: bytearray,
    static: bytearray,
) -> None:
    lo_x, hi_x = min_x + inflation_m, max_x - inflation_m
    lo_y, hi_y = min_y + inflation_m, max_y - inflation_m
    for i in range(nx):
        px = origin_x + (i + 0.5) * res
        col_outside_static = px < min_x or px > max_x
        col_outside = px < lo_x or px > hi_x
        base = i * ny
        for j in range(ny):
            py = origin_y + (j + 0.5) * res
            if col_outside_static or py < min_y or py > max_y:
                static[base + j] = 1
            if col_outside or py < lo_y or py > hi_y:
                blocked[base + j] = 1


def _stamp_circles(
    circles: Sequence[Circle],
    origin_x: float,
    origin_y: float,
    res: float,
    nx: int,
    ny: int,
    blocked: bytearray,
) -> None:
    for circle in circles:
        cx, cy, radius = circle
        i0 = math.floor((cx - radius - origin_x) / res)
        i1 = math.ceil((cx + radius - origin_x) / res)
        j0 = math.floor((cy - radius - origin_y) / res)
        j1 = math.ceil((cy + radius - origin_y) / res)
        lo_i, hi_i = max(0, i0), min(nx - 1, i1)
        lo_j, hi_j = max(0, j0), min(ny - 1, j1)
        r2 = radius * radius
        for i in range(lo_i, hi_i + 1):
            dx = origin_x + (i + 0.5) * res - cx
            base = i * ny
            for j in range(lo_j, hi_j + 1):
                dy = origin_y + (j + 0.5) * res - cy
                if dx * dx + dy * dy <= r2:
                    blocked[base + j] = 1

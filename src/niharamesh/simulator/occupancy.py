"""Uniform-grid free-space structure over a :class:`WarehouseMap`.

Why a grid at all
-----------------
Exact oriented-box tests are the right primitive for collision, but they are the
wrong primitive for "can a 0.7 m robot get from here to there at all". A grid
gives the planner a cheap, conservative, cacheable answer, and it gives the
operator a picture of where the warehouse is not.

Conservative means asymmetric on purpose
----------------------------------------
:func:`OccupancyGrid.blocked` marks a cell when its **centre** lies within
``clearance_radius`` of an obstacle. The residual error is therefore at most
``resolution / 2 + clearance_radius`` in the other direction: a cell marked free
can still have an obstacle corner inside it. Everything that actually decides
whether a robot moves re-checks with exact geometry, so this approximation can
only make the planner pessimistic, never optimistic. That direction is the whole
point -- an optimistic inflation would be an invented safety margin.

Cells outside the map envelope are blocked, and a caller may additionally declare
zone ids whose protected geometry is treated as blocked for planning purposes.
That declaration is the caller's, not the grid's: the grid does not know which
zones a particular robot needs authority for, and guessing would be planning.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Final

import numpy as np

from niharamesh.domain.map import WarehouseMap

__all__ = ["MAX_GRID_CELLS", "OccupancyGrid"]

#: Refuse absurd allocations rather than exhausting memory. A 500 m map at the
#: finest legal resolution would be 625 million cells; that is a scenario-authoring
#: error, and failing at build time is how the operator learns about it.
MAX_GRID_CELLS: Final[int] = 4_000_000

Vec2 = tuple[float, float]


class OccupancyGrid:
    """Immutable blocked/free raster over one map.

    Built once per snapshot. The world may insert temporary obstacles at runtime,
    in which case a new grid is built for the planner; the grid never mutates,
    so a route computed against it stays valid for the geometry it was computed
    from.
    """

    __slots__ = ("_blocked", "_min_x", "_min_y", "_nx", "_ny", "_resolution", "_zones")

    def __init__(
        self,
        blocked: np.ndarray,
        *,
        resolution_m: float,
        origin_xy: tuple[float, float],
        zones: tuple[tuple[str, float, float, float, float], ...],
    ) -> None:
        self._blocked = blocked
        self._resolution = float(resolution_m)
        self._min_x = float(origin_xy[0])
        self._min_y = float(origin_xy[1])
        self._ny, self._nx = (int(blocked.shape[0]), int(blocked.shape[1]))
        self._zones = zones

    # -- construction ------------------------------------------------------- #

    @classmethod
    def build(
        cls,
        warehouse_map: WarehouseMap,
        clearance_radius_m: float = 0.0,
        *,
        resolution_m: float | None = None,
        protected_zone_ids: Iterable[str] = (),
    ) -> OccupancyGrid:
        """Rasterise *warehouse_map*, inflated by ``clearance_radius_m``.

        ``protected_zone_ids`` names zones whose protected rectangle is treated
        as blocked for planning. Passing zone ids here is a declaration by the
        caller, typically "every zone this robot could be asked to enter".
        """
        if clearance_radius_m < 0.0:
            raise ValueError("clearance_radius_m must be non-negative")
        res = float(resolution_m if resolution_m is not None else warehouse_map.grid_resolution_m)
        if res <= 0.0:
            raise ValueError("resolution must be positive")

        boundary = warehouse_map.boundary
        span_x = boundary.max_x - boundary.min_x
        span_y = boundary.max_y - boundary.min_y
        nx = max(1, math.ceil(span_x / res))
        ny = max(1, math.ceil(span_y / res))
        if nx * ny > MAX_GRID_CELLS:
            raise ValueError(
                f"occupancy grid of {nx}x{ny} = {nx * ny} cells exceeds the "
                f"{MAX_GRID_CELLS} cell limit; increase grid_resolution_m"
            )

        xs = boundary.min_x + (np.arange(nx, dtype=np.float64) + 0.5) * res
        ys = boundary.min_y + (np.arange(ny, dtype=np.float64) + 0.5) * res
        gx, gy = np.meshgrid(xs, ys)
        px = gx.ravel()
        py = gy.ravel()

        blocked = np.zeros(px.size, dtype=bool)
        # Outside the usable envelope: a robot centre there is off the map.
        blocked |= (px < boundary.min_x) | (px > boundary.max_x)
        blocked |= (py < boundary.min_y) | (py > boundary.max_y)

        for obstacle in warehouse_map.obstacles:
            half_l = obstacle.length_m / 2.0
            half_w = obstacle.width_m / 2.0
            c, s = math.cos(obstacle.pose.theta), math.sin(obstacle.pose.theta)
            dx = px - obstacle.pose.x
            dy = py - obstacle.pose.y
            lx = dx * c + dy * s
            ly = -dx * s + dy * c
            # Distance from a point to the nearest point of the rectangle.
            outside = np.maximum(np.maximum(np.abs(lx) - half_l, np.abs(ly) - half_w), 0.0)
            blocked |= outside <= clearance_radius_m

        wanted = set(protected_zone_ids)
        zones: list[tuple[str, float, float, float, float]] = []
        for zone in warehouse_map.zones:
            zones.append((zone.id, *zone.protected_bounds))
            if zone.id in wanted:
                x0, y0, x1, y1 = zone.protected_bounds
                blocked |= (px >= x0) & (px <= x1) & (py >= y0) & (py <= y1)

        return cls(
            blocked.reshape(ny, nx),
            resolution_m=res,
            origin_xy=(boundary.min_x, boundary.min_y),
            zones=tuple(zones),
        )

    # -- accessors ---------------------------------------------------------- #

    @property
    def resolution(self) -> float:
        """Cell size in metres."""
        return self._resolution

    @property
    def shape(self) -> tuple[int, int]:
        """``(ny, nx)`` -- rows first, matching array indexing."""
        return (self._ny, self._nx)

    @property
    def blocked_fraction(self) -> float:
        """Share of cells marked blocked. Reported, never assumed to be small."""
        if self._blocked.size == 0:
            return 0.0
        return float(np.count_nonzero(self._blocked) / self._blocked.size)

    def world_to_cell(self, x: float, y: float) -> tuple[int, int]:
        """World metres to integer cell indices. May fall outside the grid."""
        ix = math.floor((x - self._min_x) / self._resolution)
        iy = math.floor((y - self._min_y) / self._resolution)
        return (int(ix), int(iy))

    def cell_to_world(self, ix: int, iy: int) -> Vec2:
        """Integer cell indices to that cell's centre, in metres."""
        return (
            self._min_x + (ix + 0.5) * self._resolution,
            self._min_y + (iy + 0.5) * self._resolution,
        )

    def blocked(self, x: float, y: float) -> bool:
        """True when this world point is blocked. Outside the grid counts blocked."""
        ix, iy = self.world_to_cell(x, y)
        return self._cell_blocked(ix, iy)

    def is_free(self, x: float, y: float) -> bool:
        return not self.blocked(x, y)

    def neighbours_8(self, ix: int, iy: int) -> tuple[tuple[int, int], ...]:
        """The eight neighbouring cell indices, clipped to the grid, in fixed order.

        The order is fixed rather than sorted so a search that depends on it is
        reproducible; a BFS that returned neighbours in set order would be a
        non-deterministic planner.
        """
        out: list[tuple[int, int]] = []
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                nx, ny = ix + dx, iy + dy
                if 0 <= nx < self._nx and 0 <= ny < self._ny:
                    out.append((nx, ny))
        return tuple(out)

    def nearest_free_cell(self, ix: int, iy: int) -> tuple[int, int] | None:
        """Closest unblocked cell by 8-connected distance, or ``None``.

        A blocked region larger than the map's free space returns ``None``
        honestly instead of a far-away cell that would send a robot into a wall.
        """
        if self._cell_blocked(ix, iy):
            seen = {(ix, iy)}
            frontier = [(ix, iy)]
            while frontier:
                nxt: list[tuple[int, int]] = []
                for cx, cy in frontier:
                    for nx, ny in self.neighbours_8(cx, cy):
                        if (nx, ny) in seen:
                            continue
                        seen.add((nx, ny))
                        if not self._cell_blocked(nx, ny):
                            return (nx, ny)
                        nxt.append((nx, ny))
                frontier = nxt
            return None
        return (ix, iy)

    def segment_free(self, a: Vec2, b: Vec2, samples: int = 32) -> bool:
        """True when every sample along ``a -> b`` is in free space.

        Used for line-of-sight path smoothing. ``samples`` is explicit because
        the honest answer depends on it: a coarser sample can step over a
        blocked cell. This is a *candidate smoother*, never a safety check.
        """
        if samples < 2:
            raise ValueError("segment_free needs at least two samples")
        ax, ay = a
        bx, by = b
        for i in range(samples):
            s = i / (samples - 1)
            if self.blocked(ax + (bx - ax) * s, ay + (by - ay) * s):
                return False
        return True

    def zones_containing(self, x: float, y: float) -> tuple[str, ...]:
        """Ids of zones whose protected geometry contains this point.

        A geometric containment query only. Whether the robot is *allowed* to be
        inside is a coordination decision that belongs to the protocol, never to
        the occupancy structure.
        """
        return tuple(zid for zid, x0, y0, x1, y1 in self._zones if x0 <= x <= x1 and y0 <= y <= y1)

    def free_cells(self) -> Sequence[tuple[int, int]]:
        """Every unblocked cell. Only for small maps and diagnostics."""
        ys, xs = np.nonzero(~self._blocked)
        return [(int(x), int(y)) for y, x in zip(ys, xs, strict=True)]

    # -- internals ---------------------------------------------------------- #

    def _cell_blocked(self, ix: int, iy: int) -> bool:
        if not (0 <= ix < self._nx and 0 <= iy < self._ny):
            return True
        return bool(self._blocked[iy, ix])

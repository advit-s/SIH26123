"""Approximate space-time reservation planning - honestly named, honestly bounded.

What this is
------------
A space x time search over the *inflated* occupancy grid. State is
``(cell, arrival tick)``. A peer-reported reservation ``(cell, t_start, t_end)``
removes those ticks from that cell, and the search may *delay* in place to arrive
later. The plan it returns carries the reservations the robot claims for its own
transit, one per cell it occupies.

What this is NOT
----------------
**This is not SIPP.** It is named ``ApproxSippSingleCellPlanner`` because it is a
space-time planner in SIPP's *family of ideas*, and nothing more. The differences
are load-bearing:

* Original SIPP assumes the agent can stop instantaneously. A differential-drive
  AMR cannot: it has non-zero deceleration and non-zero kinematic lag. Per Ali &
  Yakovlev (arXiv:2302.00776), original SIPP is **incomplete** once kinodynamic
  constraints apply. This planner inherits that incompleteness by construction:
  it may delay inside a cell, but it never models the stopping distance a real
  deceleration needs, so a reservation that "expires" mid-transit is not
  physically safe.
* It searches a **single** cell abstraction. It does not model the swept volume
  of a rotation, so in a one-cell aisle a turn is treated as if the body sweeps
  nothing. That is optimistic exactly where our safety problem lives.
* It is **not complete** and makes **no optimality claim**. It minimises arrival
  tick under the abstract model; nothing shows that the abstract optimum is
  physically achievable, and nothing here asserts it.

What it does guarantee, and what a test may assert
--------------------------------------------------
Only two mechanical properties:

1. the reservations a plan declares are conflict-free among themselves - the
   robot never claims two cells at the same tick, and never claims one cell twice
   over overlapping intervals;
2. a reservation the planner was *told* about causes a delay, or an explicit
   failure carrying a reason. It never plans straight through a known claim.

The feature flag
----------------
The module is unreachable from outside :mod:`niharamesh.planning` unless the run
latched ``FeatureFlags.temporal_planning`` (see
:func:`niharamesh.planning.set_temporal_exports_enabled`). Even with the flag on,
the class refuses to plan unless constructed with ``enabled=True``, so the run's
feature switch is a second explicit statement rather than an import accident.

Everything here is local. The planner sees the shared map and the reservations
peers published about themselves; it never sees another robot's true state. The
safety gate does not consult this planner (AGENTS.md rule 7): exclusivity comes
from the zone-grant protocol, so an incomplete *plan* costs throughput, while an
incomplete *safety* mechanism would be a defect.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

# The feature gate lives in :mod:`niharamesh.planning` so it is a single auditable
# statement. It is re-checked *here*, at import time, because a re-check inside the
# package's ``__getattr__`` alone would not stop a caller who reached for
# ``import niharamesh.planning.temporal`` directly. Two checks in two places, both
# reading the same latch, is the honest way to say "no import path reaches this".
import niharamesh.planning as _planning
from niharamesh.domain.config import FeatureFlags
from niharamesh.domain.pose import Footprint
from niharamesh.planning.grid import OccupancyGrid

if not _planning.temporal_exports_enabled():  # pragma: no cover - import-time guard
    raise ImportError(
        "niharamesh.planning.temporal is behind FeatureFlags.temporal_planning "
        "(RoutingPolicy.TEMPORAL_SIPP_APPROX). A run must latch "
        "niharamesh.planning.set_temporal_exports_enabled(True) at launch, from its own "
        "FeatureFlags, before this module may be imported. Exports of a run with the "
        "flag off must never be charted as if the planner were complete."
    )

__all__ = [
    "FEATURE_FLAG_NAME",
    "ApproxSippSingleCellPlanner",
    "Reservation",
    "TemporalPlan",
    "TemporalPlanFailure",
    "reservations_needed",
    "temporal_planning_enabled",
]

#: ``(cell_index, t_start_tick, t_end_tick)``, both ends inclusive.
Reservation = tuple[int, int, int]

FEATURE_FLAG_NAME: Final[str] = "temporal_planning"

PLANNER_LABEL: Final[str] = "approximate-spatial-temporal"
"""Provenance string that must appear in any manifest built from this planner."""

_SQRT2 = math.sqrt(2.0)


def _octile_cells(si: int, sj: int, gi: int, gj: int) -> float:
    """Exact 8-connected lattice distance in cell units (cardinal step = 1).

    Written as ``(dx + dy) - (2 - sqrt2) * min(dx, dy)`` so it uses the same unit
    costs the expansion charges; an over-estimating heuristic would prune the
    arrival-tick optimum and no optimality claim would survive.
    """
    dx = float(abs(si - gi))
    dy = float(abs(sj - gj))
    return (dx + dy) - (2.0 - _SQRT2) * min(dx, dy)


#: Offsets in a fixed declaration order, matching the cardinal + diagonal set.
_OFFSETS: Final[tuple[tuple[int, int, float], ...]] = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, _SQRT2),
    (1, -1, _SQRT2),
    (-1, 1, _SQRT2),
    (-1, -1, _SQRT2),
)


def temporal_planning_enabled(flags: FeatureFlags) -> bool:
    """The one place the feature flag is read."""
    return flags.temporal_planning


@dataclass(frozen=True, slots=True)
class TemporalPlan:
    """A space-time route: which cell, in which tick."""

    cells: tuple[tuple[int, int], ...]
    """``(cell_index, arrival_tick)`` in traversal order."""

    ticks_per_cell: int
    duration_ticks: int
    delay_ticks: int
    """Ticks spent stationary beyond what a reservation-free route would need."""

    horizon_ticks: int
    planner_label: str = PLANNER_LABEL

    @property
    def reservations(self) -> tuple[Reservation, ...]:
        return reservations_needed(self)


@dataclass(frozen=True, slots=True)
class TemporalPlanFailure:
    """Explicit failure. There is no partial temporal plan."""

    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.reason}: {self.detail}" if self.detail else self.reason


def reservations_needed(plan: TemporalPlan) -> tuple[Reservation, ...]:
    """The ``(cell, t_start, t_end)`` claims this plan requires.

    One reservation per occupied cell, covering exactly the ticks the robot is
    projected to be inside it. Two plans whose claims overlap conflict; that is
    the property the tests check, and nothing stronger is claimed.
    """
    span = plan.ticks_per_cell
    return tuple((cell, tick, tick + span - 1) for cell, tick in plan.cells)


class ApproxSippSingleCellPlanner:
    """Space-time search on the inflated grid. See the module docstring."""

    def __init__(
        self,
        grid: OccupancyGrid,
        *,
        max_speed_mps: float = 0.4,
        tick_s: float = 0.05,
        horizon_ticks: int = 4000,
        enabled: bool = False,
    ) -> None:
        if max_speed_mps <= 0.0:
            raise ValueError("max_speed_mps must be positive")
        if tick_s <= 0.0:
            raise ValueError("tick_s must be positive")
        if horizon_ticks <= 0:
            raise ValueError("horizon_ticks must be positive")
        self._grid = grid
        self._max_speed_mps = max_speed_mps
        self._tick_s = tick_s
        self._horizon_ticks = horizon_ticks
        self._enabled = enabled
        self._span = max(1, math.ceil(grid.resolution / (max_speed_mps * tick_s)))

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def ticks_per_cell(self) -> int:
        return self._span

    @property
    def tick_s(self) -> float:
        return self._tick_s

    @property
    def horizon_ticks(self) -> int:
        return self._horizon_ticks

    def plan(
        self,
        goal: tuple[float, float],
        footprint: Footprint,
        reservations: Sequence[Reservation] = (),
        *,
        start: tuple[float, float] | None = None,
    ) -> TemporalPlan | TemporalPlanFailure:
        """Search for a delayed route. Returns a plan or an explicit failure."""
        if not self._enabled:
            return TemporalPlanFailure(
                "temporal_planner_disabled",
                f"FeatureFlags.{FEATURE_FLAG_NAME} is off for this run",
            )
        if start is None:
            return TemporalPlanFailure(
                "no_start_position",
                "a local planner may not guess where the robot is",
            )
        grid = self._grid
        if not grid.serves(footprint):
            return TemporalPlanFailure(
                "insufficient_clearance",
                f"grid inflation {grid.inflation_m:.3f} m does not serve "
                f"{footprint.clearance_radius_m():.3f} m",
            )
        if grid.blocked(*start):
            return TemporalPlanFailure("blocked_start", "start cell is not free on the inflated grid")
        if grid.blocked(*goal):
            return TemporalPlanFailure("blocked_goal", "goal cell is not free on the inflated grid")

        nx, ny = grid.shape
        si, sj = grid.cell_of(*start)
        gi, gj = grid.cell_of(goal[0], goal[1])
        start_cell = si * ny + sj
        goal_cell = gi * ny + gj
        claims = _index_reservations(reservations)
        route, arrival = self._search(grid, nx, ny, start_cell, goal_cell, claims)
        if route is None:
            return TemporalPlanFailure(
                "no_temporal_path",
                (
                    f"no arrival within {self._horizon_ticks} ticks "
                    f"({self._horizon_ticks * self._tick_s:.2f} s) given the reported "
                    f"reservations; this planner is incomplete, so this is not a proof "
                    f"that the goal is unreachable"
                ),
            )
        static = _static_ticks(si, sj, gi, gj, grid.resolution, self._max_speed_mps, self._tick_s)
        return TemporalPlan(
            cells=route,
            ticks_per_cell=self._span,
            duration_ticks=arrival,
            delay_ticks=max(0, arrival - static),
            horizon_ticks=self._horizon_ticks,
        )

    def _search(
        self,
        grid: OccupancyGrid,
        nx: int,
        ny: int,
        start_cell: int,
        goal_cell: int,
        claims: dict[int, list[tuple[int, int]]],
    ) -> tuple[tuple[tuple[int, int], ...] | None, int]:
        """A* minimising arrival tick. Keys encode ``(cell, tick)`` as a product."""
        span = self._span
        stride = self._horizon_ticks + span + 1
        start_key = start_cell * stride
        h0 = _tick_heuristic(*divmod(start_cell, ny), *divmod(goal_cell, ny), span)
        counter = 0
        heap: list[tuple[int, int, int, int]] = [(h0, h0, 0, start_key)]
        best: dict[int, int] = {start_key: 0}
        parent: dict[int, int] = {}
        closed: set[int] = set()
        goal_key: int | None = None

        while heap:
            _, g, _order, key = heapq.heappop(heap)
            if key in closed:
                continue
            closed.add(key)
            cell, tick = divmod(key, stride)
            if cell == goal_cell:
                goal_key = key
                break
            if tick >= self._horizon_ticks:
                continue
            ci, cj = divmod(cell, ny)
            for di, dj, span_factor in _OFFSETS:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < nx and 0 <= nj < ny):
                    continue
                if grid.blocked(*grid.cell_centre(ni, nj)):
                    continue
                if (
                    di
                    and dj
                    and (
                        grid.blocked(*grid.cell_centre(ci + di, cj))
                        or grid.blocked(*grid.cell_centre(ci, cj + dj))
                    )
                ):
                    continue
                step = max(1, math.ceil(span * span_factor))
                arrival = tick + step
                if arrival + span - 1 > self._horizon_ticks:
                    continue
                n_cell = ni * ny + nj
                if _conflicts(claims.get(n_cell, ()), arrival, arrival + span - 1):
                    continue
                n_key = n_cell * stride + arrival
                if best.get(n_key, math.inf) <= g + step:
                    continue
                best[n_key] = g + step
                parent[n_key] = key
                counter += 1
                h = _tick_heuristic(ni, nj, *divmod(goal_cell, ny), span)
                heapq.heappush(heap, (g + step + h, h, counter, n_key))

        if goal_key is None:
            return None, 0
        route: list[tuple[int, int]] = []
        node = goal_key
        while node != start_key:
            cell, tick = divmod(node, stride)
            route.append((cell, tick))
            node = parent[node]
        route.append((start_cell, 0))
        route.reverse()
        return tuple(route), divmod(goal_key, stride)[1]


def _index_reservations(
    reservations: Sequence[Reservation],
) -> dict[int, list[tuple[int, int]]]:
    out: dict[int, list[tuple[int, int]]] = {}
    for cell, t_start, t_end in reservations:
        if t_end < t_start:
            raise ValueError("reservation interval is inverted")
        out.setdefault(cell, []).append((t_start, t_end))
    for intervals in out.values():
        intervals.sort()
    return out


def _conflicts(intervals: Sequence[tuple[int, int]], t0: int, t1: int) -> bool:
    """True when the closed interval ``[t0, t1]`` overlaps any reserved interval."""
    for a, b in intervals:
        if a > t1:
            return False
        if b >= t0:
            return True
    return False


def _tick_heuristic(si: int, sj: int, gi: int, gj: int, span: int) -> int:
    """Octile lower bound in cell units, rounded **down** to whole ticks.

    Rounding down keeps the heuristic admissible; rounding up could prune the
    arrival-tick optimum.
    """
    return math.floor(_octile_cells(si, sj, gi, gj) * span)


def _static_ticks(si: int, sj: int, gi: int, gj: int, resolution: float, speed: float, tick_s: float) -> int:
    """Ticks a reservation-free octile route would take, for delay bookkeeping."""
    metres = _octile_cells(si, sj, gi, gj) * resolution
    return math.ceil(metres / (speed * tick_s))

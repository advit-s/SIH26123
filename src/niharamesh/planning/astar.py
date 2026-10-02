"""8-connected A* over the inflated occupancy grid.

Cost scale - one declared unit, seconds
---------------------------------------
Every search cost in this module is a **duration in seconds**, so node costs,
the octile heuristic and the reported ``cost_s`` are directly comparable:

* a move of length ``d`` metres costs ``d / max_linear_mps``;
* a heading change of ``|dtheta|`` radians costs
  ``|dtheta| * TurnCost.seconds_per_radian`` where
  ``seconds_per_radian == turn_weight / max_angular_radps`` - i.e. the time this
  robot needs to rotate one radian at its own declared angular limit.

The turn weight is therefore *not* an arbitrary penalty tacked onto metres: it is
on the same clock as the distance term by construction. Because the turn term is
non-negative and the octile heuristic is the pure distance lower bound divided
by the same ``max_linear_mps``, the heuristic stays **admissible and
consistent**, so the first goal pop is cost-optimal *for this declared cost
model*. It is not optimal for the world: the model deliberately ignores actuator
lag, tracking error and dynamic traffic, and any such optimism is inherited by
every duration this module reports.

Determinism
-----------
The open list is a binary heap keyed on ``(f, h, insertion_index)`` with a
monotonically increasing counter, and movement is expanded in a fixed
declaration order. No tie is ever resolved by ``set`` iteration order, by
dictionary order, or by float equality, so the same inputs produce the same
waypoint tuple byte-for-byte.
"""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from niharamesh.domain.map import RouteEdge, WarehouseMap
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.domain.units import angle_difference
from niharamesh.planning.grid import Circle, OccupancyGrid

__all__ = [
    "AStarPlanner",
    "Circle",
    "PathResult",
    "PathStatus",
    "TurnCost",
    "UnreachableReason",
    "Vec2",
    "planner_from_map",
]

Vec2 = tuple[float, float]

_SQRT2 = math.sqrt(2.0)

#: Cardinal + diagonal offsets in a fixed declaration order. The index of an
#: offset *is* its heading class, which keeps heading bookkeeping trivial and
#: removes any chance of a heading table drifting out of sync with the moves.
_MOVES: tuple[tuple[int, int, float], ...] = (
    (1, 0, 1.0),
    (-1, 0, 1.0),
    (0, 1, 1.0),
    (0, -1, 1.0),
    (1, 1, _SQRT2),
    (1, -1, _SQRT2),
    (-1, 1, _SQRT2),
    (-1, -1, _SQRT2),
)

#: Heading (radians) per heading class. A lattice A* cannot rotate continuously,
#: so a diagonal step is modelled as a 45 degree heading change. This is a
#: declared approximation of the robot's curvature, not a measurement.
_HEADINGS: tuple[float, ...] = (
    0.0,
    math.pi,
    math.pi / 2.0,
    -math.pi / 2.0,
    math.pi / 4.0,
    -math.pi / 4.0,
    3.0 * math.pi / 4.0,
    -3.0 * math.pi / 4.0,
)

_HEADING_CLASSES: Final[int] = len(_HEADINGS)


def octile_distance_m(dx_m: float, dy_m: float) -> float:
    """Exact shortest 8-connected lattice distance for a cardinal step of 1 m.

    ``sqrt(2) * min + (max - min)``, written as ``(dx + dy) - (2 - sqrt2) * min``
    so the diagonal and cardinal unit costs are the same constants the search
    charges. An incorrect octile is an inadmissible heuristic, which silently
    costs optimality, so it lives in one place and is unit-tested.
    """
    dx, dy = abs(dx_m), abs(dy_m)
    return (dx + dy) - (2.0 - _SQRT2) * min(dx, dy)


class PathStatus(StrEnum):
    """Outcome of one planning request. Never a silent partial path."""

    OK = "ok"
    UNREACHABLE = "unreachable"
    SEARCH_EXHAUSTED = "search_exhausted"
    """The expansion budget ran out. Reported separately from ``unreachable``:
    "not found within the budget" is not the same claim as "no path exists"."""

    INVALID_REQUEST = "invalid_request"
    """This grid does not serve that footprint, the start pose is missing, or the
    goal is not finite. Refused rather than approximated."""


class UnreachableReason(StrEnum):
    """Why no path was produced. Every value is a distinct, checkable claim."""

    BLOCKED_START = "blocked_start"
    """The start cell is inside static geometry (a shelf, or the wall)."""

    BLOCKED_GOAL = "blocked_goal"
    """The goal cell is inside static geometry."""

    NO_CONNECTION = "no_connection"
    """Both endpoints are free but no free chain links them."""

    INSUFFICIENT_CLEARANCE = "insufficient_clearance"
    """The endpoint is free in the *uninflated* map but blocked at this robot's
    planning inflation. That is a footprint-versus-aisle problem, not a map
    problem, and the two must never be reported interchangeably."""

    SEARCH_BUDGET_EXHAUSTED = "search_budget_exhausted"


@dataclass(frozen=True, slots=True)
class TurnCost:
    """Turn cost expressed on the same seconds scale as distance.

    ``max_linear_mps`` and ``max_angular_radps`` are the robot's *declared*
    actuator limits (configured assumptions, AGENTS.md rule 2). They are what
    convert metres and radians into seconds, and therefore the only reason a
    metres-valued octile distance may be divided by ``max_linear_mps`` without
    mixing units.
    """

    max_linear_mps: float = 0.4
    max_angular_radps: float = 1.0
    #: Multiplier on the turn term. ``1.0`` means "a radian costs exactly as long
    #: as rotating at the declared angular limit". Values above ``1.0`` buy
    #: straighter (fewer-turn) routes at the price of leaving the base model's
    #: cost-optimal solution; that trade is a configured preference, not a fact.
    turn_weight: float = 1.0

    def __post_init__(self) -> None:
        if self.max_linear_mps <= 0.0 or self.max_angular_radps <= 0.0:
            raise ValueError("declared actuator limits must be positive")
        if self.turn_weight < 0.0:
            raise ValueError("turn_weight must be non-negative")

    @property
    def seconds_per_radian(self) -> float:
        """Time to rotate one radian at the declared angular limit."""
        return self.turn_weight / self.max_angular_radps

    @property
    def seconds_per_metre(self) -> float:
        return 1.0 / self.max_linear_mps

    def turn_cost(self, from_heading_rad: float, to_heading_rad: float) -> float:
        return abs(angle_difference(from_heading_rad, to_heading_rad)) * self.seconds_per_radian

    def heuristic_seconds(self, dx_m: float, dy_m: float) -> float:
        """Octile lower bound in seconds. Ignores the non-negative turn term, so
        it never over-estimates the remaining cost."""
        return octile_distance_m(dx_m, dy_m) * self.seconds_per_metre


@dataclass(frozen=True, slots=True)
class PathResult:
    """Full planning outcome, including *why* there is no path.

    ``waypoints`` is empty unless ``status is PathStatus.OK``. A partial path is
    never returned as a plan: a truncated route that looks like a route is worse
    than an explicit failure, because the caller cannot tell it apart.
    """

    status: PathStatus
    waypoints: tuple[Vec2, ...] = ()
    length_m: float = 0.0
    cost_s: float = 0.0
    turn_count: int = 0
    reason: str = ""
    unreachable_reason: UnreachableReason | None = None
    expansions: int = 0
    version: int = 0

    @property
    def ok(self) -> bool:
        return self.status is PathStatus.OK


class AStarPlanner:
    """Local planner over one immutable grid. Implements ``PlannerPort``."""

    def __init__(
        self,
        grid: OccupancyGrid,
        *,
        turn_cost: TurnCost | None = None,
        directed_routes: Sequence[RouteEdge] = (),
        max_expansions: int = 200_000,
        current_pose: Pose2 | None = None,
    ) -> None:
        if max_expansions <= 0:
            raise ValueError("max_expansions must be positive")
        self._grid = grid
        self._turn_cost = TurnCost(
            max_linear_mps=turn_cost.max_linear_mps if turn_cost else 0.4,
            max_angular_radps=turn_cost.max_angular_radps if turn_cost else 1.0,
            turn_weight=turn_cost.turn_weight if turn_cost else 1.0,
        )
        self._max_expansions = max_expansions
        self._forbidden = _forbidden_transitions(grid, directed_routes)
        self._plan_version = 0
        self._grid_in_use = grid
        self._current_pose = current_pose
        self._last = PathResult(status=PathStatus.INVALID_REQUEST, reason="no plan has been requested yet")

    def set_current_pose(self, pose: Pose2 | None) -> None:
        """Publish this robot's own pose estimate.

        The port's ``plan(goal, footprint)`` shape carries no start pose, so the
        planner holds the robot's *own* pose here. This is not hidden truth: it
        is the robot's own pose, supplied by the agent that owns this process.
        """
        self._current_pose = pose

    @property
    def current_pose(self) -> Pose2 | None:
        return self._current_pose

    # ------------------------------------------------------------------
    # introspection
    # ------------------------------------------------------------------

    @property
    def grid(self) -> OccupancyGrid:
        """The static grid this planner was built on. Never mutated."""
        return self._grid

    @property
    def active_grid(self) -> OccupancyGrid:
        """The grid the most recent request actually used (may include claims)."""
        return self._grid_in_use

    @property
    def turn_cost(self) -> TurnCost:
        return self._turn_cost

    @property
    def plan_version(self) -> int:
        """Monotonic id of the last *successful* plan. ``0`` means "never"."""
        return self._plan_version

    @property
    def last_result(self) -> PathResult:
        """The full outcome of the most recent request.

        :meth:`plan` must return ``None`` on failure, because that is what
        :class:`~niharamesh.ports.PlannerPort` declares and a bare ``None``
        cannot carry a reason. Callers that need to explain the stop read this
        attribute; callers that ignore it are choosing not to explain it.
        """
        return self._last

    # ------------------------------------------------------------------
    # PlannerPort
    # ------------------------------------------------------------------

    def plan(self, goal: tuple[float, float], footprint: Footprint) -> tuple[Vec2, ...] | None:
        """``PlannerPort`` entry point. Returns ``None`` when there is no plan.

        ``None`` cannot carry a reason, so the reason is always available on
        :attr:`last_result`. Callers must not read ``None`` as "unreachable" -
        the four unreachability reasons and the search-budget case are distinct.
        """
        result = self._plan_on(self._grid, goal, footprint, start=self._current_pose)
        return result.waypoints or None

    def blocked_aware_plan(
        self,
        goal: tuple[float, float],
        footprint: Footprint,
        blocked: Sequence[Circle],
    ) -> tuple[Vec2, ...] | None:
        """Plan on a temporary copy of the grid with additional blocked discs.

        ``blocked`` entries are ``(cx, cy, radius_m)`` **claims**: what this
        robot was told by a peer or measured itself. They are never promoted into
        static map geometry, so the next plan against the unmodified map is
        unaffected and the claim's age can still be reported separately.
        """
        grid = self._grid.with_extra_blocked(blocked)
        result = self._plan_on(grid, goal, footprint, start=self._current_pose)
        return result.waypoints or None

    def plan_detailed(
        self,
        goal: tuple[float, float],
        footprint: Footprint,
        *,
        start: Pose2,
    ) -> PathResult:
        return self._plan_on(self._grid, goal, footprint, start=start)

    def blocked_aware_plan_detailed(
        self,
        goal: tuple[float, float],
        footprint: Footprint,
        blocked: Sequence[Circle],
        *,
        start: Pose2,
    ) -> PathResult:
        grid = self._grid.with_extra_blocked(blocked)
        return self._plan_on(grid, goal, footprint, start=start)

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def _plan_on(
        self,
        grid: OccupancyGrid,
        goal: Vec2,
        footprint: Footprint,
        *,
        start: Pose2 | None,
    ) -> PathResult:
        self._grid_in_use = grid
        if not grid.serves(footprint):
            return self._fail(
                PathStatus.INVALID_REQUEST,
                f"grid inflation {grid.inflation_m:.3f} m does not serve this footprint "
                f"(needs {footprint.clearance_radius_m():.3f} m)",
            )
        if start is None:
            return self._fail(
                PathStatus.INVALID_REQUEST,
                "start pose is required: a local planner may not guess where the robot is",
            )
        if not (math.isfinite(goal[0]) and math.isfinite(goal[1])):
            return self._fail(PathStatus.INVALID_REQUEST, "goal is not finite")

        start_xy: Vec2 = (start.x, start.y)
        start_cell = grid.cell_of(start.x, start.y)
        if grid.blocked(start.x, start.y):
            static = grid.blocked_by_static_geometry(start.x, start.y)
            if static:
                return self._fail(
                    PathStatus.UNREACHABLE,
                    f"start ({start.x:.3f}, {start.y:.3f}) lies in static map geometry",
                    UnreachableReason.BLOCKED_START,
                )
            return self._fail(
                PathStatus.UNREACHABLE,
                f"start ({start.x:.3f}, {start.y:.3f}) is inside the "
                f"{grid.inflation_m:.3f} m planning inflation",
                UnreachableReason.INSUFFICIENT_CLEARANCE,
            )
        if grid.blocked(goal[0], goal[1]):
            static = grid.blocked_by_static_geometry(goal[0], goal[1])
            if static:
                return self._fail(
                    PathStatus.UNREACHABLE,
                    f"goal ({goal[0]:.3f}, {goal[1]:.3f}) lies in static map geometry",
                    UnreachableReason.BLOCKED_GOAL,
                )
            return self._fail(
                PathStatus.UNREACHABLE,
                f"goal ({goal[0]:.3f}, {goal[1]:.3f}) is inside the "
                f"{grid.inflation_m:.3f} m planning inflation",
                UnreachableReason.INSUFFICIENT_CLEARANCE,
            )

        goal_cell = grid.cell_of(goal[0], goal[1])
        if start_cell == goal_cell:
            self._plan_version += 1
            return self._succeed(
                waypoints=(start_xy, (goal[0], goal[1])),
                length_m=math.dist(start_xy, (goal[0], goal[1])),
                cost_s=math.dist(start_xy, (goal[0], goal[1])) * self._turn_cost.seconds_per_metre,
                expansions=0,
            )

        cells, cost, expansions, turns, exhausted = self._search(grid, start_cell, start.theta, goal_cell)
        if cells is None:
            if exhausted:
                return self._fail(
                    PathStatus.SEARCH_EXHAUSTED,
                    f"expansion budget {self._max_expansions} exhausted after "
                    f"{expansions} expansions without reaching the goal cell",
                    UnreachableReason.SEARCH_BUDGET_EXHAUSTED,
                    expansions=expansions,
                )
            return self._fail(
                PathStatus.UNREACHABLE,
                (
                    f"no free chain connects ({start.x:.3f}, {start.y:.3f}) to "
                    f"({goal[0]:.3f}, {goal[1]:.3f}) on the inflated grid"
                ),
                UnreachableReason.NO_CONNECTION,
                expansions=expansions,
            )
        waypoints = _cells_to_waypoints(grid, cells, start_xy, (goal[0], goal[1]))
        length_m = sum(math.dist(waypoints[k], waypoints[k + 1]) for k in range(len(waypoints) - 1))
        return self._succeed(
            waypoints=waypoints,
            length_m=length_m,
            cost_s=cost,
            expansions=expansions,
            turn_count=turns,
        )

    def _succeed(
        self,
        *,
        waypoints: tuple[Vec2, ...],
        length_m: float,
        cost_s: float,
        expansions: int,
        turn_count: int = 0,
    ) -> PathResult:
        self._plan_version += 1
        result = PathResult(
            status=PathStatus.OK,
            waypoints=waypoints,
            length_m=length_m,
            cost_s=cost_s,
            turn_count=turn_count,
            expansions=expansions,
            version=self._plan_version,
        )
        self._last = result
        return result

    def _fail(
        self,
        status: PathStatus,
        reason: str,
        unreachable_reason: UnreachableReason | None = None,
        *,
        expansions: int = 0,
    ) -> PathResult:
        result = PathResult(
            status=status,
            reason=reason,
            unreachable_reason=unreachable_reason,
            expansions=expansions,
        )
        self._last = result
        return result

    def _search(
        self,
        grid: OccupancyGrid,
        start_cell: tuple[int, int],
        start_theta: float,
        goal_cell: tuple[int, int],
    ) -> tuple[tuple[tuple[int, int], ...] | None, float, int, int, bool]:
        """A* over ``(cell, heading class)``.

        Returns ``(cells, cost, expansions, lattice_turns, budget_exhausted)``.
        ``budget_exhausted`` separates "the search ran out of room" from "there is no
        path"; collapsing the two would report a resource limit as a geometric
        fact. ``lattice_turns`` counts heading-class changes the search actually
        made. It deliberately does *not* count the two sub-cell corrections where
        the exact requested start and goal are spliced onto the cell-centre
        polyline: those are corrections, not turns the planner chose, and counting
        them would make ``turn_count`` disagree with the turn cost actually paid.
        """
        nx, ny = grid.shape
        res = grid.resolution
        tc = self._turn_cost
        forbidden = self._forbidden
        start_flat = start_cell[0] * ny + start_cell[1]
        goal_flat = goal_cell[0] * ny + goal_cell[1]
        start_heading = _nearest_heading_class(start_theta)

        counter = 0
        # Node keys encode (cell flat, heading class) as flat * 8 + heading class.
        start_key = start_flat * _HEADING_CLASSES + start_heading
        start_h = _octile_cells(start_cell, goal_cell) * res * tc.seconds_per_metre
        heap: list[tuple[float, float, int, int]] = [(start_h, start_h, 0, start_key)]
        best: dict[int, float] = {start_key: 0.0}
        parent: dict[int, int] = {}
        closed: set[int] = set()
        expansions = 0
        goal_key: int | None = None

        while heap:
            _f, _h, _order, key = heapq.heappop(heap)
            if key in closed:
                continue
            closed.add(key)
            # The heap orders on (f, h, insertion_index); the accumulated cost is
            # read back from ``best`` rather than unpacked from the tuple, because
            # the tuple deliberately does not carry g.
            g = best[key]
            if key // _HEADING_CLASSES == goal_flat:
                goal_key = key
                break
            if expansions >= self._max_expansions:
                return None, g, expansions, 0, True
            expansions += 1
            flat, heading = divmod(key, _HEADING_CLASSES)
            ci, cj = divmod(flat, ny)
            from_heading = _HEADINGS[heading]
            for idx, (di, dj, dist_cells) in enumerate(_MOVES):
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
                    # No corner cutting: a diagonal through a blocked corner is
                    # not drivable for a differential drive with a non-zero body,
                    # and allowing it would make every "8-connected" claim here
                    # quietly false in exactly the narrow-aisle case we care about.
                    continue
                n_flat = ni * ny + nj
                if (flat, n_flat) in forbidden:
                    continue
                to_heading = _HEADINGS[idx]
                step = dist_cells * res * tc.seconds_per_metre
                step += abs(angle_difference(from_heading, to_heading)) * tc.seconds_per_radian
                n_key = n_flat * _HEADING_CLASSES + idx
                ng = g + step
                known = best.get(n_key)
                if known is not None and known <= ng:
                    continue
                best[n_key] = ng
                parent[n_key] = key
                counter += 1
                h = _octile_cells((ni, nj), goal_cell) * res * tc.seconds_per_metre
                heapq.heappush(heap, (ng + h, h, counter, n_key))

        if goal_key is None:
            return None, 0.0, expansions, 0, False
        chain: list[int] = []
        node = goal_key
        while node != start_key:
            chain.append(node)
            node = parent[node]
        chain.append(start_key)
        chain.reverse()
        cells: list[tuple[int, int]] = []
        turns = 0
        previous_heading: int | None = None
        for key in chain:
            flat, heading = divmod(key, _HEADING_CLASSES)
            cells.append((flat // ny, flat % ny))
            if previous_heading is not None and heading != previous_heading:
                turns += 1
            previous_heading = heading
        return tuple(cells), best[goal_key], expansions, turns, False


def _octile_cells(a: tuple[int, int], b: tuple[int, int]) -> float:
    return octile_distance_m(float(abs(a[0] - b[0])), float(abs(a[1] - b[1])))


def _nearest_heading_class(theta: float) -> int:
    best = 0
    best_delta = math.inf
    for idx, heading in enumerate(_HEADINGS):
        delta = abs(angle_difference(theta, heading))
        if delta < best_delta - 1e-12:
            best_delta = delta
            best = idx
    return best


def _count_turns(waypoints: Sequence[Vec2]) -> int:
    if len(waypoints) < 3:
        return 0
    turns = 0
    seg_prev = math.atan2(waypoints[1][1] - waypoints[0][1], waypoints[1][0] - waypoints[0][0])
    for k in range(1, len(waypoints) - 1):
        seg = math.atan2(waypoints[k + 1][1] - waypoints[k][1], waypoints[k + 1][0] - waypoints[k][0])
        if abs(angle_difference(seg, seg_prev)) > 1e-6:
            turns += 1
        seg_prev = seg
    return turns


def _cells_to_waypoints(
    grid: OccupancyGrid,
    cells: Sequence[tuple[int, int]],
    start_xy: Vec2,
    goal_xy: Vec2,
) -> tuple[Vec2, ...]:
    """Snap interior cells to centres but keep the two requested endpoints exact."""
    interior = [grid.cell_centre(i, j) for i, j in cells[1:-1]]
    raw: tuple[Vec2, ...] = (start_xy, *interior, goal_xy)
    out: list[Vec2] = [raw[0]]
    for point in raw[1:]:
        if math.dist(point, out[-1]) > 1e-9:
            out.append(point)
    return tuple(out)


def _forbidden_transitions(
    grid: OccupancyGrid, directed_routes: Sequence[RouteEdge]
) -> frozenset[tuple[int, int]]:
    """Cell-pair transitions the map's one-way edges forbid.

    Honest scope: this forbids the reverse of the **exact declared cell pair**
    only, because a ``RouteEdge`` says nothing else. It is the topological hint
    the map describes itself as, not a whole one-way network, and it must not be
    described as one.
    """
    if not directed_routes:
        return frozenset()
    ny = grid.shape[1]
    forbidden: set[tuple[int, int]] = set()
    for edge in directed_routes:
        if not edge.one_way:
            continue
        fi, fj = grid.cell_of(edge.from_pose.x, edge.from_pose.y)
        ti, tj = grid.cell_of(edge.to_pose.x, edge.to_pose.y)
        forbidden.add((ti * ny + tj, fi * ny + fj))
    return frozenset(forbidden)


def planner_from_map(
    warehouse_map: WarehouseMap,
    footprint: Footprint,
    *,
    zones_blocking: bool = False,
    max_linear_mps: float = 0.4,
    max_angular_radps: float = 1.0,
    turn_weight: float = 1.0,
    max_expansions: int = 200_000,
    current_pose: Pose2 | None = None,
) -> AStarPlanner:
    """Convenience factory. Reads only the immutable map and one footprint."""
    grid = OccupancyGrid.from_map(
        warehouse_map, footprint.clearance_radius_m(), zones_blocking=zones_blocking
    )
    return AStarPlanner(
        grid,
        turn_cost=TurnCost(
            max_linear_mps=max_linear_mps,
            max_angular_radps=max_angular_radps,
            turn_weight=turn_weight,
        ),
        directed_routes=warehouse_map.directed_routes,
        max_expansions=max_expansions,
        current_pose=current_pose,
    )

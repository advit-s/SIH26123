"""Path geometry: smoothing, measurement, and the declared zone/stop-line facts.

Everything in this module is *derived from the plan and the immutable map* by
local geometry. Nothing here consults another robot's state.

Two honesty notes that travel with every number produced here:

* ``length_m`` and ``estimated_duration_s`` are **configured estimates**. The
  duration is length divided by the declared maximum speed plus one rotation
  time per heading change. It contains no actuator lag, no tracking error and no
  queueing, so it is an optimistic lower bound and must be labelled as such
  wherever it is displayed.
* ``zones_touched`` and ``stop_lines_crossed`` are geometric containment tests on
  the inflated grid, computed in path order. They describe *where the path goes*;
  they grant nothing. Authority to enter a zone comes from the grant protocol
  (AGENTS.md rule 6) and every command still passes the safety gate (rule 7).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.geometry import segment_intersects_segment
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import Footprint
from niharamesh.domain.units import angle_difference
from niharamesh.planning.grid import OccupancyGrid

__all__ = [
    "PathPlan",
    "Vec2",
    "build_plan",
    "estimate_duration_s",
    "path_length_m",
    "smooth",
    "stop_lines_crossed",
    "turn_count",
    "zones_touched",
]

Vec2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class PathPlan:
    """A planned route plus the geometric facts about it.

    ``zones_touched`` is ordered by first entry along the path and deduplicated.
    ``stop_line_id`` is the *first* stop line the path crosses in path order;
    :func:`stop_lines_crossed` returns the full ordered list when a caller needs
    every one (the velocity profile brakes before each of them).
    """

    waypoints: tuple[Vec2, ...]
    length_m: float
    estimated_duration_s: float
    turn_count: int
    version: int
    zones_touched: tuple[str, ...]
    stop_line_id: str | None = None

    def __post_init__(self) -> None:
        if not self.waypoints:
            raise ValueError("a PathPlan must contain at least one waypoint")
        for name in ("length_m", "estimated_duration_s"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"PathPlan.{name} must be finite")

    @property
    def start(self) -> Vec2:
        return self.waypoints[0]

    @property
    def goal(self) -> Vec2:
        return self.waypoints[-1]


def path_length_m(waypoints: Sequence[Vec2]) -> float:
    return sum(math.dist(waypoints[k], waypoints[k + 1]) for k in range(len(waypoints) - 1))


def turn_count(waypoints: Sequence[Vec2]) -> int:
    """Number of direction changes above ``1e-6`` rad."""
    if len(waypoints) < 3:
        return 0
    turns = 0
    previous = _heading_of(waypoints[0], waypoints[1])
    for k in range(1, len(waypoints) - 1):
        heading = _heading_of(waypoints[k], waypoints[k + 1])
        if abs(angle_difference(heading, previous)) > 1e-6:
            turns += 1
        previous = heading
    return turns


def estimate_duration_s(
    waypoints: Sequence[Vec2],
    *,
    max_linear_mps: float,
    max_angular_radps: float,
    turn_weight: float = 1.0,
) -> float:
    """Configured duration estimate: travel at the speed limit plus rotations.

    Every term is a declared limit divided into the geometry. There is no
    measured value anywhere in this function, and no allowance for acceleration,
    braking, tracking error or waiting - so the result is an optimistic bound and
    is named ``estimated_`` everywhere it appears.
    """
    if max_linear_mps <= 0.0 or max_angular_radps <= 0.0:
        raise ValueError("declared actuator limits must be positive")
    travel = path_length_m(waypoints) / max_linear_mps
    if len(waypoints) < 3:
        return travel
    rotation = 0.0
    previous = _heading_of(waypoints[0], waypoints[1])
    for k in range(1, len(waypoints) - 1):
        heading = _heading_of(waypoints[k], waypoints[k + 1])
        rotation += abs(angle_difference(heading, previous))
        previous = heading
    return travel + rotation * turn_weight / max_angular_radps


def zones_touched(
    waypoints: Sequence[Vec2],
    warehouse_map: WarehouseMap,
    *,
    step_m: float = 0.05,
) -> tuple[str, ...]:
    """Zone ids whose ``protected_bounds`` the path enters, in path order."""
    order: list[str] = []
    seen: set[str] = set()
    for point in _sample(waypoints, step_m):
        for zone in warehouse_map.zones:
            x0, y0, x1, y1 = zone.protected_bounds
            if zone.id in seen:
                continue
            if x0 <= point[0] <= x1 and y0 <= point[1] <= y1:
                seen.add(zone.id)
                order.append(zone.id)
    return tuple(order)


def stop_lines_crossed(
    waypoints: Sequence[Vec2],
    warehouse_map: WarehouseMap,
) -> tuple[str, ...]:
    """Stop-line ids the polyline crosses, in path order, deduplicated.

    Geometric only. Crossing a line without the named authority is a violation
    the *evaluator* detects independently; this function only reports which lines
    a route runs over.
    """
    order: list[str] = []
    for line in warehouse_map.stop_lines:
        a, b = line.start, line.end
        for k in range(len(waypoints) - 1):
            if segment_intersects_segment(waypoints[k], waypoints[k + 1], a, b):
                order.append(line.id)
                break
    return tuple(order)


def smooth(
    waypoints: Sequence[Vec2],
    grid: OccupancyGrid,
    footprint: Footprint,
) -> tuple[Vec2, ...]:
    """Line-of-sight string pulling on the inflated grid.

    Greedy and deterministic: from each anchor, the *furthest* later waypoint
    with a free straight line to it becomes the next anchor. Because the
    line-of-sight test runs on the same inflated mask the search used, a smoothed
    path cannot enter a cell the search refused to enter - the discrete test is
    what guarantees that, so it is re-checked here rather than assumed.

    Raises :class:`ValueError` when *grid* was not inflated enough for
    *footprint*: smoothing an under-inflated grid would produce a route the
    robot's own body cannot fit through, which is worse than no smoothing.
    """
    if not grid.serves(footprint):
        raise ValueError(
            f"smooth() needs a grid inflated for {footprint.clearance_radius_m():.3f} m; "
            f"this one is {grid.inflation_m:.3f} m"
        )
    points = tuple(waypoints)
    if len(points) <= 2:
        return points
    out: list[Vec2] = [points[0]]
    anchor = 0
    while anchor < len(points) - 1:
        chosen: int | None = None
        for candidate in range(len(points) - 1, anchor, -1):
            if grid.segment_free(points[anchor], points[candidate]):
                chosen = candidate
                break
        if chosen is None:
            raise ValueError(
                "string pulling lost line of sight on the inflated grid; refusing to "
                "invent a segment that the search would not have accepted"
            )
        out.append(points[chosen])
        anchor = chosen
    return tuple(out)


def build_plan(
    waypoints: Sequence[Vec2],
    warehouse_map: WarehouseMap,
    actuator_model: ActuatorModel,
    *,
    version: int = 0,
) -> PathPlan:
    """Measure a waypoint polyline into a :class:`PathPlan`."""
    points = tuple(waypoints)
    if not points:
        raise ValueError("cannot build a PathPlan from an empty waypoint tuple")
    crossed = stop_lines_crossed(points, warehouse_map)
    return PathPlan(
        waypoints=points,
        length_m=path_length_m(points),
        estimated_duration_s=estimate_duration_s(
            points,
            max_linear_mps=actuator_model.max_linear_mps,
            max_angular_radps=actuator_model.max_angular_radps,
        ),
        turn_count=turn_count(points),
        version=version,
        zones_touched=zones_touched(points, warehouse_map),
        stop_line_id=crossed[0] if crossed else None,
    )


def _heading_of(a: Vec2, b: Vec2) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _sample(waypoints: Sequence[Vec2], step_m: float) -> tuple[Vec2, ...]:
    """Points along the polyline at most ``step_m`` apart, including vertices."""
    if step_m <= 0.0:
        raise ValueError("step_m must be positive")
    out: list[Vec2] = [waypoints[0]]
    for k in range(len(waypoints) - 1):
        ax, ay = waypoints[k]
        bx, by = waypoints[k + 1]
        length = math.hypot(bx - ax, by - ay)
        steps = max(1, math.ceil(length / step_m))
        for s in range(1, steps + 1):
            t = s / steps
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return tuple(out)

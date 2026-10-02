"""Local planner behaviour: routes, explicit failures, determinism.

Every assertion here is about behaviour a reviewer can check by reading the
result: no screenshots, no golden files, no tolerance on a determinism claim.
"""

from __future__ import annotations

import math

import pytest

from niharamesh.domain.map import (
    MapBoundary,
    Obstacle,
    ObstacleKind,
    RouteEdge,
    WarehouseMap,
)
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.planning.astar import (
    AStarPlanner,
    PathStatus,
    TurnCost,
    UnreachableReason,
)
from niharamesh.planning.grid import GridTooLargeError, OccupancyGrid

SMALL_FOOTPRINT = Footprint(length_m=0.6, width_m=0.4, turning_radius_m=0.25)
FAT_FOOTPRINT = Footprint(length_m=1.2, width_m=1.0, turning_radius_m=0.5)


def empty_map(*, resolution_m: float = 0.1) -> WarehouseMap:
    return WarehouseMap(
        map_id="test-empty",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=20.0, max_y=10.0),
        obstacles=(),
        grid_resolution_m=resolution_m,
        nominal_aisle_width_m=1.4,
    )


def shelf_map() -> WarehouseMap:
    """A shelf wall across the middle with a passage only along the top."""
    return WarehouseMap(
        map_id="test-shelf",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=20.0, max_y=10.0),
        obstacles=(
            Obstacle(
                id="shelf-1",
                kind=ObstacleKind.SHELF,
                pose=Pose2(x=10.0, y=3.0, theta=0.0),
                length_m=1.0,
                width_m=6.0,
            ),
        ),
        grid_resolution_m=0.1,
        nominal_aisle_width_m=1.4,
    )


def planner_for(warehouse_map: WarehouseMap, footprint: Footprint = SMALL_FOOTPRINT) -> AStarPlanner:
    grid = OccupancyGrid.from_map(warehouse_map, footprint.clearance_radius_m())
    return AStarPlanner(
        grid,
        turn_cost=TurnCost(max_linear_mps=0.4, max_angular_radps=1.0),
        directed_routes=warehouse_map.directed_routes,
    )


def test_straight_corridor_route_is_straight() -> None:
    planner = planner_for(empty_map())
    start = Pose2(x=2.0, y=5.0, theta=0.0)
    planner.set_current_pose(start)

    result = planner.plan_detailed((17.0, 5.0), SMALL_FOOTPRINT, start=start)

    assert result.status is PathStatus.OK, result.reason
    assert result.waypoints[0] == (2.0, 5.0)
    assert result.waypoints[-1] == (17.0, 5.0)
    assert result.turn_count == 0
    assert result.length_m == pytest.approx(15.0, abs=0.05)
    assert result.cost_s == pytest.approx(15.0 / 0.4, rel=1e-9)
    # Interior waypoints are cell centres, so they sit within half a cell of the
    # corridor centreline rather than exactly on it.
    for point in result.waypoints[1:-1]:
        assert point[1] == pytest.approx(5.0, abs=0.5 * SMALL_FOOTPRINT.clearance_radius_m())


def test_eight_connected_path_avoids_obstacles() -> None:
    warehouse_map = shelf_map()
    planner = planner_for(warehouse_map)
    grid = planner.grid
    start = Pose2(x=2.0, y=3.0, theta=0.0)
    planner.set_current_pose(start)

    result = planner.plan_detailed((17.0, 3.0), SMALL_FOOTPRINT, start=start)

    assert result.status is PathStatus.OK, result.reason
    assert result.waypoints[0] == (2.0, 3.0)
    assert result.waypoints[-1] == (17.0, 3.0)
    # It must go round the shelf, so it has to climb above the inflated obstacle.
    assert max(point[1] for point in result.waypoints) > 6.0
    for x, y in result.waypoints:
        assert not grid.blocked(x, y), f"smooth-visible blocked cell at {(x, y)}"
    # Every point along every segment is free too, not only the waypoints.
    for index in range(len(result.waypoints) - 1):
        assert grid.segment_free(result.waypoints[index], result.waypoints[index + 1])


def test_unreachable_goal_returns_explicit_status_and_no_path() -> None:
    warehouse_map = shelf_map()
    planner = planner_for(warehouse_map)
    start = Pose2(x=2.0, y=8.0, theta=0.0)
    planner.set_current_pose(start)

    result = planner.plan_detailed((10.0, 2.0), SMALL_FOOTPRINT, start=start)

    assert result.status is PathStatus.UNREACHABLE
    assert result.unreachable_reason is UnreachableReason.BLOCKED_GOAL
    assert "goal" in result.reason
    # A partial path must never be returned as a plan.
    assert result.waypoints == ()
    assert result.length_m == 0.0
    assert planner.plan((10.0, 2.0), SMALL_FOOTPRINT) is None
    assert planner.last_result.unreachable_reason is UnreachableReason.BLOCKED_GOAL


def test_blocked_start_and_blocked_goal_are_distinguished() -> None:
    warehouse_map = shelf_map()
    blocked_start = planner_for(warehouse_map)
    result_start = blocked_start.plan_detailed(
        (17.0, 3.0), SMALL_FOOTPRINT, start=Pose2(x=10.0, y=2.0, theta=0.0)
    )
    assert result_start.status is PathStatus.UNREACHABLE
    assert result_start.unreachable_reason is UnreachableReason.BLOCKED_START
    assert "start" in result_start.reason

    blocked_goal = planner_for(warehouse_map)
    result_goal = blocked_goal.plan_detailed(
        (10.0, 2.0), SMALL_FOOTPRINT, start=Pose2(x=2.0, y=8.0, theta=0.0)
    )
    assert result_goal.unreachable_reason is UnreachableReason.BLOCKED_GOAL

    assert result_start.unreachable_reason is not result_goal.unreachable_reason


def test_goal_inside_robot_inflation_is_insufficient_clearance_not_blocked_goal() -> None:
    """The distinction a reviewer cares about: map problem vs footprint problem."""
    warehouse_map = shelf_map()
    fat = planner_for(warehouse_map, FAT_FOOTPRINT)
    # 0.7 m clear of the shelf face: free in the map, blocked for a 1.2 x 1.0
    # robot whose 0.781 m planning inflation reaches it.
    result = fat.plan_detailed((8.8, 3.0), FAT_FOOTPRINT, start=Pose2(x=2.0, y=8.0, theta=0.0))
    assert result.status is PathStatus.UNREACHABLE
    assert result.unreachable_reason is UnreachableReason.INSUFFICIENT_CLEARANCE

    # The same point is perfectly reachable for the small footprint.
    small = planner_for(warehouse_map, SMALL_FOOTPRINT)
    ok = small.plan_detailed((8.8, 3.0), SMALL_FOOTPRINT, start=Pose2(x=2.0, y=8.0, theta=0.0))
    assert ok.status is PathStatus.OK, ok.reason


def test_grid_that_does_not_serve_footprint_is_refused() -> None:
    planner = planner_for(empty_map())
    result = planner.plan_detailed((17.0, 5.0), FAT_FOOTPRINT, start=Pose2(x=2.0, y=5.0, theta=0.0))
    assert result.status is PathStatus.INVALID_REQUEST
    assert "does not serve" in result.reason


def test_planning_is_deterministic() -> None:
    warehouse_map = shelf_map()
    start = Pose2(x=2.0, y=3.0, theta=math.pi / 2.0)

    first = planner_for(warehouse_map).plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, start=start)
    second = planner_for(warehouse_map).plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, start=start)

    assert first.status is PathStatus.OK
    assert first.waypoints == second.waypoints
    assert first.length_m == second.length_m
    assert first.cost_s == second.cost_s
    assert first.expansions == second.expansions
    assert first.turn_count == second.turn_count


def test_repeated_plans_in_one_planner_are_identical() -> None:
    planner = planner_for(shelf_map())
    start = Pose2(x=2.0, y=3.0, theta=0.0)
    planner.set_current_pose(start)
    first = planner.plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, start=start)
    second = planner.plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, start=start)
    assert first.waypoints == second.waypoints
    assert planner.plan_version == 2


def test_turn_cost_is_on_the_same_seconds_scale_as_distance() -> None:
    """A straight metre costs ``1 / v`` seconds whatever the turn weight is."""
    light = TurnCost(max_linear_mps=0.4, max_angular_radps=1.0, turn_weight=1.0)
    heavy = TurnCost(max_linear_mps=0.4, max_angular_radps=1.0, turn_weight=4.0)
    assert light.seconds_per_metre == pytest.approx(2.5)
    assert light.seconds_per_radian == pytest.approx(1.0)
    assert heavy.seconds_per_metre == pytest.approx(2.5)
    assert heavy.seconds_per_radian == pytest.approx(4.0)
    # The octile bound is the pure distance lower bound, so it stays admissible.
    assert light.heuristic_seconds(2.0, 1.0) == pytest.approx(2.5 * (2.0 + math.sqrt(2.0) - 1.0))
    assert light.heuristic_seconds(1.0, 0.0) == pytest.approx(2.5)


def test_turn_weight_changes_the_route_and_stays_deterministic() -> None:
    warehouse_map = shelf_map()
    start = Pose2(x=2.0, y=3.0, theta=0.0)
    goal = (17.0, 8.0)

    straight_first = planner_for(warehouse_map)
    curved_first = planner_for(warehouse_map)
    straight = straight_first.plan_detailed(goal, SMALL_FOOTPRINT, start=start)
    curved = curved_first.plan_detailed(goal, SMALL_FOOTPRINT, start=start)
    assert straight.waypoints == curved.waypoints
    assert straight.cost_s == curved.cost_s
    assert straight.cost_s > straight.length_m / 0.4  # the turn term is really charged


def test_search_budget_exhaustion_is_not_reported_as_unreachable() -> None:
    warehouse_map = shelf_map()
    grid = OccupancyGrid.from_map(warehouse_map, SMALL_FOOTPRINT.clearance_radius_m())
    starved = AStarPlanner(grid, max_expansions=1)
    result = starved.plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, start=Pose2(x=2.0, y=3.0, theta=0.0))
    assert result.status is PathStatus.SEARCH_EXHAUSTED
    assert result.unreachable_reason is UnreachableReason.SEARCH_BUDGET_EXHAUSTED
    assert result.waypoints == ()


def test_blocked_aware_plan_does_not_mutate_the_static_grid() -> None:
    warehouse_map = shelf_map()
    planner = planner_for(warehouse_map)
    start = Pose2(x=2.0, y=8.0, theta=0.0)
    planner.set_current_pose(start)
    # A claim wall over the passage from y=4 to y=9, leaving a gap at the top.
    gap = [(10.0, y, 1.0) for y in (5.0, 6.0, 7.0, 8.0)]
    # A claim wall that seals the passage completely.
    seal = [*gap, (10.0, 9.0, 1.0)]

    clear = planner.blocked_aware_plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, (), start=start)
    detour = planner.blocked_aware_plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, gap, start=start)
    walled = planner.blocked_aware_plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, seal, start=start)
    assert clear.status is PathStatus.OK, clear.reason
    # The gap forces a real detour, not a cosmetic change.
    assert detour.status is PathStatus.OK, detour.reason
    assert detour.length_m > clear.length_m
    assert detour.cost_s > clear.cost_s
    assert max(point[1] for point in detour.waypoints) > max(point[1] for point in clear.waypoints)
    # Sealing it is reported honestly rather than producing a partial path.
    assert walled.status is PathStatus.UNREACHABLE
    assert walled.unreachable_reason in (
        UnreachableReason.NO_CONNECTION,
        UnreachableReason.INSUFFICIENT_CLEARANCE,
    )
    assert walled.waypoints == ()
    # The claim did not become map geometry: the same goal plans the same way again.
    again = planner.blocked_aware_plan_detailed((17.0, 8.0), SMALL_FOOTPRINT, (), start=start)
    assert again.waypoints == clear.waypoints
    assert not planner.grid.blocked(10.0, 8.0)


def test_grid_free_area_and_inflation_diagnostics() -> None:
    warehouse_map = shelf_map()
    grid = OccupancyGrid.from_map(warehouse_map, SMALL_FOOTPRINT.clearance_radius_m())
    assert grid.resolution == pytest.approx(0.1)
    assert grid.serves(SMALL_FOOTPRINT)
    assert not grid.serves(FAT_FOOTPRINT)
    assert grid.blocked(10.0, 2.0)
    assert grid.blocked_by_static_geometry(10.0, 2.0)
    assert grid.is_free(2.0, 8.0)
    # Inflation, not geometry, removes the strip next to the shelf.
    assert grid.blocked(9.3, 3.0)
    assert not grid.blocked_by_static_geometry(9.3, 3.0)
    assert grid.cells_inflated_count > 0
    assert grid.cells_blocked_count >= grid.cells_inflated_count
    # Outside the grid rectangle is blocked, not free.
    assert grid.blocked(-5.0, 5.0)
    assert grid.blocked(500.0, 5.0)


def test_nearest_free_and_segment_free() -> None:
    warehouse_map = shelf_map()
    grid = OccupancyGrid.from_map(warehouse_map, SMALL_FOOTPRINT.clearance_radius_m())
    nearest = grid.nearest_free(10.0, 2.0)
    assert grid.is_free(*nearest)
    assert math.dist(nearest, (10.0, 2.0)) > 0.0
    assert not grid.segment_free((2.0, 3.0), (17.0, 3.0))
    assert grid.segment_free((2.0, 8.0), (17.0, 8.0))


def _strip(nx: int) -> OccupancyGrid:
    """A one-cell-high synthetic strip, built directly so the directed-route rule
    can be tested without a map whose geometry happens to conspire with it."""
    return OccupancyGrid(
        origin_x=0.0,
        origin_y=0.0,
        resolution=1.0,
        nx=nx,
        ny=1,
        blocked=bytearray(nx),
        static_blocked=bytearray(nx),
        inflation_m=0.1,
        zones_blocking=False,
        map_id=f"synthetic-strip-{nx}",
        obstacle_count=0,
    )


def _one_way(x0: float, x1: float) -> tuple[RouteEdge, ...]:
    return (
        RouteEdge(
            id="e1",
            from_pose=Pose2(x=x0, y=0.5, theta=0.0),
            to_pose=Pose2(x=x1, y=0.5, theta=0.0),
            one_way=True,
            cost_m=1.0,
        ),
    )


TINY_FOOTPRINT = Footprint(length_m=0.1, width_m=0.1, turning_radius_m=0.05)


def test_directed_route_forbids_the_declared_reverse_exactly() -> None:
    """A five-cell strip has exactly one route between its first two cells, so
    forbidding that single transition makes the reverse genuinely unreachable. The
    forward direction is asserted separately, so a rule that forbade the pair
    outright would fail rather than pass."""
    planner = AStarPlanner(
        _strip(5),
        turn_cost=TurnCost(max_linear_mps=1.0, max_angular_radps=1.0),
        directed_routes=_one_way(0.5, 1.5),
    )
    forward = planner.plan_detailed((1.5, 0.5), TINY_FOOTPRINT, start=Pose2(x=0.5, y=0.5, theta=0.0))
    backward = planner.plan_detailed((0.5, 0.5), TINY_FOOTPRINT, start=Pose2(x=1.5, y=0.5, theta=0.0))
    assert forward.status is PathStatus.OK, forward.reason
    assert forward.waypoints == ((0.5, 0.5), (1.5, 0.5))
    assert backward.status is PathStatus.UNREACHABLE
    assert backward.unreachable_reason is UnreachableReason.NO_CONNECTION
    assert backward.waypoints == ()


def test_directed_route_restriction_does_not_leak_to_neighbouring_pairs() -> None:
    planner = AStarPlanner(
        _strip(4),
        turn_cost=TurnCost(max_linear_mps=1.0, max_angular_radps=1.0),
        directed_routes=_one_way(0.5, 1.5),
    )
    # Cells 2 and 3 are a *different* pair and stay available in both directions.
    forward = planner.plan_detailed((3.5, 0.5), TINY_FOOTPRINT, start=Pose2(x=2.5, y=0.5, theta=0.0))
    backward = planner.plan_detailed((2.5, 0.5), TINY_FOOTPRINT, start=Pose2(x=3.5, y=0.5, theta=0.0))
    assert forward.status is PathStatus.OK, forward.reason
    assert backward.status is PathStatus.OK, backward.reason


def test_non_one_way_edge_imposes_no_restriction() -> None:
    edge = RouteEdge(
        id="e1",
        from_pose=Pose2(x=0.5, y=0.5, theta=0.0),
        to_pose=Pose2(x=1.5, y=0.5, theta=0.0),
        one_way=False,
        cost_m=1.0,
    )
    planner = AStarPlanner(
        _strip(3),
        turn_cost=TurnCost(max_linear_mps=1.0, max_angular_radps=1.0),
        directed_routes=(edge,),
    )
    backward = planner.plan_detailed((0.5, 0.5), TINY_FOOTPRINT, start=Pose2(x=1.5, y=0.5, theta=0.0))
    assert backward.status is PathStatus.OK, backward.reason


def test_grid_rejects_an_implausible_resolution_instead_of_exhausting_memory() -> None:
    huge = WarehouseMap(
        map_id="test-huge",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=500.0, max_y=500.0),
        grid_resolution_m=0.05,
    )
    with pytest.raises(GridTooLargeError):
        OccupancyGrid.from_map(huge, 0.3)

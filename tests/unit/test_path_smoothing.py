"""Path smoothing: never enters a blocked cell, and always shortens a zigzag."""

from __future__ import annotations

import math

import pytest

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.map import (
    MapBoundary,
    Obstacle,
    ObstacleKind,
    StopLine,
    WarehouseMap,
    Zone,
)
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.planning.astar import AStarPlanner, TurnCost
from niharamesh.planning.grid import OccupancyGrid
from niharamesh.planning.path import build_plan, smooth
from niharamesh.planning.velocity import velocity_profile

FOOTPRINT = Footprint(length_m=0.6, width_m=0.4, turning_radius_m=0.25)
FAT_FOOTPRINT = Footprint(length_m=1.2, width_m=1.0, turning_radius_m=0.5)
ACTUATOR = ActuatorModel()


def corridor_map() -> WarehouseMap:
    return WarehouseMap(
        map_id="test-corridor",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=12.0, max_y=6.0),
        obstacles=(
            Obstacle(
                id="pillar",
                kind=ObstacleKind.PILLAR,
                pose=Pose2(x=6.0, y=1.0, theta=0.0),
                length_m=0.6,
                width_m=0.6,
            ),
        ),
        grid_resolution_m=0.1,
        nominal_aisle_width_m=1.4,
    )


def grid_for(warehouse_map: WarehouseMap, footprint: Footprint = FOOTPRINT) -> OccupancyGrid:
    return OccupancyGrid.from_map(warehouse_map, footprint.clearance_radius_m())


def samples_along(
    waypoints: tuple[tuple[float, float], ...], spacing_m: float = 0.02
) -> tuple[tuple[float, float], ...]:
    """Densely sample the whole polyline, not only the waypoints."""
    out: list[tuple[float, float]] = []
    for k in range(len(waypoints) - 1):
        ax, ay = waypoints[k]
        bx, by = waypoints[k + 1]
        steps = max(1, math.ceil(math.dist((ax, ay), (bx, by)) / spacing_m))
        for s in range(steps + 1):
            t = s / steps
            out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return tuple(out)


def test_smoothing_never_enters_a_blocked_cell() -> None:
    warehouse_map = corridor_map()
    grid = grid_for(warehouse_map)
    planner = AStarPlanner(grid, turn_cost=TurnCost(max_linear_mps=0.4, max_angular_radps=1.0))
    start = Pose2(x=1.0, y=4.5, theta=0.0)
    result = planner.plan_detailed((11.0, 4.5), FOOTPRINT, start=start)
    assert result.status.value == "ok", result.reason

    smoothed = smooth(result.waypoints, grid, FOOTPRINT)

    for point in samples_along(smoothed):
        assert grid.is_free(*point), f"smoothed path entered a blocked cell at {point}"
    assert smoothed[0] == result.waypoints[0]
    assert smoothed[-1] == result.waypoints[-1]


def test_smoothing_shortens_a_zigzag() -> None:
    warehouse_map = corridor_map()
    grid = grid_for(warehouse_map)
    planner = AStarPlanner(grid, turn_cost=TurnCost(max_linear_mps=0.4, max_angular_radps=1.0))
    start = Pose2(x=1.0, y=4.5, theta=0.0)
    raw = planner.plan_detailed((11.0, 4.5), FOOTPRINT, start=start)
    assert raw.status.value == "ok", raw.reason
    # A deliberate zigzag inside clear space, well away from the pillar.
    zigzag: tuple[tuple[float, float], ...] = (
        (2.0, 5.2),
        (2.5, 4.8),
        (3.0, 5.2),
        (3.5, 4.8),
        (4.0, 5.2),
        (4.5, 4.8),
        (5.0, 5.2),
    )
    assert all(grid.is_free(*point) for point in zigzag)

    smoothed = smooth(zigzag, grid, FOOTPRINT)

    assert len(smoothed) == 2
    assert smoothed == ((2.0, 5.2), (5.0, 5.2))
    polyline = sum(math.dist(zigzag[k], zigzag[k + 1]) for k in range(len(zigzag) - 1))
    assert math.dist(smoothed[0], smoothed[1]) < polyline
    for point in samples_along(smoothed):
        assert grid.is_free(*point)


def test_smoothing_is_deterministic() -> None:
    warehouse_map = corridor_map()
    grid = grid_for(warehouse_map)
    planner = AStarPlanner(grid, turn_cost=TurnCost(max_linear_mps=0.4, max_angular_radps=1.0))
    start = Pose2(x=1.0, y=4.5, theta=0.0)
    raw = planner.plan_detailed((11.0, 4.5), FOOTPRINT, start=start)
    assert raw.status.value == "ok"
    first = smooth(raw.waypoints, grid, FOOTPRINT)
    second = smooth(raw.waypoints, grid, FOOTPRINT)
    assert first == second


def test_smoothing_refuses_a_grid_that_does_not_serve_the_footprint() -> None:
    warehouse_map = corridor_map()
    grid = grid_for(warehouse_map)
    with pytest.raises(ValueError, match="needs a grid inflated"):
        smooth(((1.0, 4.5), (11.0, 4.5)), grid, FAT_FOOTPRINT)


def test_smoothing_leaves_short_paths_alone() -> None:
    grid = grid_for(corridor_map())
    pair = ((1.0, 4.5), (2.0, 4.5))
    assert smooth(pair, grid, FOOTPRINT) == pair
    single = ((1.0, 4.5),)
    assert smooth(single, grid, FOOTPRINT) == single


def _mapped_map() -> WarehouseMap:
    return WarehouseMap(
        map_id="test-mapped",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=12.0, max_y=6.0),
        zones=(
            Zone(
                id="aisle-a",
                kind="corridor",
                protected_origin=(5.0, 4.0),
                protected_extent=(2.0, 1.0),
                entry_pose=Pose2(x=5.0, y=4.5, theta=0.0),
                exit_pose=Pose2(x=7.0, y=4.5, theta=0.0),
            ),
        ),
        stop_lines=(
            StopLine(
                id="sl-a-in",
                zone_id="aisle-a",
                start=(5.0, 4.0),
                end=(5.0, 5.0),
            ),
        ),
        grid_resolution_m=0.1,
    )


def test_zones_touched_and_stop_lines_are_geometric_and_ordered() -> None:
    warehouse_map = _mapped_map()
    straight: tuple[tuple[float, float], ...] = ((1.0, 4.5), (11.0, 4.5))
    plan = build_plan(straight, warehouse_map, ACTUATOR, version=7)
    assert plan.zones_touched == ("aisle-a",)
    assert plan.stop_line_id == "sl-a-in"
    assert plan.version == 7
    # Zones are reported in path order, deduplicated.
    zigzag: tuple[tuple[float, float], ...] = (
        (1.0, 4.5),
        (4.0, 4.5),
        (6.0, 4.5),
        (9.0, 4.5),
        (11.0, 4.5),
    )
    assert build_plan(zigzag, warehouse_map, ACTUATOR).zones_touched == ("aisle-a",)
    # A route that never enters the protected box touches nothing.
    below: tuple[tuple[float, float], ...] = ((1.0, 1.0), (11.0, 1.0))
    assert build_plan(below, warehouse_map, ACTUATOR).zones_touched == ()
    assert build_plan(below, warehouse_map, ACTUATOR).stop_line_id is None


def test_velocity_profile_marks_the_braking_onset_at_each_stop_line() -> None:
    warehouse_map = _mapped_map()
    plan = build_plan(((1.0, 4.5), (11.0, 4.5)), warehouse_map, ACTUATOR)
    start = Pose2(x=1.0, y=4.5, theta=0.0)
    profile = velocity_profile(plan, start, ACTUATOR, warehouse_map=warehouse_map)

    assert len(profile) == len(plan.waypoints)
    for waypoint in profile:
        assert 0.0 <= waypoint.target_speed_mps <= ACTUATOR.max_linear_mps
    brake_points = [index for index, w in enumerate(profile) if w.brake_only]
    assert brake_points == [0]
    # The line sits at x = 5.0, so the onset waypoint is strictly before it.
    assert profile[brake_points[0]].x < 5.0
    # The declared speed cannot exceed what decel_mps2 can still stop in time.
    distance = 5.0 - profile[brake_points[0]].x
    bound = math.sqrt(2.0 * ACTUATOR.decel_mps2 * distance)
    assert profile[brake_points[0]].target_speed_mps <= min(ACTUATOR.max_linear_mps, bound) + 1e-9


def test_velocity_profile_reduces_speed_for_a_tight_stop_line_approach() -> None:
    """Same rule, geometry that actually binds: braking onset 0.5 m from the line."""
    slow_decel = ActuatorModel(decel_mps2=0.1)
    warehouse_map = _mapped_map()
    approach: tuple[tuple[float, float], ...] = (
        (1.0, 4.5),
        (4.5, 4.5),
        (5.5, 4.5),
        (11.0, 4.5),
    )
    plan = build_plan(approach, warehouse_map, slow_decel)
    profile = velocity_profile(plan, Pose2(x=1.0, y=4.5, theta=0.0), slow_decel, warehouse_map=warehouse_map)
    brake_points = [index for index, w in enumerate(profile) if w.brake_only]
    assert brake_points == [1]
    onset = profile[brake_points[0]]
    assert onset.x == pytest.approx(4.5)
    assert onset.target_speed_mps < slow_decel.max_linear_mps
    assert onset.target_speed_mps == pytest.approx(math.sqrt(2.0 * slow_decel.decel_mps2 * 0.5), rel=1e-6)


def test_velocity_profile_slows_for_turns() -> None:
    warehouse_map = corridor_map()
    grid = grid_for(warehouse_map)
    planner = AStarPlanner(grid, turn_cost=TurnCost(max_linear_mps=0.4, max_angular_radps=1.0))
    start = Pose2(x=1.0, y=4.5, theta=0.0)
    result = planner.plan_detailed((11.0, 0.8), FOOTPRINT, start=start)
    assert result.status.value == "ok", result.reason
    plan = build_plan(result.waypoints, warehouse_map, ACTUATOR)
    profile = velocity_profile(plan, start, ACTUATOR)
    cruise = max(w.target_speed_mps for w in profile)
    corners = [w.target_speed_mps for w in profile if w.target_speed_mps < cruise - 1e-9]
    assert corners, "a route around the pillar must slow down somewhere"
    assert min(corners) < cruise
    assert min(corners) >= 0.0


def test_velocity_profile_without_a_map_never_claims_brake_only() -> None:
    warehouse_map = _mapped_map()
    plan = build_plan(((1.0, 4.5), (11.0, 4.5)), warehouse_map, ACTUATOR)
    profile = velocity_profile(plan, Pose2(x=1.0, y=4.5, theta=0.0), ACTUATOR)
    assert not any(w.brake_only for w in profile)


def test_estimated_duration_is_a_declared_estimate_not_a_measurement() -> None:
    warehouse_map = corridor_map()
    straight: tuple[tuple[float, float], ...] = ((1.0, 4.5), (11.0, 4.5))
    plan = build_plan(straight, warehouse_map, ACTUATOR)
    assert plan.length_m == pytest.approx(10.0)
    assert plan.estimated_duration_s == pytest.approx(10.0 / ACTUATOR.max_linear_mps)
    assert plan.turn_count == 0
    corner: tuple[tuple[float, float], ...] = ((1.0, 4.5), (3.0, 4.5), (3.0, 2.5))
    corner_plan = build_plan(corner, warehouse_map, ACTUATOR)
    assert corner_plan.turn_count == 1
    assert corner_plan.estimated_duration_s == pytest.approx(
        4.0 / ACTUATOR.max_linear_mps + (math.pi / 2.0) / ACTUATOR.max_angular_radps
    )

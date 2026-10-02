"""Approximate space-time planner, asserted only to the contract it documents.

The module docstring in ``niharamesh.planning.temporal`` is the contract. These
tests assert exactly two things and nothing more:

1. the reservations a plan declares are conflict-free among themselves;
2. a reservation the planner was told about produces a delay, or an explicit
   failure carrying a reason.

They assert **no** completeness and **no** optimality, because the planner claims
neither. A test that demanded either would be demanding something the module
explicitly disclaims.
"""

from __future__ import annotations

import importlib
import sys

import pytest

import niharamesh.planning as planning
from niharamesh.domain.config import FeatureFlags
from niharamesh.domain.map import MapBoundary, Obstacle, ObstacleKind, WarehouseMap
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.planning.grid import OccupancyGrid


def _latch_and_import() -> tuple[object, ...]:
    """Latch the feature flag the way a run would, then import the module.

    This is the *only* way the test module reaches the planner, which is exactly the
    point: the flag has to be latched deliberately, not imported past.
    """
    planning.set_temporal_exports_enabled(True)
    try:
        module = importlib.import_module("niharamesh.planning.temporal")
        return (
            module,
            module.PLANNER_LABEL,
            module.ApproxSippSingleCellPlanner,
            module.Reservation,
            module.TemporalPlan,
            module.TemporalPlanFailure,
            module.reservations_needed,
            module.temporal_planning_enabled,
        )
    finally:
        planning.set_temporal_exports_enabled(False)


(
    _temporal,
    PLANNER_LABEL,
    ApproxSippSingleCellPlanner,
    Reservation,
    TemporalPlan,
    TemporalPlanFailure,
    reservations_needed,
    temporal_planning_enabled,
) = _latch_and_import()

FOOTPRINT = Footprint(length_m=0.2, width_m=0.2, turning_radius_m=0.1)
START = (1.0, 1.0)
GOAL = (8.0, 1.0)
#: Matches the synthetic strips below, which are hand-built with a fixed inflation.
STRIP_FOOTPRINT = Footprint(length_m=0.1, width_m=0.1, turning_radius_m=0.05)


def open_grid(*, resolution_m: float = 0.5) -> OccupancyGrid:
    warehouse_map = WarehouseMap(
        map_id="temporal-test",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=10.0, max_y=4.0),
        obstacles=(),
        grid_resolution_m=resolution_m,
    )
    return OccupancyGrid.from_map(warehouse_map, FOOTPRINT.clearance_radius_m())


def single_row_grid() -> OccupancyGrid:
    """A one-cell corridor: any reservation in it must be waited out, not dodged.

    The inflation matches :data:`STRIP_FOOTPRINT` exactly, so the planner accepts
    the grid rather than refusing it for insufficient clearance - the point of these
    tests is the temporal behaviour, not the inflation arithmetic.
    """
    return OccupancyGrid(
        origin_x=0.0,
        origin_y=0.0,
        resolution=1.0,
        nx=6,
        ny=1,
        blocked=bytearray(6),
        static_blocked=bytearray(6),
        inflation_m=STRIP_FOOTPRINT.clearance_radius_m(),
        zones_blocking=False,
        map_id="temporal-strip",
        obstacle_count=0,
    )


def strip_planner(grid: OccupancyGrid, **kwargs: object) -> ApproxSippSingleCellPlanner:
    return ApproxSippSingleCellPlanner(grid, enabled=True, **kwargs)  # type: ignore[arg-type]


def planner_for(grid: OccupancyGrid, **kwargs: object) -> ApproxSippSingleCellPlanner:
    return strip_planner(grid, **kwargs)


# ----------------------------------------------------------------------
# the feature gate
# ----------------------------------------------------------------------


def test_importing_the_module_directly_is_refused_until_the_flag_is_latched() -> None:
    """The load-bearing gate is the import-time guard inside the module itself.

    The package's ``__getattr__`` is a second convenience gate. It is only
    reachable while the submodule has *never* been imported, because Python binds
    ``planning.temporal`` as a real attribute after the first successful import.
    That asymmetry is exactly why the import-time guard is the one that matters, and
    this test drops the cached module to exercise it.
    """
    cached = sys.modules.pop("niharamesh.planning.temporal", None)
    planning.set_temporal_exports_enabled(False)
    try:
        with pytest.raises(ImportError, match="temporal_planning"):
            importlib.import_module("niharamesh.planning.temporal")
        planning.set_temporal_exports_enabled(True)
        module = importlib.import_module("niharamesh.planning.temporal")
        assert module.PLANNER_LABEL == PLANNER_LABEL
    finally:
        planning.set_temporal_exports_enabled(False)
        if cached is not None:
            sys.modules["niharamesh.planning.temporal"] = cached


def test_package_attribute_access_is_gated_before_the_module_is_ever_imported() -> None:
    cached = sys.modules.pop("niharamesh.planning.temporal", None)
    had_attribute = "temporal" in vars(planning)
    saved = vars(planning).pop("temporal", None)
    planning.set_temporal_exports_enabled(False)
    try:
        with pytest.raises(ImportError, match="temporal_planning"):
            planning.temporal  # noqa: B018 - the access is the assertion
        with pytest.raises(ImportError, match="temporal_planning"):
            planning.ApproxSippSingleCellPlanner  # noqa: B018
        with pytest.raises(ImportError, match="temporal_planning"):
            planning.TemporalPlan  # noqa: B018
        with pytest.raises(AttributeError, match="has no attribute"):
            planning.NoSuchExport  # noqa: B018
    finally:
        planning.set_temporal_exports_enabled(False)
        if cached is not None:
            sys.modules["niharamesh.planning.temporal"] = cached
        if had_attribute and saved is not None:
            vars(planning)["temporal"] = saved


def test_the_flag_reader_is_the_single_source() -> None:
    assert temporal_planning_enabled(FeatureFlags()) is False
    assert temporal_planning_enabled(FeatureFlags(temporal_planning=True)) is True


def test_the_planner_refuses_to_run_even_when_importable() -> None:
    grid = open_grid()
    disabled = ApproxSippSingleCellPlanner(grid, enabled=False)
    outcome = disabled.plan(GOAL, FOOTPRINT, (), start=START)
    assert isinstance(outcome, TemporalPlanFailure)
    assert outcome.reason == "temporal_planner_disabled"
    assert disabled.enabled is False


# ----------------------------------------------------------------------
# reservations
# ----------------------------------------------------------------------


def test_reservations_are_produced_and_conflict_free() -> None:
    grid = open_grid()
    planner = planner_for(grid, max_speed_mps=0.4, tick_s=0.05, horizon_ticks=4000)
    outcome = planner.plan(GOAL, FOOTPRINT, (), start=START)
    assert isinstance(outcome, TemporalPlan), outcome
    assert outcome.planner_label == PLANNER_LABEL

    reservations = reservations_needed(outcome)
    assert reservations == outcome.reservations
    assert reservations
    assert all(len(entry) == 3 for entry in reservations)
    for cell, t_start, t_end in reservations:
        assert isinstance(cell, int)
        assert 0 <= t_start <= t_end
        assert t_end - t_start + 1 == outcome.ticks_per_cell

    # (a) no cell is claimed twice over overlapping intervals
    by_cell: dict[int, list[tuple[int, int]]] = {}
    for cell, t_start, t_end in reservations:
        by_cell.setdefault(cell, []).append((t_start, t_end))
    for cell, intervals in by_cell.items():
        assert len(intervals) == 1, f"cell {cell} claimed {len(intervals)} times"
    # (b) no two cells are claimed at the same tick
    occupied: dict[int, int] = {}
    for cell, t_start, t_end in reservations:
        for tick in range(t_start, t_end + 1):
            assert tick not in occupied, f"tick {tick} claimed by cells {occupied[tick]} and {cell}"
            occupied[tick] = cell
    # (c) arrivals are non-decreasing along the route
    ticks = [tick for _cell, tick in outcome.cells]
    assert ticks == sorted(ticks)
    assert ticks[0] == 0
    assert outcome.duration_ticks == ticks[-1]


#: Cell 3 of the strip, held across the tick window the robot would otherwise
#: occupy it in. Anchored on the free plan so the test states a *conflict*, not a
#: reservation that happens to sit somewhere the robot never goes.
BLOCKED_CELL = 3


def test_reservations_never_overlap_a_reservation_the_planner_was_told_about() -> None:
    grid = single_row_grid()
    planner = strip_planner(grid, max_speed_mps=0.4, tick_s=0.25, horizon_ticks=200)
    free = planner.plan((5.5, 0.5), STRIP_FOOTPRINT, (), start=(0.5, 0.5))
    assert isinstance(free, TemporalPlan), free
    # The free plan occupies cell 3 at exactly these ticks; claim them and the
    # planner must route its occupancy elsewhere in time.
    uncontested = next(
        (t_start, t_end) for cell, t_start, t_end in reservations_needed(free) if cell == BLOCKED_CELL
    )
    blocker: Reservation = (BLOCKED_CELL, uncontested[0], uncontested[1])

    outcome = planner.plan((5.5, 0.5), STRIP_FOOTPRINT, (blocker,), start=(0.5, 0.5))
    assert isinstance(outcome, TemporalPlan), outcome
    for cell, t_start, _t_end in reservations_needed(outcome):
        if cell != BLOCKED_CELL:
            continue
        assert t_start > blocker[2], f"planned into cell {cell} at t={t_start} <= {blocker[2]}"
    assert outcome.delay_ticks > 0


def test_a_conflicting_reservation_causes_a_delay() -> None:
    grid = single_row_grid()
    planner = strip_planner(grid, max_speed_mps=0.4, tick_s=0.25, horizon_ticks=400)
    free = planner.plan((5.5, 0.5), STRIP_FOOTPRINT, (), start=(0.5, 0.5))
    assert isinstance(free, TemporalPlan), free
    blocked = planner.plan(
        (5.5, 0.5),
        STRIP_FOOTPRINT,
        ((BLOCKED_CELL, free.duration_ticks // 2, free.duration_ticks),),
        start=(0.5, 0.5),
    )
    assert isinstance(blocked, TemporalPlan), blocked
    assert blocked.delay_ticks > free.delay_ticks
    assert blocked.duration_ticks > free.duration_ticks


def test_an_unreachable_reservation_table_fails_explicitly_with_a_reason() -> None:
    grid = single_row_grid()
    planner = strip_planner(grid, max_speed_mps=0.4, tick_s=0.25, horizon_ticks=6)
    outcome = planner.plan((5.5, 0.5), STRIP_FOOTPRINT, ((3, 0, 5),), start=(0.5, 0.5))
    assert isinstance(outcome, TemporalPlanFailure)
    assert outcome.reason == "no_temporal_path"
    assert "incomplete" in outcome.detail
    assert "not a proof" in outcome.detail
    assert str(outcome).startswith("no_temporal_path:")


def test_blocked_start_and_goal_fail_with_their_own_reasons() -> None:
    warehouse_map = WarehouseMap(
        map_id="temporal-blocked",
        boundary=MapBoundary(min_x=0.0, min_y=0.0, max_x=10.0, max_y=4.0),
        obstacles=(
            Obstacle(
                id="block",
                kind=ObstacleKind.SHELF,
                pose=Pose2(x=8.0, y=1.0, theta=0.0),
                length_m=2.0,
                width_m=2.0,
            ),
        ),
        grid_resolution_m=0.5,
    )
    grid = OccupancyGrid.from_map(warehouse_map, FOOTPRINT.clearance_radius_m())
    planner = planner_for(grid)
    goal_failure = planner.plan((8.0, 1.0), FOOTPRINT, (), start=START)
    assert isinstance(goal_failure, TemporalPlanFailure)
    assert goal_failure.reason == "blocked_goal"
    start_failure = planner.plan(GOAL, FOOTPRINT, (), start=(8.0, 1.0))
    assert isinstance(start_failure, TemporalPlanFailure)
    assert start_failure.reason == "blocked_start"


def test_missing_start_position_is_refused() -> None:
    planner = planner_for(open_grid())
    outcome = planner.plan(GOAL, FOOTPRINT, (), start=None)
    assert isinstance(outcome, TemporalPlanFailure)
    assert outcome.reason == "no_start_position"


def test_a_grid_that_does_not_serve_the_footprint_is_refused() -> None:
    small_grid = open_grid()
    fat = Footprint(length_m=2.0, width_m=2.0, turning_radius_m=0.5)
    planner = planner_for(small_grid)
    outcome = planner.plan(GOAL, fat, (), start=START)
    assert isinstance(outcome, TemporalPlanFailure)
    assert outcome.reason == "insufficient_clearance"


def test_inverted_reservation_intervals_are_refused() -> None:
    planner = strip_planner(single_row_grid())
    with pytest.raises(ValueError, match="inverted"):
        planner.plan((5.5, 0.5), STRIP_FOOTPRINT, ((3, 7, 2),), start=(0.5, 0.5))


def test_planning_is_deterministic_and_parameters_are_validated() -> None:
    planner = planner_for(open_grid(), max_speed_mps=0.4, tick_s=0.05)
    first = planner.plan(GOAL, FOOTPRINT, (), start=START)
    second = planner.plan(GOAL, FOOTPRINT, (), start=START)
    assert isinstance(first, TemporalPlan)
    assert first.cells == second.cells
    assert first.duration_ticks == second.duration_ticks
    assert first.delay_ticks == second.delay_ticks
    assert planner.ticks_per_cell >= 1
    assert planner.tick_s == 0.05
    assert planner.horizon_ticks == 4000

    with pytest.raises(ValueError, match="max_speed_mps"):
        ApproxSippSingleCellPlanner(open_grid(), max_speed_mps=0.0)
    with pytest.raises(ValueError, match="tick_s"):
        ApproxSippSingleCellPlanner(open_grid(), tick_s=0.0)
    with pytest.raises(ValueError, match="horizon_ticks"):
        ApproxSippSingleCellPlanner(open_grid(), horizon_ticks=0)


def test_temporal_plan_requires_cells() -> None:
    empty = TemporalPlan(cells=(), ticks_per_cell=2, duration_ticks=0, delay_ticks=0, horizon_ticks=10)
    assert empty.reservations == ()
    assert empty.planner_label == PLANNER_LABEL

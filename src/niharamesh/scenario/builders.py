"""Programmatic builders for warehouse maps, tasks and scenarios.

Scenarios are authored here and exported to versioned JSON under ``scenarios/``.
The builders exist so the authored library is *reproducible* rather than being
hand-edited JSON that nobody can regenerate.

Geometry convention for every map in the library
------------------------------------------------
* Robot chassis: 0.60 m x 0.40 m, clearance radius 0.36 m.
* Nominal aisle clear width: 1.40 m, which leaves 1.00 m of lateral freedom for a
  0.40 m chassis -- enough for the declared turning sweep, with margin.
* Shelf blocks sit on a regular lattice so that every gap between two blocks is
  exactly 1.40 m. That invariant is asserted by
  :func:`assert_aisle_clearance`.
* Every exclusive zone is one full aisle *segment* between two cross aisles.
  Consecutive segments are therefore separated by a whole cross aisle, which is a
  safe place to stop. Disjoint zone geometry and "there is always a berth
  between consecutive zones" both follow from the lattice.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal

from niharamesh.domain.config import (
    AssignmentPolicy,
    ComparisonMode,
    CoordinationPolicy,
    RoutingPolicy,
    SimulationConfig,
)
from niharamesh.domain.faults import FaultChannel, FaultKind, FaultSpec, FaultTarget
from niharamesh.domain.identity import Capability, RobotIdentity
from niharamesh.domain.map import (
    Berth,
    MapBoundary,
    Obstacle,
    ObstacleKind,
    Station,
    StationKind,
    StopLine,
    WarehouseMap,
    Zone,
    ZoneMovement,
)
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.domain.scenario import (
    IntentDescription,
    RobotStart,
    RunPolicy,
    Scenario,
)
from niharamesh.domain.task import Task
from niharamesh.domain.units import SCHEMA_VERSION

#: Authored scenario kinds. Mirrors ``Scenario.kind`` but is imported from the
#: domain module so a typo is a type error rather than a runtime rejection.
type ScenarioKind = Literal["nominal", "fault", "diagnostic", "benchmark"]

__all__ = [
    "AISLE_CLEAR_M",
    "AMR_FOOTPRINT",
    "AMR_MODEL",
    "DEFAULT_ROBOT_COUNT",
    "aisle_zone",
    "assert_aisle_clearance",
    "base_warehouse",
    "berth",
    "make_scenario",
    "obstacle",
    "shelf_block",
    "standard_amr",
    "station",
    "stop_line",
]

#: Declared robot geometry. A *configured assumption*, labelled as such in the UI.
AMR_FOOTPRINT = Footprint(
    length_m=0.60,
    width_m=0.40,
    payload_length_m=0.30,
    payload_width_m=0.24,
    payload_offset_m=0.0,
    turning_radius_m=0.32,
)

AMR_MODEL = "niharamesh-amr-600"

#: Clear width between two adjacent shelf blocks, metres.
AISLE_CLEAR_M = 1.40

DEFAULT_ROBOT_COUNT = 3

# -- lattice constants (26 m x 18 m envelope) ---------------------------------
_ENV = MapBoundary(min_x=0.0, min_y=0.0, max_x=26.0, max_y=18.0)
_SHELF_X0 = (5.0, 9.6, 14.2, 18.8)  # 4 columns
_SHELF_W = 3.2
_SHELF_Y0 = (2.6, 7.6, 12.6)  # 3 rows
_SHELF_D = 3.6

#: Aisle centre lines between and beside shelf blocks.
VERTICAL_AISLES = (8.9, 13.5, 18.1, 24.0)
#: Cross-aisle centre lines: bottom perimeter, then one per row gap, then top.
_CROSS_Y = (1.3, 6.9, 11.9, 17.1)
HORIZONTAL_AISLES = _CROSS_Y


def obstacle(
    oid: str,
    kind: ObstacleKind,
    cx: float,
    cy: float,
    length: float,
    width: float,
    *,
    theta: float = 0.0,
    dynamic: bool = False,
) -> Obstacle:
    return Obstacle(
        id=oid,
        kind=kind,
        pose=Pose2(x=cx, y=cy, theta=theta),
        length_m=length,
        width_m=width,
        dynamic=dynamic,
    )


def shelf_block(col: int, row: int, *, tag: str = "shelf") -> Obstacle:
    """One lattice shelf block, centred."""
    x0 = _SHELF_X0[col]
    y0 = _SHELF_Y0[row]
    return obstacle(
        f"{tag}-{col}{row}",
        ObstacleKind.SHELF,
        cx=x0 + _SHELF_W / 2.0,
        cy=y0 + _SHELF_D / 2.0,
        length=_SHELF_W,
        width=_SHELF_D,
    )


def station(sid: str, kind: StationKind, x: float, y: float, *, service_s: float = 4.0) -> Station:
    return Station(id=sid, kind=kind, pose=Pose2(x=x, y=y, theta=0.0), service_time_s=service_s, capacity=1)


def berth(bid: str, x: float, y: float, *, theta: float = 0.0, capacity: int = 1) -> Berth:
    return Berth(id=bid, pose=Pose2(x=x, y=y, theta=theta), capacity=capacity)


def stop_line(
    lid: str, zone_id: str, y: float, x0: float, x1: float, *, approach: str = "increasing"
) -> StopLine:
    return StopLine(id=lid, zone_id=zone_id, start=(x0, y), end=(x1, y), approach=approach)


def aisle_zone(
    zid: str,
    *,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    entry: tuple[float, float, float],
    exit_pose: tuple[float, float, float],
    queue_berth: str | None = None,
    exit_berth: str | None = None,
    kind: str = "corridor",
    one_way: float | None = None,
) -> Zone:
    """An exclusive zone covering one aisle segment.

    The protected rectangle is the *inflated* corridor: the raw corridor grown by
    the robot clearance radius on every side, because two robots inside the same
    1.40 m aisle are in conflict even if their centres are 1.40 m apart.
    """
    margin = AMR_FOOTPRINT.clearance_radius_m()
    return Zone(
        id=zid,
        kind=kind,
        description=f"exclusive {kind} segment",
        protected_origin=(x0 - margin, y0 - margin),
        protected_extent=((x1 - x0) + 2 * margin, (y1 - y0) + 2 * margin),
        entry_pose=Pose2(x=entry[0], y=entry[1], theta=entry[2]),
        exit_pose=Pose2(x=exit_pose[0], y=exit_pose[1], theta=exit_pose[2]),
        queue_berth_id=queue_berth,
        exit_berth_id=exit_berth,
        allowed_movement=(ZoneMovement.FWD, ZoneMovement.CROSS),
        one_way_heading_rad=one_way,
    )


def assert_aisle_clearance(map: WarehouseMap, minimum_m: float = AISLE_CLEAR_M) -> None:
    """Raise if any pair of axis-aligned shelf blocks is closer than *minimum_m*.

    This is the lattice invariant that makes every authored zone disjoint and
    every aisle wide enough for the declared turning sweep. Asserting it here
    means an authored map cannot silently become a "undersized passage".
    """
    boxes = [
        (
            o.pose.x - o.length_m / 2,
            o.pose.y - o.width_m / 2,
            o.pose.x + o.length_m / 2,
            o.pose.y + o.width_m / 2,
        )
        for o in map.obstacles
        if o.kind is ObstacleKind.SHELF and abs(o.pose.theta) < 1e-9
    ]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            dx = max(a[0] - b[2], b[0] - a[2], 0.0)
            dy = max(a[1] - b[3], b[1] - a[3], 0.0)
            gap = math.hypot(dx, dy)
            if gap < minimum_m - 1e-6:
                raise ValueError(
                    f"aisle clearance {gap:.3f} m below the declared {minimum_m:.2f} m "
                    f"between obstacles {a} and {b}"
                )


def standard_amr(robot_id: str, *, max_linear: float = 0.4) -> RobotIdentity:
    return RobotIdentity(
        robot_id=robot_id,
        model=AMR_MODEL,
        capabilities=(Capability.CARRY_PAYLOAD, Capability.DOCK),
        footprint=AMR_FOOTPRINT,
        max_linear_mps=max_linear,
        max_angular_radps=1.0,
    )


def base_warehouse(map_id: str, name: str, *, revision: int = 1) -> WarehouseMap:
    """The shared 26 m x 18 m warehouse with 4x3 shelf blocks and perimeter aisles."""
    obstacles = tuple(shelf_block(c, r) for c in range(4) for r in range(3))
    stations = (
        station("stn-pick-a", StationKind.PICKUP, 2.5, 2.0),
        station("stn-pick-b", StationKind.PICKUP, 2.5, 9.0),
        station("stn-pick-c", StationKind.PICKUP, 2.5, 15.5),
        station("stn-drop-a", StationKind.DROP, 24.2, 2.0),
        station("stn-drop-b", StationKind.DROP, 24.2, 9.0),
        station("stn-drop-c", StationKind.DROP, 24.2, 15.5),
        station("stn-charge-a", StationKind.CHARGE, 24.2, 17.2, service_s=30.0),
    )
    berths = _lattice_berths()
    return WarehouseMap(
        schema_version=SCHEMA_VERSION,
        map_id=map_id,
        revision=revision,
        name=name,
        boundary=_ENV,
        obstacles=obstacles,
        stations=stations,
        berths=berths,
        grid_resolution_m=0.1,
        nominal_aisle_width_m=AISLE_CLEAR_M,
    )


def _lattice_berths() -> tuple[Berth, ...]:
    """Holding berths on every cross aisle.

    Interior aisle berths are **offset 1.5 m laterally** from the aisle centre
    line. That offset matters: a berth on the aisle centre line at a cross-aisle
    y would fall inside the inflated protected area of the zone it is supposed to
    let a robot wait *outside* of. The offset puts the berth in the cross aisle
    (which is free across the whole warehouse) while keeping it laterally clear
    of every vertical zone.
    """
    out: list[Berth] = []
    xs: tuple[tuple[float, ...], ...] = (
        (2.5,),
        (8.9 - 1.5, 8.9 + 1.5),
        (13.5 - 1.5, 13.5 + 1.5),
        (18.1 - 1.5, 18.1 + 1.5),
        (24.0,),
    )
    ys = (1.3, 6.9, 11.9, 17.1)
    n = 0
    for row in xs:
        for x in row:
            for y in ys:
                out.append(berth(f"brt-{n:02d}", x, y, capacity=2))
                n += 1
    return tuple(out)


def berth_id(x: float, y: float, *, tolerance: float = 0.05) -> str:
    """Resolve a berth id from a position.

    Used by the scenario library so berth references are derived from the lattice
    rather than hard-coded, which is what keeps zone/berth references consistent
    when the lattice changes.
    """
    for b in _BERTH_INDEX:
        if abs(b.pose.x - x) <= tolerance and abs(b.pose.y - y) <= tolerance:
            return b.id
    raise KeyError(f"no lattice berth at ({x}, {y})")


#: Positions, per vertical aisle centre line, where a queue/exit berth is placed.
#: ``+/- 1.5 m`` is the lateral offset out of the aisle's protected area.
def aisle_berth_x(aisle_x: float) -> tuple[float, ...]:
    """Lateral offsets at which queue/exit berths sit for this aisle.

    Interior aisles are offset +/-1.5 m so the berth lands in the cross aisle and
    outside the aisle's protected area. The perimeter aisles are already in open
    floor, so they need no offset.
    """
    if aisle_x <= 2.5 or aisle_x >= 24.0:
        return (aisle_x,)
    return (aisle_x - 1.5, aisle_x + 1.5)


_BERTH_INDEX: tuple[Berth, ...] = _lattice_berths()


def row_zone(
    zid: str,
    *,
    aisle_x: float,
    row: int,
    kind: str = "aisle",
    one_way: float | None = None,
) -> Zone:
    """An exclusive zone for the aisle segment alongside shelf *row*.

    Segments are the y-span of one shelf row. Because the rows are separated by a
    full 1.40 m cross aisle, consecutive zones along the same aisle are always
    separated by a safe place to stop. That is the property that lets the
    protocol hold "at most one outstanding grant per robot" without deadlocking:
    a robot can always release its grant, come to rest, and only then seek the
    next one.
    """
    y0 = _SHELF_Y0[row]
    y1 = y0 + _SHELF_D
    half = AISLE_CLEAR_M / 2.0
    entry_cross = _CROSS_Y[row - 1] if row > 0 else _CROSS_Y[0]
    exit_cross = _CROSS_Y[row] if row < len(_CROSS_Y) else _CROSS_Y[-1]
    offset = 1.5
    return Zone(
        id=zid,
        kind=kind,
        description=f"exclusive {kind} segment beside shelf row {row}",
        protected_origin=(
            aisle_x - half - AMR_FOOTPRINT.clearance_radius_m(),
            y0 - AMR_FOOTPRINT.clearance_radius_m(),
        ),
        protected_extent=(
            (2 * half) + 2 * AMR_FOOTPRINT.clearance_radius_m(),
            (y1 - y0) + 2 * AMR_FOOTPRINT.clearance_radius_m(),
        ),
        entry_pose=Pose2(x=aisle_x, y=entry_cross, theta=_THETA_N),
        exit_pose=Pose2(x=aisle_x, y=exit_cross, theta=_THETA_N),
        queue_berth_id=berth_id(aisle_x + offset, entry_cross),
        exit_berth_id=berth_id(aisle_x + offset, exit_cross),
        allowed_movement=(ZoneMovement.FWD, ZoneMovement.CROSS),
        one_way_heading_rad=one_way,
    )


def row_stop_lines(zid: str, *, aisle_x: float, row: int) -> tuple[StopLine, StopLine]:
    """Stop lines on the two cross aisles bounding the row segment."""
    y0 = _SHELF_Y0[row]
    y1 = y0 + _SHELF_D
    half = AISLE_CLEAR_M / 2.0 + 0.4
    return (
        StopLine(
            id=f"sl-{zid}-in",
            zone_id=zid,
            start=(aisle_x - half, y0),
            end=(aisle_x + half, y0),
            approach="increasing",
        ),
        StopLine(
            id=f"sl-{zid}-out",
            zone_id=zid,
            start=(aisle_x - half, y1),
            end=(aisle_x + half, y1),
            approach="increasing",
        ),
    )


_THETA_N = math.pi / 2.0


def make_scenario(
    *,
    scenario_id: str,
    name: str,
    description: str,
    intent: IntentDescription,
    map: WarehouseMap,
    robot_ids: Sequence[str],
    starts: Sequence[RobotStart],
    tasks: Sequence[Task],
    faults: Sequence[FaultSpec] = (),
    kind: ScenarioKind = "nominal",
    policy: RunPolicy | None = None,
    simulation: SimulationConfig | None = None,
    seed: int = 20260101,
    max_sim_time_s: float = 900.0,
) -> Scenario:
    scenario = Scenario(
        schema_version=SCHEMA_VERSION,
        scenario_id=scenario_id,
        name=name,
        description=description,
        kind=kind,
        intent=intent,
        map=map,
        robots=tuple(standard_amr(r) for r in robot_ids),
        starts=tuple(starts),
        tasks=tuple(tasks),
        faults=tuple(faults),
        policy=policy or RunPolicy(),
        simulation=simulation or SimulationConfig(),
        seed=seed,
        max_sim_time_s=max_sim_time_s,
    )
    assert_aisle_clearance(scenario.map)
    return scenario


def default_policy(
    coordination: CoordinationPolicy = CoordinationPolicy.CANONICAL_SEQUENTIAL,
) -> RunPolicy:
    return RunPolicy(
        coordination=coordination,
        assignment=AssignmentPolicy.LOCAL_AUCTION,
        routing=RoutingPolicy.BLOCKED_AWARE,
        comparison_mode=ComparisonMode.COORDINATION_ONLY,
        planner_seed=11,
        sensor_seed=22,
        fault_seed=33,
    )


def partition_fault(
    fault_id: str,
    sender: str,
    receiver: str,
    *,
    start_s: float,
    duration_s: float,
    kind: FaultKind = FaultKind.PARTITION,
    invariant: str = "the partitioned robot retains occupancy and stops safely",
    seed: int = 33,
) -> FaultSpec:
    return FaultSpec(
        fault_id=fault_id,
        target=FaultTarget(channel=FaultChannel.COORDINATION, kind=kind, sender=sender, receiver=receiver),
        start_at_s=start_s,
        duration_s=duration_s,
        seed=seed,
        params={"jitter_s": 0.05} if kind is FaultKind.DELAY else {},
        expected_invariant=invariant,
    )

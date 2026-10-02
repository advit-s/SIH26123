"""The named scenario library.

Seven scenarios that between them cover every contested geometry and failure mode
the brief requires:

1. ``headon-aisle``       - two robots meeting head-on in the same aisle row.
2. ``three-way-junction`` - three robots contending for one junction zone.
3. ``cycle-with-holding`` - a delivery cycle that needs holding berths.
4. ``blocked-exit``       - a station exit blocked by an inserted obstacle.
5. ``dynamic-arrivals``   - tasks released mid-run.
6. ``asymmetric-partition`` - a directed channel cut between one pair of robots.
7. ``infeasible-layout``  - a deliberately unsatisfiable map whose *correct*
   result is a safe, explained stop (never eligible for a success comparison).

Zones are authored with :func:`row_zone`, which places the exclusive zone beside
one shelf row and resolves its queue and exit berths from the offset lattice.
Consecutive zones along the same aisle are therefore always separated by a full
cross aisle, which is a safe place to come to rest.

Every scenario is exported to ``scenarios/<id>.r<N>.json`` so it is a reviewable,
versioned artifact, and rebuilt from here so it is reproducible.
"""

from __future__ import annotations

from niharamesh.domain.config import (
    AssignmentPolicy,
    ComparisonMode,
    CoordinationPolicy,
    RoutingPolicy,
)
from niharamesh.domain.faults import FaultChannel, FaultKind, FaultSpec, FaultTarget
from niharamesh.domain.map import ObstacleKind, StopLine
from niharamesh.domain.pose import Pose2
from niharamesh.domain.scenario import IntentDescription, RobotStart, RunPolicy, Scenario
from niharamesh.domain.task import Task
from niharamesh.scenario.builders import (
    AISLE_CLEAR_M,
    AMR_FOOTPRINT,
    aisle_zone,
    base_warehouse,
    berth_id,
    default_policy,
    make_scenario,
    obstacle,
    partition_fault,
    row_stop_lines,
    row_zone,
)

__all__ = ["SCENARIOS", "build", "build_all", "scenario_ids"]

_R1, _R2, _R3 = "amr-01", "amr-02", "amr-03"
_THREE = (_R1, _R2, _R3)
_EAST = 0.0
_WEST = 3.141592653589793
_NORTH = 1.5707963267948966

# Shelf rows and the aisle centre lines used by the library.
_ROW = {"bottom": 0, "middle": 1, "top": 2}
_AISLE_W = 8.9
_AISLE_M = 13.5
_AISLE_E = 18.1




def _task(
    task_id: str,
    pickup: str,
    drop: str,
    *,
    release_s: float = 0.0,
    service_s: float = 3.0,
    priority: int = 100,
) -> Task:
    return Task(
        task_id=task_id,
        pickup_station_id=pickup,
        drop_station_id=drop,
        release_at_s=release_s,
        service_time_s=service_s,
        required_capabilities=("carry_payload",),
        priority=priority,
    )


# --------------------------------------------------------------------------- 1
def headon_aisle() -> Scenario:
    """Two robots enter the same aisle segment from opposite ends.

    A 1.40 m aisle admits a 0.40 m chassis but cannot pass two of them, so
    exactly one may traverse while the other holds in a cross-aisle berth. This is
    the scenario that most directly separates a real coordination policy from a
    stop-and-wait baseline.
    """
    zone = row_zone("zn-headon-mid", aisle_x=_AISLE_M, row=_ROW["middle"], kind="aisle")
    # The head-on pair contend for the same zone from opposite approaches.
    zone = zone.model_copy(
        update={
            "queue_berth_id": berth_id(_AISLE_M + 1.5, 6.9),
            "exit_berth_id": berth_id(_AISLE_M + 1.5, 11.9),
        }
    )
    wm = base_warehouse("map-headon", "Head-on aisle")
    wm = wm.model_copy(
        update={
            "zones": (zone,),
            "stop_lines": row_stop_lines("zn-headon-mid", aisle_x=_AISLE_M, row=_ROW["middle"]),
        }
    )

    tasks = (
        _task("t-headon-up", "stn-pick-a", "stn-drop-c"),
        _task("t-headon-down", "stn-pick-c", "stn-drop-a"),
    )
    starts = (
        RobotStart(
            robot_id=_R1,
            pose=Pose2(x=_AISLE_M, y=1.3, theta=_NORTH),
            assigned_task_id="t-headon-up",
        ),
        RobotStart(
            robot_id=_R2,
            pose=Pose2(x=_AISLE_M, y=17.1, theta=_WEST),
            assigned_task_id="t-headon-down",
        ),
        RobotStart(
            robot_id=_R3,
            pose=Pose2(x=_AISLE_W, y=11.9, theta=_EAST),
            assigned_task_id="t-headon-up",
        ),
    )
    return make_scenario(
        scenario_id="headon-aisle",
        name="Head-on narrow aisle",
        description=(
            "Two robots claim the same 1.40 m aisle segment from opposite approaches. There is no "
            "room to pass, so one must hold at a cross-aisle berth while the other traverses."
        ),
        intent=IntentDescription(
            goal="Deliver two opposing transports through one shared aisle segment without contact.",
            expect=(
                "Exactly one robot enters the aisle at a time; the other holds at a named berth. "
                "The zone inspector must show the blocking request, peer and resource."
            ),
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        policy=default_policy(),
        max_sim_time_s=600.0,
    )


# --------------------------------------------------------------------------- 2
def three_way_junction() -> Scenario:
    """Three robots contending for one junction zone on the centre cross aisle."""
    half = AISLE_CLEAR_M / 2.0
    cx, cy = _AISLE_M, 11.9
    junction = aisle_zone(
        "zn-junction",
        x0=cx - half,
        x1=cx + half,
        y0=cy - half,
        y1=cy + half,
        entry=(cx, cy - half - 0.30, _NORTH),
        exit_pose=(cx, cy + half + 0.30, _NORTH),
        # Laterally offset into the cross aisle, so a queued robot is genuinely
        # outside the junction's protected area rather than sitting in it.
        queue_berth=berth_id(cx + 1.5, 6.9),
        exit_berth=berth_id(cx + 1.5, 17.1),
        kind="junction",
    )
    lines = (
        _stop("sl-junction-in", "zn-junction", cx - half - 0.4, cx + half + 0.4, cy - half - 0.30),
        _stop("sl-junction-out", "zn-junction", cx - half - 0.4, cx + half + 0.4, cy + half + 0.30),
    )
    wm = base_warehouse("map-junction", "Three-way junction").model_copy(
        update={"zones": (junction,), "stop_lines": lines}
    )

    tasks = (
        _task("t-junction-0", "stn-pick-a", "stn-drop-b"),
        _task("t-junction-1", "stn-pick-b", "stn-drop-c"),
        _task("t-junction-2", "stn-pick-c", "stn-drop-a"),
    )
    starts = (
        RobotStart(
            robot_id=_R1, pose=Pose2(x=2.5, y=6.9, theta=_EAST), assigned_task_id="t-junction-0"
        ),
        RobotStart(
            robot_id=_R2, pose=Pose2(x=24.0, y=11.9, theta=_WEST), assigned_task_id="t-junction-1"
        ),
        RobotStart(
            robot_id=_R3,
            pose=Pose2(x=_AISLE_M, y=1.3, theta=_NORTH),
            assigned_task_id="t-junction-2",
        ),
    )
    return make_scenario(
        scenario_id="three-way-junction",
        name="Three-way junction contention",
        description="Three robots, one junction zone on the centre cross aisle, one grant at a time.",
        intent=IntentDescription(
            goal="Three transports cross one junction zone with a complete, explainable right of way.",
            expect=(
                "Right of way follows canonical acquisition order and every acquisition is "
                "inspectable in the zone inspector."
            ),
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        policy=default_policy(),
        max_sim_time_s=600.0,
    )


def _stop(lid: str, zone_id: str, x0: float, x1: float, y: float) -> StopLine:

    return StopLine(id=lid, zone_id=zone_id, start=(x0, y), end=(x1, y), approach="increasing")


# --------------------------------------------------------------------------- 3
def cycle_with_holding() -> Scenario:
    """A delivery cycle that genuinely needs the holding berths."""
    zones = tuple(
        row_zone(f"zn-cycle-{name}", aisle_x=_AISLE_W, row=row, kind="corridor")
        for name, row in _ROW.items()
    )
    lines: list[object] = []
    for z in zones:
        row = _ROW[z.id.removeprefix("zn-cycle-")]
        lines.extend(row_stop_lines(z.id, aisle_x=_AISLE_W, row=row))
    wm = base_warehouse("map-cycle", "Cycle with holding space").model_copy(
        update={"zones": zones, "stop_lines": tuple(lines)}
    )

    tasks = (
        _task("t-cycle-0", "stn-pick-a", "stn-drop-a", service_s=4.0),
        _task("t-cycle-1", "stn-pick-b", "stn-drop-b", service_s=4.0),
        _task("t-cycle-2", "stn-pick-c", "stn-drop-c", service_s=4.0),
    )
    starts = (
        RobotStart(
            robot_id=_R1, pose=Pose2(x=2.5, y=1.3, theta=_EAST), assigned_task_id="t-cycle-0"
        ),
        RobotStart(
            robot_id=_R2, pose=Pose2(x=_AISLE_M, y=1.3, theta=_EAST), assigned_task_id="t-cycle-1"
        ),
        RobotStart(
            robot_id=_R3, pose=Pose2(x=_AISLE_E, y=1.3, theta=_EAST), assigned_task_id="t-cycle-2"
        ),
    )
    return make_scenario(
        scenario_id="cycle-with-holding",
        name="Delivery cycle using holding berths",
        description=(
            "Three robots circulate between the pickup and drop rows, contending for three "
            "consecutive segments of the west aisle. Each segment must be released before the "
            "next is acquired, so a robot has to reach a berth in between."
        ),
        intent=IntentDescription(
            goal="Complete a three-robot delivery cycle while using holding berths correctly.",
            expect="Robots release one aisle segment and reach a berth before seeking the next.",
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        policy=default_policy(),
        max_sim_time_s=900.0,
    )


# --------------------------------------------------------------------------- 4
def blocked_exit() -> Scenario:
    """A drop-station exit corridor blocked by an obstacle inserted at run time."""
    zones = tuple(
        row_zone(f"zn-exit-{name}", aisle_x=_AISLE_E, row=row, kind="corridor")
        for name, row in _ROW.items()
    )
    lines: list[object] = []
    for z in zones:
        row = _ROW[z.id.removeprefix("zn-exit-")]
        lines.extend(row_stop_lines(z.id, aisle_x=_AISLE_E, row=row))
    # A pallet already narrowing the aisle beside the drop-b station.
    obstacles = (
        *base_warehouse("map-blocked-exit", "Blocked exit").obstacles,
        obstacle("obs-pallet", ObstacleKind.TEMPORARY, _AISLE_E, 9.4, 1.3, 0.8),
    )
    wm = base_warehouse("map-blocked-exit", "Blocked exit").model_copy(
        update={"zones": zones, "stop_lines": tuple(lines), "obstacles": obstacles}
    )

    tasks = (
        _task("t-blocked-0", "stn-pick-a", "stn-drop-b", service_s=4.0),
        _task("t-blocked-1", "stn-pick-b", "stn-drop-c", release_s=6.0, service_s=4.0),
    )
    faults = (
        FaultSpec(
            fault_id="fx-exit-block",
            target=FaultTarget(
                channel=FaultChannel.TELEMETRY,
                kind=FaultKind.OBSTACLE_INSERT,
                position=(_AISLE_E, 9.4),
                robot=_R1,
            ),
            start_at_s=40.0,
            duration_s=60.0,
            seed=33,
            params={"length_m": 1.3, "width_m": 0.9, "theta": 0.0, "replace": "obs-pallet"},
            expected_invariant=(
                "the blocked robot detects the obstruction, compares reroute cost against waiting, "
                "and never drives into it"
            ),
        ),
    )
    starts = (
        RobotStart(
            robot_id=_R1, pose=Pose2(x=2.5, y=6.9, theta=_EAST), assigned_task_id="t-blocked-0"
        ),
        RobotStart(
            robot_id=_R2, pose=Pose2(x=2.5, y=11.9, theta=_EAST), assigned_task_id="t-blocked-1"
        ),
        RobotStart(
            robot_id=_R3, pose=Pose2(x=24.0, y=6.9, theta=_WEST), assigned_task_id="t-blocked-1"
        ),
    )
    return make_scenario(
        scenario_id="blocked-exit",
        name="Blocked station exit",
        description="A temporary obstacle occupies the aisle beside drop station b for 60 s mid-run.",
        kind="fault",
        intent=IntentDescription(
            goal="Deliver both tasks while an obstacle blocks a shared aisle segment for 60 s.",
            expect=(
                "The affected robot either replans around the block or holds at a berth, with the "
                "cost comparison visible. It must never drive into the obstacle."
            ),
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        faults=faults,
        policy=default_policy(),
        max_sim_time_s=700.0,
    )


# --------------------------------------------------------------------------- 5
def dynamic_arrivals() -> Scenario:
    """Tasks released mid-run, so allocation must handle late rounds."""
    wm = base_warehouse("map-dynamic", "Dynamic task arrivals")
    tasks = (
        _task("t-dyn-0", "stn-pick-a", "stn-drop-a", release_s=0.0, service_s=4.0),
        _task("t-dyn-1", "stn-pick-b", "stn-drop-b", release_s=60.0, service_s=4.0),
        _task("t-dyn-2", "stn-pick-c", "stn-drop-c", release_s=120.0, service_s=4.0),
        _task("t-dyn-3", "stn-pick-a", "stn-drop-c", release_s=180.0, service_s=4.0),
    )
    starts = (
        RobotStart(robot_id=_R1, pose=Pose2(x=_AISLE_W, y=1.3, theta=_EAST)),
        RobotStart(robot_id=_R2, pose=Pose2(x=_AISLE_M, y=1.3, theta=_EAST)),
        RobotStart(robot_id=_R3, pose=Pose2(x=_AISLE_E, y=1.3, theta=_EAST)),
    )
    return make_scenario(
        scenario_id="dynamic-arrivals",
        name="Dynamic task arrivals",
        description="Four tasks released at 0 s, 60 s, 120 s and 180 s.",
        kind="benchmark",
        intent=IntentDescription(
            goal="Allocate and deliver tasks as they appear, with no duplicate award or custody.",
            expect="Each task is awarded exactly once and delivered exactly once.",
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        policy=RunPolicy(
            coordination=CoordinationPolicy.CANONICAL_SEQUENTIAL,
            assignment=AssignmentPolicy.LOCAL_AUCTION,
            routing=RoutingPolicy.BLOCKED_AWARE,
            comparison_mode=ComparisonMode.END_TO_END,
            planner_seed=11,
            sensor_seed=22,
            fault_seed=33,
        ),
        max_sim_time_s=900.0,
    )


# --------------------------------------------------------------------------- 6
def asymmetric_partition() -> Scenario:
    """A directed cut between two robots while a third keeps full connectivity.

    This separates genuine degraded operation from a fleet-wide stop. The third
    robot must keep working; the partitioned pair must stop safely rather than
    assume the aisle is empty.
    """
    zones = (
        row_zone("zn-part-mid-w", aisle_x=_AISLE_W, row=_ROW["middle"], kind="aisle"),
        row_zone("zn-part-mid-e", aisle_x=_AISLE_E, row=_ROW["middle"], kind="aisle"),
    )
    lines: list[object] = []
    for z in zones:
        lines.extend(
            row_stop_lines(
                z.id, aisle_x=_AISLE_W if z.id.endswith("w") else _AISLE_E, row=_ROW["middle"]
            )
        )
    wm = base_warehouse("map-partition", "Asymmetric partition").model_copy(
        update={"zones": zones, "stop_lines": tuple(lines)}
    )

    tasks = (
        _task("t-part-0", "stn-pick-a", "stn-drop-b"),
        _task("t-part-1", "stn-pick-b", "stn-drop-c"),
        _task("t-part-2", "stn-pick-c", "stn-drop-a"),
    )
    starts = (
        RobotStart(
            robot_id=_R1, pose=Pose2(x=_AISLE_W, y=17.1, theta=_WEST), assigned_task_id="t-part-0"
        ),
        RobotStart(
            robot_id=_R2, pose=Pose2(x=_AISLE_E, y=17.1, theta=_WEST), assigned_task_id="t-part-1"
        ),
        RobotStart(
            robot_id=_R3, pose=Pose2(x=_AISLE_M, y=6.9, theta=_EAST), assigned_task_id="t-part-2"
        ),
    )
    faults = (
        partition_fault(
            "fx-part-a-to-b",
            _R1,
            _R2,
            start_s=25.0,
            duration_s=45.0,
            invariant=(
                "amr-01 retains occupancy of any held zone and stops before a stop line it can no "
                "longer confirm, while amr-03 keeps delivering"
            ),
        ),
    )
    return make_scenario(
        scenario_id="asymmetric-partition",
        name="Asymmetric coordination partition",
        description="amr-01 -> amr-02 is cut for 45 s while amr-03 stays fully connected.",
        kind="fault",
        intent=IntentDescription(
            goal="Show that a directed channel cut degrades only the affected pair.",
            expect=(
                "The partitioned robots stop safely before any unconfirmed stop line; the third "
                "robot continues delivering. No conflicting motion authority is created."
            ),
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        faults=faults,
        policy=default_policy(),
        max_sim_time_s=600.0,
    )


# --------------------------------------------------------------------------- 7
def infeasible_layout() -> Scenario:
    """A structurally valid map whose correct result is a safe, explained stop.

    A full-height wall seals the drop row off from the pickup row, so no route
    exists. The scenario runs only as an explicitly labelled expected-failure
    experiment, is never eligible for a successful task-completion comparison, and
    must not bypass any geometry or authority invariant.
    """
    base = base_warehouse("map-infeasible", "Infeasible layout (diagnostic)")
    wall = obstacle("obs-wall-seal", ObstacleKind.WALL, 20.4, 9.0, 0.6, 18.0)
    wm = base.model_copy(update={"obstacles": (*base.obstacles, wall)})

    tasks = (_task("t-infeasible-0", "stn-pick-a", "stn-drop-a", service_s=4.0),)
    starts = (
        RobotStart(
            robot_id=_R1, pose=Pose2(x=2.5, y=6.9, theta=_EAST), assigned_task_id="t-infeasible-0"
        ),
        RobotStart(robot_id=_R2, pose=Pose2(x=2.5, y=11.9, theta=_EAST)),
        RobotStart(robot_id=_R3, pose=Pose2(x=_AISLE_W, y=11.9, theta=_EAST)),
    )
    return make_scenario(
        scenario_id="infeasible-layout",
        name="Infeasible layout (expected safe stop)",
        description=(
            "The drop row is sealed off from the pickup row. The correct outcome is a safe, "
            "explained stop, never a completed delivery and never a false success."
        ),
        kind="diagnostic",
        intent=IntentDescription(
            goal="Demonstrate that an infeasible workload produces a safe explained stop.",
            expect=(
                "The planner reports UNREACHABLE with an explicit reason. No robot claims a "
                "delivery. The run outcome is expected_safe_stop and the run is excluded from "
                "successful-completion comparisons."
            ),
            expected_failure_reason="no geometrically feasible route from the pickup row to the drop row",
        ),
        map=wm,
        robot_ids=_THREE,
        starts=starts,
        tasks=tasks,
        policy=default_policy(),
        max_sim_time_s=180.0,
    )


_BUILDERS = {
    "headon-aisle": headon_aisle,
    "three-way-junction": three_way_junction,
    "cycle-with-holding": cycle_with_holding,
    "blocked-exit": blocked_exit,
    "dynamic-arrivals": dynamic_arrivals,
    "asymmetric-partition": asymmetric_partition,
    "infeasible-layout": infeasible_layout,
}

SCENARIOS: dict[str, Scenario] = {name: fn() for name, fn in _BUILDERS.items()}


def scenario_ids() -> tuple[str, ...]:
    return tuple(sorted(SCENARIOS))


def build(scenario_id: str) -> Scenario:
    try:
        return SCENARIOS[scenario_id]
    except KeyError as exc:
        raise KeyError(
            f"unknown scenario {scenario_id!r}; known: {', '.join(scenario_ids())}"
        ) from exc


def build_all() -> dict[str, Scenario]:
    return dict(SCENARIOS)


# The footprint is part of the builder vocabulary even where unused here.
_ = AMR_FOOTPRINT

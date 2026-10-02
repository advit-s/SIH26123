"""Scenario validation, reported as one actionable list.

Two severities, deliberately separated because they mean different things:

``STRUCTURAL``
    The scenario cannot be launched, full stop. Duplicate ids, footprint-obstacle
    intersection, invalid references, overlapping initial bodies, inconsistent zone
    definitions, undersized passages, absent safe exits, incompatible versions.

``WORKLOAD``
    The layout is structurally fine but the *workload* is unsatisfiable. An
    unreachable destination, a blocked route or a blocked exit. This may be run
    only as an explicitly labelled expected-failure experiment, and it is never
    eligible for a successful task-completion comparison. It must still not bypass
    any geometry or authority invariant.

Where full feasibility cannot be established (proving multi-robot reachability is
undecidable in general) we state the limit rather than claiming a verdict.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum

from niharamesh.domain.geometry import OrientedBox, circle_rect_overlap, sat_overlap
from niharamesh.domain.map import ObstacleKind, WarehouseMap, Zone
from niharamesh.domain.scenario import Scenario
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "Severity",
    "ValidationIssue",
    "ValidationReport",
    "estimate_reachability",
    "validate_berth_separation",
    "validate_scenario",
    "validate_zone_disjointness",
]


class Severity(StrEnum):
    STRUCTURAL = "structural"
    """Blocks launch. The scenario cannot be executed as authored."""

    WORKLOAD = "workload"
    """The layout is sound but the workload may be unsatisfiable. Blocks launch
    unless the scenario is explicitly marked as an expected-failure experiment."""

    WARNING = "warning"
    """Launchable, but an operator should know."""


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    #: What the operator can actually do about it.
    remedy: str = ""
    entity: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "severity": self.severity.value,
            "message": self.message,
            "remedy": self.remedy,
            "entity": self.entity,
        }


@dataclass(slots=True)
class ValidationReport:
    scenario_id: str
    revision: int
    issues: list[ValidationIssue] = field(default_factory=list)
    #: Stated limits of what was actually checked.
    checks_not_performed: list[str] = field(default_factory=list)

    @property
    def structural_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.STRUCTURAL]

    @property
    def workload_issues(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WORKLOAD]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity is Severity.WARNING]

    @property
    def launchable(self) -> bool:
        """A non-diagnostic scenario must have no structural or workload issues."""
        return not self.structural_issues and not self.workload_issues

    @property
    def diagnostic_allowed(self) -> bool:
        """Only workload-level problems may be run, and only as a labelled failure."""
        return not self.structural_issues

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "revision": self.revision,
            "launchable": self.launchable,
            "diagnostic_allowed": self.diagnostic_allowed,
            "issue_count": len(self.issues),
            "structural_count": len(self.structural_issues),
            "workload_count": len(self.workload_issues),
            "warning_count": len(self.warnings),
            "issues": [i.as_dict() for i in self.issues],
            "checks_not_performed": list(self.checks_not_performed),
        }


def validate_zone_disjointness(wm: WarehouseMap) -> list[ValidationIssue]:
    """Exclusive zones must have disjoint protected geometry.

    Two different zone ids must not be able to authorise physically conflicting
    movements. Where a traversal needs two adjacent resources with no safe berth
    between them, they must be authored as one compound zone instead.
    """
    issues: list[ValidationIssue] = []
    zones = wm.zones
    for i, a in enumerate(zones):
        for b in zones[i + 1 :]:
            if _bounds_overlap(a, b):
                issues.append(
                    ValidationIssue(
                        code="zone_protected_geometry_overlaps",
                        severity=Severity.STRUCTURAL,
                        message=(
                            f"zones {a.id!r} and {b.id!r} have overlapping protected geometry, so "
                            "two different zone ids could authorise physically conflicting movements"
                        ),
                        remedy=(
                            "shrink one protected rectangle, or author the pair as a single "
                            "compound zone using 'members'"
                        ),
                        entity=a.id,
                    )
                )
    claimed_members = [m for z in zones for m in z.members]
    if len(set(claimed_members)) != len(claimed_members):
        dupes = sorted({m for m in claimed_members if claimed_members.count(m) > 1})
        issues.append(
            ValidationIssue(
                code="zone_member_claimed_twice",
                severity=Severity.STRUCTURAL,
                message=f"zone id(s) {dupes} are claimed as a compound member by more than one zone",
                remedy="each component zone may belong to at most one compound zone",
            )
        )
    return issues


def _bounds_overlap(a: Zone, b: Zone) -> bool:
    ax0, ay0, ax1, ay1 = a.protected_bounds
    bx0, by0, bx1, by1 = b.protected_bounds
    return not (ax1 <= bx0 or bx1 <= ax0 or ay1 <= by0 or by1 <= ay0)


def validate_berth_separation(wm: WarehouseMap) -> list[ValidationIssue]:
    """A berth that lies inside a zone protected area is not a safe waiting place.

    Such a berth would let a robot stop while still holding another robot's
    resource, which is exactly the situation the protocol is designed to avoid.
    """
    issues: list[ValidationIssue] = []
    for b in wm.berths:
        for z in wm.zones:
            if z.contains_point(b.pose.x, b.pose.y):
                issues.append(
                    ValidationIssue(
                        code="berth_inside_zone",
                        severity=Severity.STRUCTURAL,
                        message=(
                            f"berth {b.id!r} lies inside zone {z.id!r}'s protected area, so a robot "
                            "stopping there would still hold another robot's resource"
                        ),
                        remedy="move the berth into a cross aisle outside every zone",
                        entity=b.id,
                    )
                )
    for z in wm.zones:
        if z.exit_berth_id is None:
            issues.append(
                ValidationIssue(
                    code="zone_without_exit_berth",
                    severity=Severity.WARNING,
                    message=f"zone {z.id!r} declares no safe exit berth",
                    remedy="name a berth outside every other zone so a holder can always come to rest",
                    entity=z.id,
                )
            )
    return issues


def validate_aisle_widths(wm: WarehouseMap) -> list[ValidationIssue]:
    """Flag passages narrower than the declared aisle width."""
    issues: list[ValidationIssue] = []
    shelves = [o for o in wm.obstacles if o.kind in (ObstacleKind.SHELF, ObstacleKind.WALL)]
    minimum = wm.nominal_aisle_width_m
    for i, a in enumerate(shelves):
        for b in shelves[i + 1 :]:
            if b.dynamic or a.dynamic:
                continue
            ax0, ay0 = a.pose.x - a.length_m / 2, a.pose.y - a.width_m / 2
            ax1, ay1 = a.pose.x + a.length_m / 2, a.pose.y + a.width_m / 2
            bx0, by0 = b.pose.x - b.length_m / 2, b.pose.y - b.width_m / 2
            bx1, by1 = b.pose.x + b.length_m / 2, b.pose.y + b.width_m / 2
            dx = max(ax0 - bx1, bx0 - ax1, 0.0)
            dy = max(ay0 - by1, by0 - ay1, 0.0)
            gap = math.hypot(dx, dy)
            if 0.0 < gap < minimum - 1e-6:
                issues.append(
                    ValidationIssue(
                        code="undersized_passage",
                        severity=Severity.STRUCTURAL,
                        message=(
                            f"passage of {gap:.2f} m between {a.id!r} and {b.id!r} is narrower than "
                            f"the declared {minimum:.2f} m aisle width"
                        ),
                        remedy=(
                            "widen the passage or shrink a shelf; the declared footprint needs room to turn"
                        ),
                        entity=a.id,
                    )
                )
    return issues


def _footprint_box(wm: WarehouseMap, scenario: Scenario, robot_id: str) -> OrientedBox:
    identity = scenario.robot(robot_id)
    fp = identity.footprint
    start = scenario.start_of(robot_id)
    theta = start.pose.theta
    return OrientedBox(
        start.pose.x + fp.payload_offset_m * math.cos(theta),
        start.pose.y + fp.payload_offset_m * math.sin(theta),
        theta,
        max(fp.length_m, fp.payload_length_m),
        fp.width_m,
    )


def validate_starts(wm: WarehouseMap, scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    boxes: list[tuple[str, OrientedBox]] = []
    for start in scenario.starts:
        box = _footprint_box(wm, scenario, start.robot_id)
        boxes.append((start.robot_id, box))
        for o in wm.obstacles:
            if sat_overlap(box, OrientedBox(o.pose.x, o.pose.y, o.pose.theta, o.length_m, o.width_m)):
                issues.append(
                    ValidationIssue(
                        code="start_overlaps_obstacle",
                        severity=Severity.STRUCTURAL,
                        message=(
                            f"robot {start.robot_id!r} starts with its footprint inside obstacle {o.id!r}"
                        ),
                        remedy="move the start pose to a clear berth",
                        entity=start.robot_id,
                    )
                )
        if not (
            wm.boundary.min_x <= box.cx <= wm.boundary.max_x
            and wm.boundary.min_y <= box.cy <= wm.boundary.max_y
        ):
            issues.append(
                ValidationIssue(
                    code="start_outside_boundary",
                    severity=Severity.STRUCTURAL,
                    message=f"robot {start.robot_id!r} starts outside the map boundary",
                    remedy="place the start inside the usable envelope",
                    entity=start.robot_id,
                )
            )
    for i, (a_id, a_box) in enumerate(boxes):
        for b_id, b_box in boxes[i + 1 :]:
            if sat_overlap(a_box, b_box):
                issues.append(
                    ValidationIssue(
                        code="initial_bodies_overlap",
                        severity=Severity.STRUCTURAL,
                        message=f"robots {a_id!r} and {b_id!r} start with overlapping footprints",
                        remedy="separate the start poses by at least one body length",
                        entity=a_id,
                    )
                )
    return issues


def _station_reference_valid(scenario: Scenario, station_id: str, task_id: str) -> bool:
    try:
        scenario.map.station(station_id)
    except KeyError:
        return False
    return True


def estimate_reachability(
    wm: WarehouseMap, start: tuple[float, float], goal: tuple[float, float], clearance_m: float
) -> bool:
    """Conservative single-robot reachability estimate by BFS on a coarse grid.

    This is deliberately described as an *estimate*: it is a sampled
    configuration-space flood fill, not a completeness proof. The validator
    reports the limit rather than claiming a verdict.
    """
    step = 0.25
    from collections import deque

    obstacles = [OrientedBox(o.pose.x, o.pose.y, o.pose.theta, o.length_m, o.width_m) for o in wm.obstacles]
    boundary = wm.boundary

    def free(x: float, y: float) -> bool:
        if not (boundary.min_x + clearance_m <= x <= boundary.max_x - clearance_m):
            return False
        if not (boundary.min_y + clearance_m <= y <= boundary.max_y - clearance_m):
            return False
        return not any(circle_rect_overlap(x, y, clearance_m, o) for o in obstacles)

    sx, sy = start
    gx, gy = goal
    if not free(sx, sy) or not free(gx, gy):
        return False
    if math.hypot(gx - sx, gy - sy) <= step:
        return True
    seen = {(round(sx / step), round(sy / step))}
    queue: deque[tuple[int, int]] = deque([(round(sx / step), round(sy / step))])
    goal_cell = (round(gx / step), round(gy / step))
    neighbours = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))
    while queue:
        cx, cy = queue.popleft()
        if (cx, cy) == goal_cell:
            return True
        for dx, dy in neighbours:
            nxt = (cx + dx, cy + dy)
            if nxt in seen:
                continue
            seen.add(nxt)
            if free(nxt[0] * step, nxt[1] * step):
                queue.append(nxt)
    return False


def validate_tasks(wm: WarehouseMap, scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    clearance = max(r.footprint.clearance_radius_m() for r in scenario.robots)
    for task in scenario.tasks:
        for label, sid in (("pickup", task.pickup_station_id), ("drop", task.drop_station_id)):
            if not _station_reference_valid(scenario, sid, task.task_id):
                issues.append(
                    ValidationIssue(
                        code="task_references_unknown_station",
                        severity=Severity.STRUCTURAL,
                        message=f"task {task.task_id!r} {label} station {sid!r} does not exist",
                        remedy="reference an existing station id",
                        entity=task.task_id,
                    )
                )
        if task.release_at_s > scenario.max_sim_time_s:
            issues.append(
                ValidationIssue(
                    code="task_released_after_deadline",
                    severity=Severity.WORKLOAD,
                    message=(
                        f"task {task.task_id!r} is released at {task.release_at_s}s but the run ends "
                        f"at {scenario.max_sim_time_s}s, so it can never be delivered"
                    ),
                    remedy="release the task earlier or extend max_sim_time_s",
                    entity=task.task_id,
                )
            )
    # Reachability between stations, estimated.
    stations = {s.id: s for s in wm.stations}
    checked = 0
    for task in scenario.tasks:
        a, b = stations.get(task.pickup_station_id), stations.get(task.drop_station_id)
        if a is None or b is None:
            continue
        checked += 1
        if not estimate_reachability(wm, (a.pose.x, a.pose.y), (b.pose.x, b.pose.y), clearance):
            issues.append(
                ValidationIssue(
                    code="task_destination_unreachable",
                    severity=Severity.WORKLOAD,
                    message=(
                        f"task {task.task_id!r} asks for {a.id!r} -> {b.id!r} but no single-robot route "
                        "exists at the declared clearance. The correct outcome for this workload is a "
                        "safe explained stop."
                    ),
                    remedy=(
                        "if that is intended, mark the scenario kind='diagnostic' and set "
                        "intent.expected_failure_reason so it is excluded from success comparisons"
                    ),
                    entity=task.task_id,
                )
            )
    if checked:
        issues.append(
            ValidationIssue(
                code="reachability_is_estimated",
                severity=Severity.WARNING,
                message=(
                    f"reachability for {checked} task leg(s) was estimated by a 0.25 m "
                    "configuration-space flood fill. This is not a completeness proof, and "
                    "multi-robot reachability was not analysed at all."
                ),
                remedy="treat an UNREACHABLE planner result at run time as authoritative for that leg",
            )
        )
    return issues


def validate_faults(scenario: Scenario) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    robot_ids = {r.robot_id for r in scenario.robots}
    for f in scenario.faults:
        for role, rid in (
            ("sender", f.target.sender),
            ("receiver", f.target.receiver),
            ("robot", f.target.robot),
        ):
            if rid is not None and rid not in robot_ids:
                issues.append(
                    ValidationIssue(
                        code="fault_targets_unknown_robot",
                        severity=Severity.STRUCTURAL,
                        message=f"fault {f.fault_id!r} targets unknown robot {rid!r} as {role}",
                        remedy=f"use one of: {', '.join(sorted(robot_ids))}",
                        entity=f.fault_id,
                    )
                )
        if f.target.zone_id is not None:
            try:
                scenario.map.zone(f.target.zone_id)
            except KeyError:
                issues.append(
                    ValidationIssue(
                        code="fault_targets_unknown_zone",
                        severity=Severity.STRUCTURAL,
                        message=f"fault {f.fault_id!r} targets unknown zone {f.target.zone_id!r}",
                        remedy="reference an existing zone id",
                        entity=f.fault_id,
                    )
                )
        if f.end_at_s > scenario.max_sim_time_s:
            issues.append(
                ValidationIssue(
                    code="fault_outlives_run",
                    severity=Severity.WARNING,
                    message=(
                        f"fault {f.fault_id!r} ends at {f.end_at_s}s but the run ends at "
                        f"{scenario.max_sim_time_s}s, so its expected invariant may never be observed"
                    ),
                    remedy="shorten the fault or extend the run",
                    entity=f.fault_id,
                )
            )
    return issues


def validate_scenario(scenario: Scenario) -> ValidationReport:
    """Full validation. Every issue is collected; nothing is silently repaired."""
    report = ValidationReport(scenario_id=scenario.scenario_id, revision=scenario.revision)
    report.checks_not_performed = [
        "multi-robot reachability and deadlock-freedom are not analysed statically",
        "temporal feasibility of every planned traversal is not analysed statically",
        "sensor observability coverage is not analysed statically",
    ]

    if scenario.schema_version.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        report.issues.append(
            ValidationIssue(
                code="schema_version_incompatible",
                severity=Severity.STRUCTURAL,
                message=(
                    f"scenario schema_version {scenario.schema_version!r} is not compatible with "
                    f"{SCHEMA_VERSION!r}"
                ),
                remedy="re-author the scenario against the current schema; it is never auto-migrated",
            )
        )

    if len(scenario.robots) < 3:
        report.issues.append(
            ValidationIssue(
                code="fewer_than_three_robots",
                severity=Severity.WARNING,
                message=(
                    f"scenario declares {len(scenario.robots)} robot(s); the demonstration requirement "
                    "is at least three independently executing agents"
                ),
                remedy="add robots to exercise the decentralised coordination path",
            )
        )

    report.issues.extend(validate_zone_disjointness(scenario.map))
    report.issues.extend(validate_berth_separation(scenario.map))
    report.issues.extend(validate_aisle_widths(scenario.map))
    report.issues.extend(validate_starts(scenario.map, scenario))
    report.issues.extend(validate_tasks(scenario.map, scenario))
    report.issues.extend(validate_faults(scenario))

    if scenario.kind == "diagnostic" and not scenario.intent.expected_failure_reason:
        report.issues.append(
            ValidationIssue(
                code="diagnostic_without_reason",
                severity=Severity.STRUCTURAL,
                message="a diagnostic scenario must state intent.expected_failure_reason",
                remedy="state what the safe outcome is, so it is never mistaken for a real result",
            )
        )
    if scenario.kind != "diagnostic" and scenario.intent.expected_failure_reason:
        report.issues.append(
            ValidationIssue(
                code="unexpected_failure_reason",
                severity=Severity.WARNING,
                message=(
                    "a non-diagnostic scenario declares expected_failure_reason; runs of it will be "
                    "excluded from successful-completion comparisons"
                ),
                remedy="clear the reason if this scenario is expected to succeed",
            )
        )
    if scenario.simulation.physical_actuation_enabled:
        report.issues.append(
            ValidationIssue(
                code="physical_actuation_enabled",
                severity=Severity.WARNING,
                message=(
                    "physical actuation is enabled for this scenario. It requires configured devices, "
                    "a controlled test area and operator authorisation, and it is refused outright "
                    "while any safety-weakening ablation flag is set."
                ),
                remedy="leave NIHARA_PHYSICAL_ACTUATION_ENABLED=false for demonstrations",
            )
        )
    if scenario.simulation.features.unsafe_research_variant:
        report.issues.append(
            ValidationIssue(
                code="unsafe_research_flags",
                severity=Severity.WARNING,
                message=(
                    f"unsafe research ablations active: {list(scenario.simulation.features.unsafe_flags)}. "
                    "Results from such a run are research observations, never evidence of safety."
                ),
                remedy="turn the ablations off for any run whose result is presented as a safety claim",
            )
        )
    return report

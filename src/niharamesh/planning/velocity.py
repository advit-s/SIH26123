"""Curvature-aware speed profile along a planned route.

This module turns a geometric plan into per-waypoint speed targets. It is an
**estimator**, not a controller and not a safety decision:

* the corner law ``v_corner = v_max * cos(|dtheta| / 2)`` is a declared
  approximation of a differential drive's turn geometry. It is zero at a
  hairpin and ``v_max`` on a straight, which is the right qualitative shape, but
  it is not the robot's actual lateral-acceleration envelope and must not be
  presented as one.
* the braking pass computes what ``decel_mps2`` *allows*, not what the robot
  will achieve. If a stop line is closer than the stopping distance allows, this
  module still reports the best target it can and says nothing about the
  consequence - the safety gate owns that refusal (AGENTS.md rule 7).

``brake_only`` marks the *braking onset* waypoint for each crossed stop line: the
last waypoint before the line. Its ``target_speed_mps`` is the largest speed from
which ``decel_mps2`` still stops the robot on the line. For a distant line that is
the cruise speed, and the flag - not the number - is the information. That flag is
a *request* to brake from here on; crossing the line without the named authority is
still a violation the evaluator detects independently.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from niharamesh.domain.config import ActuatorModel
from niharamesh.domain.geometry import segment_intersects_segment
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import Pose2
from niharamesh.domain.units import angle_difference, wrap_angle
from niharamesh.planning.path import PathPlan

__all__ = ["Vec2", "Waypoint", "velocity_profile"]

Vec2 = tuple[float, float]


@dataclass(frozen=True, slots=True)
class Waypoint:
    """One commanded pose-and-speed target along the route."""

    x: float
    y: float
    target_heading: float
    target_speed_mps: float
    brake_only: bool = False

    def as_tuple(self) -> tuple[float, float, float, float, bool]:
        return (self.x, self.y, self.target_heading, self.target_speed_mps, self.brake_only)


def velocity_profile(
    plan: PathPlan,
    start_pose: Pose2,
    actuator_model: ActuatorModel,
    *,
    warehouse_map: WarehouseMap | None = None,
) -> tuple[Waypoint, ...]:
    """Speed-limited targets for every waypoint of *plan*.

    Parameters
    ----------
    plan:
        The geometric route. Its first waypoint is replaced by ``start_pose`` if
        they differ, because the profile describes where the robot *is*, not
        where the last plan said it was.
    actuator_model:
        Declared ``max_linear_mps``, ``accel_mps2`` and ``decel_mps2``.
    warehouse_map:
        Used only to locate stop lines the route crosses. When omitted the
        profile has **no** ``brake_only`` waypoints; that is reported by
        :attr:`Waypoint.brake_only` staying false everywhere, not hidden.
    """
    v_max = actuator_model.max_linear_mps
    points = _align_to_start(plan.waypoints, start_pose)
    if len(points) < 2:
        return (
            Waypoint(
                x=points[0][0],
                y=points[0][1],
                target_heading=start_pose.theta,
                target_speed_mps=0.0,
                brake_only=False,
            ),
        )

    headings = _headings(points, start_pose.theta)
    corners = [0.0] * len(points)
    for k in range(len(points)):
        before = angle_difference(headings[k], headings[k - 1]) if k > 0 else 0.0
        after = angle_difference(headings[k + 1], headings[k]) if k + 1 < len(points) else 0.0
        corners[k] = max(abs(before), abs(after))
    speeds = [v_max * math.cos(0.5 * min(c, math.pi)) for c in corners]

    gaps = [math.dist(points[k], points[k + 1]) for k in range(len(points) - 1)]
    _backward_brake_pass(speeds, gaps, actuator_model.decel_mps2)
    _forward_accel_pass(speeds, gaps, actuator_model.accel_mps2)

    brake_flags = _brake_only_flags(points, warehouse_map)
    for index, distance_to_line in brake_flags.items():
        if index >= len(speeds):
            continue
        reachable = math.sqrt(max(0.0, 2.0 * actuator_model.decel_mps2 * distance_to_line))
        speeds[index] = min(speeds[index], reachable, v_max)
        speeds[index] = max(0.0, min(speeds[index], v_max))

    out: list[Waypoint] = []
    for k, point in enumerate(points):
        out.append(
            Waypoint(
                x=point[0],
                y=point[1],
                target_heading=headings[k],
                target_speed_mps=round(max(0.0, min(speeds[k], v_max)), 6),
                brake_only=k in brake_flags,
            )
        )
    return tuple(out)


def _align_to_start(waypoints: Sequence[Vec2], start_pose: Pose2) -> tuple[Vec2, ...]:
    points = tuple(waypoints)
    if math.dist(points[0], (start_pose.x, start_pose.y)) <= 1e-9:
        return points
    return ((start_pose.x, start_pose.y), *points[1:])


def _headings(points: Sequence[Vec2], start_theta: float) -> tuple[float, ...]:
    """Heading *of* each waypoint: into it from the previous one, out to the next."""
    out: list[float] = [wrap_angle(start_theta)]
    for k in range(len(points) - 1):
        out.append(_bearing(points[k], points[k + 1]))
    if len(points) > 1:
        out[-1] = _bearing(points[-2], points[-1])
    return tuple(out)


def _backward_brake_pass(speeds: list[float], gaps: Sequence[float], decel_mps2: float) -> None:
    """Enforce ``v[i]^2 <= v[i+1]^2 + 2 * decel * gap`` walking backwards."""
    for k in range(len(speeds) - 2, -1, -1):
        gap = gaps[k]
        limit = math.sqrt(speeds[k + 1] ** 2 + 2.0 * decel_mps2 * gap)
        speeds[k] = min(speeds[k], limit)


def _forward_accel_pass(speeds: list[float], gaps: Sequence[float], accel_mps2: float) -> None:
    """Cap speeds so each step is reachable from the previous one by accelerating."""
    for k in range(1, len(speeds)):
        gap = gaps[k - 1]
        if gap <= 0.0:
            continue
        time_s = _solve_speed_time(speeds[k - 1], gap, accel_mps2)
        speeds[k] = min(speeds[k], speeds[k - 1] + accel_mps2 * time_s)


def _solve_speed_time(entry_speed: float, gap: float, accel_mps2: float) -> float:
    """Time to cross *gap* starting at *entry_speed* and accelerating at *accel*.

    Solves ``gap = v0*t + 0.5*a*t^2`` for ``t >= 0``. When the target speed is
    already below the entry speed the quadratic has no non-negative root, and the
    physically meaningful answer is the time the entry speed alone would take.
    """
    if entry_speed <= 0.0:
        return math.sqrt(max(0.0, 2.0 * gap / accel_mps2)) if accel_mps2 > 0 else 0.0
    if accel_mps2 <= 0.0:
        return gap / entry_speed
    a = 0.5 * accel_mps2
    disc = entry_speed**2 + 2.0 * a * gap
    return (-entry_speed + math.sqrt(disc)) / accel_mps2


def _brake_only_flags(points: Sequence[Vec2], warehouse_map: WarehouseMap | None) -> dict[int, float]:
    """Index of the braking-onset waypoint for each crossed line -> distance to it.

    For a crossing in segment ``k`` the onset is waypoint ``k``: the last waypoint
    before the line. Its ``target_speed_mps`` is the largest speed from which
    ``decel_mps2`` still stops the robot *on* the line, which for a distant line is
    the cruise speed - and that is the honest answer. When the approach is tight the
    same rule reduces the target; the tests assert both cases so neither is
    quietly omitted.
    """
    if warehouse_map is None or len(points) < 2:
        return {}
    flags: dict[int, float] = {}
    for line in warehouse_map.stop_lines:
        a, b = line.start, line.end
        for k in range(len(points) - 1):
            if not segment_intersects_segment(points[k], points[k + 1], a, b):
                continue
            flags.setdefault(k, _distance_to_segment(points[k], a, b))
            break
    return flags


def _bearing(a: Vec2, b: Vec2) -> float:
    return wrap_angle(math.atan2(b[1] - a[1], b[0] - a[0]))


def _distance_to_segment(point: Vec2, a: Vec2, b: Vec2) -> float:
    vx, vy = b[0] - a[0], b[1] - a[1]
    wx, wy = point[0] - a[0], point[1] - a[1]
    denom = vx * vx + vy * vy
    t = 0.0 if denom <= 1e-18 else max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    return math.hypot(point[0] - (a[0] + t * vx), point[1] - (a[1] + t * vy))

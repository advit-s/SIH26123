"""Range sensing and localisation estimate generation.

What a robot is allowed to find out
-----------------------------------
Only what the declared sensor model can physically measure: range and bearing to
whatever is inside the field of view, within range. There is no path to a
peer's pose here -- a ray that lands on another robot yields a distance, which
is what a real lidar returns. Whoever wants a peer's position must get it over
the peer channel, with provenance and age attached.

Honest dropout
--------------
``dropout_probability`` empties the whole scan and sets
``SensorObservation.dropped``. It does **not** report phantom clear rays. A
model that turned a dropped beam into "nothing within range" would let a failed
sensor look like a clear aisle, which is the most dangerous possible default for
a safety monitor. A dropped scan is an explicit "I have no data", which the
agent must handle by stopping, not by proceeding.

Two timestamps, never one
-------------------------
``observed_at_ns`` is when the measurement was taken -- ``sim_time_ns`` minus
the declared latency. ``delivered_at_ns`` is when it reached the agent. They
differ by exactly the modelled latency, and neither is ever quietly replaced by
"now". Fusing a stale pose with a fresh receipt is how an old message becomes
current information, which the whole freshness argument in this project exists to
prevent.

Determinism
-----------
Every draw comes from a *named* stream in :class:`niharamesh.clocks.SeededStreams`
whose name identifies the robot. Two runs with the same seed and the same call
sequence produce byte-identical observations; two robots never share a stream, so
one robot's noise cannot perturb another's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from niharamesh.clocks import SeededStreams
from niharamesh.domain.config import SensorModel
from niharamesh.domain.geometry import OrientedBox, Pose, Vec2
from niharamesh.domain.map import MapBoundary, WarehouseMap
from niharamesh.domain.pose import Footprint, Pose2, PoseEstimate, UncertaintyModel
from niharamesh.domain.units import TimeDomain, wrap_angle
from niharamesh.ports import RangeRay, SensorObservation

__all__ = [
    "NS_PER_S",
    "SensorScene",
    "cast_rays",
    "generate_observation",
    "generate_pose_estimate",
    "nearest_surface",
    "ray_boundary_distance_m",
    "ray_box_distance_m",
]

NS_PER_S: Final[int] = 1_000_000_000
_EPS: Final[float] = 1e-12


@dataclass(frozen=True, slots=True)
class SensorScene:
    """Everything a sensor ray can land on, in the map frame.

    The caller assembles this deliberately. ``other_bodies`` holds the chassis
    and payload rectangles of the *other* robots; only their ranges are ever
    reported, so holding this object does not hand a robot a peer's pose. The
    observing robot's own body must **not** appear in it -- see
    :func:`generate_observation`.
    """

    map: WarehouseMap
    other_bodies: tuple[OrientedBox, ...] = ()


def obstacle_boxes(world_map: WarehouseMap) -> tuple[OrientedBox, ...]:
    """Static and temporary obstacles as oriented rectangles, in map order."""
    return tuple(
        OrientedBox(
            obstacle.pose.x,
            obstacle.pose.y,
            obstacle.pose.theta,
            obstacle.length_m,
            obstacle.width_m,
        )
        for obstacle in world_map.obstacles
    )


def ray_box_distance_m(origin: Vec2, bearing_rad: float, box: OrientedBox) -> float:
    """Distance from *origin* along a ray to the first contact with *box*.

    Returns ``0.0`` when the origin is already inside the box and ``math.inf``
    when the ray misses. Implemented as the standard 2D slab test in the box's
    own frame, so it is independent of the rectangle's orientation.
    """
    dx = math.cos(bearing_rad)
    dy = math.sin(bearing_rad)
    c, s = math.cos(-box.theta), math.sin(-box.theta)
    ox = origin[0] - box.cx
    oy = origin[1] - box.cy
    local_x = ox * c - oy * s
    local_y = ox * s + oy * c
    dir_x = dx * c - dy * s
    dir_y = dx * s + dy * c

    t_near = -math.inf
    t_far = math.inf
    for position, direction, half in (
        (local_x, dir_x, box.half_length),
        (local_y, dir_y, box.half_width),
    ):
        if abs(direction) < _EPS:
            # Ray parallel to this slab pair: a miss unless it already straddles.
            if position < -half or position > half:
                return math.inf
            continue
        t1 = (-half - position) / direction
        t2 = (half - position) / direction
        if t1 > t2:
            t1, t2 = t2, t1
        t_near = max(t_near, t1)
        t_far = min(t_far, t2)
        if t_near > t_far:
            return math.inf
    if t_far < 0.0:
        return math.inf
    return max(0.0, t_near)


def ray_boundary_distance_m(origin: Vec2, bearing_rad: float, boundary: MapBoundary) -> float:
    """Distance along a ray to the usable map envelope.

    An origin outside the envelope gets ``0.0``: the robot is already off the
    map, which the evaluator reports as a boundary violation rather than as a
    wall it cannot see.
    """
    ox, oy = origin
    if not (boundary.min_x <= ox <= boundary.max_x and boundary.min_y <= oy <= boundary.max_y):
        return 0.0
    dx = math.cos(bearing_rad)
    dy = math.sin(bearing_rad)
    best = math.inf
    if dx > _EPS:
        best = min(best, (boundary.max_x - ox) / dx)
    elif dx < -_EPS:
        best = min(best, (boundary.min_x - ox) / dx)
    if dy > _EPS:
        best = min(best, (boundary.max_y - oy) / dy)
    elif dy < -_EPS:
        best = min(best, (boundary.min_y - oy) / dy)
    return max(0.0, best)


def nearest_surface(
    scene: SensorScene,
    origin: Vec2,
    bearing_rad: float,
    range_m: float,
    *,
    boxes: tuple[OrientedBox, ...] | None = None,
) -> tuple[float, str]:
    """Closest surface along a ray, clamped to *range_m*.

    Returns ``(distance, kind)`` where kind is ``"obstacle"``, ``"boundary"``,
    ``"robot"`` or ``"free"``. ``"free"`` means only that nothing was detected
    within the sensor's range; it is not a safety statement.
    """
    static = obstacle_boxes(scene.map) if boxes is None else boxes
    best = ray_boundary_distance_m(origin, bearing_rad, scene.map.boundary)
    kind = "boundary"
    for box in static:
        dist = ray_box_distance_m(origin, bearing_rad, box)
        if dist < best:
            best = dist
            kind = "obstacle"
    for body in scene.other_bodies:
        dist = ray_box_distance_m(origin, bearing_rad, body)
        if dist < best:
            best = dist
            kind = "robot"
    if best >= range_m:
        return range_m, "free"
    return best, kind


def cast_rays(
    scene: SensorScene,
    origin: Pose,
    sensor_model: SensorModel,
) -> tuple[RangeRay, ...]:
    """Complete noise-free scan across the declared field of view.

    Rays are emitted at fixed ``angular_resolution_rad`` steps starting at the
    left edge of the field of view, so the sample pattern is a pure function of
    the configuration -- two runs of the same scenario compare beam for beam.
    """
    static = obstacle_boxes(scene.map)
    half_fov = _half_fov(sensor_model)
    count = max(1, int(2 * half_fov / sensor_model.angular_resolution_rad))
    rays: list[RangeRay] = []
    for index in range(count + 1):
        bearing = wrap_angle(origin.theta - half_fov + index * sensor_model.angular_resolution_rad)
        distance, kind = nearest_surface(
            scene, (origin.x, origin.y), bearing, sensor_model.range_m, boxes=static
        )
        rays.append(RangeRay(bearing, distance, kind, 0, 0))
    return tuple(rays)


def generate_observation(
    world_geometry: SensorScene,
    robot_id: str,
    true_pose: Pose,
    footprint: Footprint,
    sim_time_ns: int,
    sensor_model: SensorModel,
    streams: SeededStreams,
    rng_stream_name: str,
) -> SensorObservation:
    """Build one :class:`SensorObservation` for one robot at one instant.

    ``rng_stream_name`` must identify this robot's scan stream (conventionally
    ``f"sensor/{robot_id}/scan"``). Passing a shared name would let one robot's
    draws shift another's, which is exactly the coupling named seeded streams
    exist to prevent.

    ``footprint`` is used as a guard, not a measurement: the observing robot's own
    body must be absent from ``world_geometry.other_bodies``. If it were present,
    the first beam would return a distance to the robot's own chassis and quietly
    reconstruct its exact pose, so that configuration is rejected loudly.
    """
    if sim_time_ns < 0:
        raise ValueError("sim_time_ns must be non-negative")
    _reject_own_body(world_geometry, true_pose, footprint, robot_id)

    rng = streams.stream(rng_stream_name)
    latency_ns = int(sensor_model.observation_latency_s * NS_PER_S)
    observed_at_ns = max(0, sim_time_ns - latency_ns)

    if rng.random() < sensor_model.dropout_probability:
        return SensorObservation(
            robot_id=robot_id,
            observed_at_ns=observed_at_ns,
            delivered_at_ns=sim_time_ns,
            rays=(),
            dropped=True,
        )

    static = obstacle_boxes(world_geometry.map)
    half_fov = _half_fov(sensor_model)
    count = max(1, int(2 * half_fov / sensor_model.angular_resolution_rad))
    sigma = sensor_model.range_noise_m

    rays: list[RangeRay] = []
    for index in range(count + 1):
        bearing = wrap_angle(
            true_pose.theta - half_fov + index * sensor_model.angular_resolution_rad
        )
        distance, kind = nearest_surface(
            world_geometry, (true_pose.x, true_pose.y), bearing, sensor_model.range_m, boxes=static
        )
        measured = distance + rng.gauss(0.0, sigma) if sigma > 0.0 else distance
        # A negative range is physically impossible. Clamping to zero reports
        # "in contact", which is what a surface at distance zero really means.
        rays.append(
            RangeRay(
                bearing_rad=bearing,
                distance_m=max(0.0, measured),
                kind=kind,
                observed_at_ns=observed_at_ns,
                age_ns=sim_time_ns - observed_at_ns,
            )
        )

    return SensorObservation(
        robot_id=robot_id,
        observed_at_ns=observed_at_ns,
        delivered_at_ns=sim_time_ns,
        rays=tuple(rays),
        dropped=False,
    )


def generate_pose_estimate(
    true_pose: Pose,
    map_id: str,
    sensor_model: SensorModel,
    streams: SeededStreams,
    rng_stream_name: str,
    observed_at_ns: int,
    time_domain: TimeDomain = TimeDomain.LOGICAL,
) -> PoseEstimate:
    """Noisy self-localisation estimate with an explicit uncertainty.

    ``observed_at_ns`` is passed in rather than computed here because the caller
    already knows when the fix was taken -- for a delayed scan that is *earlier*
    than the moment of delivery, and an estimate labelled with the arrival time
    would silently claim freshness it does not have.
    """
    if observed_at_ns < 0:
        raise ValueError("observed_at_ns must be non-negative")
    rng = streams.stream(rng_stream_name)
    sigma_m = sensor_model.position_sigma_m
    sigma_rad = sensor_model.heading_sigma_rad
    return PoseEstimate(
        map_id=map_id,
        pose=Pose2(
            x=true_pose.x + (rng.gauss(0.0, sigma_m) if sigma_m > 0.0 else 0.0),
            y=true_pose.y + (rng.gauss(0.0, sigma_m) if sigma_m > 0.0 else 0.0),
            theta=true_pose.theta + (rng.gauss(0.0, sigma_rad) if sigma_rad > 0.0 else 0.0),
        ),
        observed_at_ns=observed_at_ns,
        time_domain=time_domain,
        uncertainty=UncertaintyModel(
            kind="gaussian_sigma",
            sigma_m=sigma_m,
            sigma_rad=sigma_rad,
            source="simulated",
        ),
        fused=True,
    )


def _half_fov(sensor_model: SensorModel) -> float:
    return sensor_model.field_of_view_rad / 2.0


def _reject_own_body(
    scene: SensorScene, true_pose: Pose, footprint: Footprint, robot_id: str
) -> None:
    """Refuse a scene that literally contains the observing robot's own body.

    The test is exact equality against the observer's own footprint, not mere
    overlap. An overlap means a robot is touching or inside a neighbour, which is
    precisely the collision the evaluator needs to inspect; refusing to scan then
    would blind the very run that matters most. Exact equality, by contrast, can
    only come from a scene assembled with the observer's own body in it, and that
    would let the first beam reconstruct the robot's exact pose.
    """
    own = set(footprint.occupied_boxes(true_pose))
    for other in scene.other_bodies:
        if other in own:
            raise ValueError(
                f"scene for {robot_id!r} contains the observer's own body at its own "
                "pose; that would leak exact self-pose through the scan"
            )

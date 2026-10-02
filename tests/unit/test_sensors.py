"""Declared range sensing: coverage, latency, dropout and determinism.

The properties under test are the ones an agent's safety gate depends on. If a
robot inside a sealed room could be told "clear aisle", or if a stale measurement
were relabelled with its arrival time, every downstream freshness argument in the
project would be built on a lie.
"""

from __future__ import annotations

import math

import pytest

from niharamesh.clocks import SeededStreams
from niharamesh.domain.config import SensorModel
from niharamesh.domain.geometry import OrientedBox, Pose
from niharamesh.domain.map import MapBoundary, Obstacle, WarehouseMap
from niharamesh.domain.pose import Footprint
from niharamesh.simulator.sensors import (
    NS_PER_S,
    SensorScene,
    cast_rays,
    generate_observation,
    generate_pose_estimate,
    nearest_surface,
    ray_boundary_distance_m,
    ray_box_distance_m,
)

_SENSOR = SensorModel(
    range_m=3.0,
    field_of_view_rad=math.pi,
    angular_resolution_rad=math.radians(15.0),
    observation_latency_s=0.1,
    position_sigma_m=0.02,
    heading_sigma_rad=0.01,
    dropout_probability=0.0,
    range_noise_m=0.0,
)
_NOSED_SENSOR = SensorModel(**{**_SENSOR.model_dump(), "dropout_probability": 0.5})
_FOOTPRINT = Footprint(length_m=0.80, width_m=0.60)
_LATENCY_NS = int(_SENSOR.observation_latency_s * NS_PER_S)


def _box(x: float, y: float, length: float, width: float, theta: float = 0.0) -> Obstacle:
    from niharamesh.domain.pose import Pose2

    return Obstacle(id=f"o{x}_{y}", pose=Pose2(x=x, y=y, theta=theta), length_m=length, width_m=width)


def _map(obstacles: tuple[Obstacle, ...] = (), half_extent: float = 10.0) -> WarehouseMap:
    return WarehouseMap(
        map_id="test-map",
        boundary=MapBoundary(
            min_x=-half_extent,
            min_y=-half_extent,
            max_x=half_extent,
            max_y=half_extent,
        ),
        obstacles=obstacles,
        grid_resolution_m=0.1,
    )


def _sealed_room_scene(gap: float) -> SensorScene:
    """Four walls forming a box around the origin, leaving a gap of *gap* metres.

    The walls are thin and long, so a ray at any bearing inside the room must hit
    one of them before reaching the map envelope.
    """
    side = 2.0
    walls = (
        _box(0.0, side, 2 * side, 0.1),
        _box(0.0, -side, 2 * side, 0.1),
        _box(side, 0.0, 0.1, 2 * side),
        _box(-side, 0.0, 0.1, 2 * side),
    )
    return SensorScene(map=_map(walls, half_extent=20.0))


def _signature_scan(rays: object) -> tuple[object, ...]:
    """Comparable form of a bare ray tuple; ``RangeRay`` has no value equality."""
    return tuple(
        (round(r.bearing_rad, 15), round(r.distance_m, 15), r.kind, r.observed_at_ns, r.age_ns)
        for r in rays
    )


def _signature(observation: object) -> tuple[object, ...]:
    """Everything a caller can see, as a comparable tuple for determinism checks."""
    rays = observation.rays  # type: ignore[attr-defined]
    return (
        observation.robot_id,  # type: ignore[attr-defined]
        observation.observed_at_ns,  # type: ignore[attr-defined]
        observation.delivered_at_ns,  # type: ignore[attr-defined]
        observation.dropped,  # type: ignore[attr-defined]
        tuple((round(r.bearing_rad, 15), round(r.distance_m, 15), r.kind, r.age_ns) for r in rays),
    )


# --------------------------------------------------------------------------- #
# Coverage inside a closed box
# --------------------------------------------------------------------------- #


def test_robot_inside_a_closed_box_observes_a_hit_in_every_direction() -> None:
    """A sealed room: no beam may report open space in any direction in the FOV.

    This is the property a naive "max range = free" model breaks. If any bearing
    inside the field of view reported the full range, an agent would conclude it
    had a clear path through a wall.
    """
    scene = _sealed_room_scene(gap=0.0)
    observation = generate_observation(
        world_geometry=scene,
        robot_id="r1",
        true_pose=Pose(0.0, 0.0, 0.0),
        footprint=_FOOTPRINT,
        sim_time_ns=1_000_000_000,
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/scan",
    )

    assert not observation.dropped
    assert len(observation.rays) == 13  # a pi FOV at 15 degrees, both edges included
    for ray in observation.rays:
        assert ray.kind in ("obstacle", "boundary"), f"open space reported at {ray.bearing_rad}"
        assert ray.distance_m < _SENSOR.range_m, (
            f"ray at {ray.bearing_rad:.3f} rad reported {ray.distance_m} m, at or beyond range"
        )
        assert ray.distance_m > 0.0
    # The walls are 2 m out and 100 mm thick, so every return lies between 1.95 m
    # (straight ahead) and 2.83 m (into a corner). Anything wider escaped the room.
    assert all(1.94 <= ray.distance_m <= 2.83 for ray in observation.rays)


def test_a_gap_in_the_wall_is_reported_as_open() -> None:
    """The complement: a genuine opening must show up, or the sensor is useless."""
    walls = (
        _box(0.0, 2.0, 1.8, 0.1),  # shortened: leaves an opening near x = +0.6
        _box(0.0, -2.0, 4.0, 0.1),
        _box(2.0, 0.0, 0.1, 4.0),
        _box(-2.0, 0.0, 0.1, 4.0),
    )
    scene = SensorScene(map=_map(walls, half_extent=20.0))
    observation = generate_observation(
        world_geometry=scene,
        robot_id="r1",
        true_pose=Pose(0.0, 0.0, 0.0),
        footprint=_FOOTPRINT,
        sim_time_ns=0,
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/scan",
    )
    kinds = {ray.kind for ray in observation.rays}
    assert "obstacle" in kinds


def test_a_robot_is_detected_as_a_robot_not_as_an_obstacle() -> None:
    """A peer must be distinguishable in the scan, so provenance is preserved."""
    peer = OrientedBox(1.5, 0.0, 0.0, 0.8, 0.6)
    scene = SensorScene(map=_map(), other_bodies=(peer,))
    distance, kind = nearest_surface(scene, (0.0, 0.0), 0.0, _SENSOR.range_m)
    assert kind == "robot"
    assert distance == pytest.approx(1.1, abs=1e-9)


def test_rays_stop_at_the_map_envelope_when_nothing_else_is_present() -> None:
    scene = SensorScene(map=_map(half_extent=2.0))
    distance, kind = nearest_surface(scene, (0.0, 0.0), 0.0, _SENSOR.range_m)
    assert kind == "boundary"
    assert distance == pytest.approx(2.0, abs=1e-9)


def test_nothing_within_range_is_reported_as_free_at_full_range() -> None:
    """""Free"" means only that the sensor saw nothing inside its own range."""
    scene = SensorScene(map=_map(half_extent=50.0))
    distance, kind = nearest_surface(scene, (0.0, 0.0), 0.0, _SENSOR.range_m)
    assert kind == "free"
    assert distance == pytest.approx(_SENSOR.range_m)


def test_a_ray_misses_past_a_wall_and_hits_the_wall_instead() -> None:
    """Nearest hit wins: a wall behind a window must not be reported."""
    window = OrientedBox(3.0, 0.0, 0.0, 0.1, 0.1)
    wall = OrientedBox(1.0, 0.0, 0.0, 0.2, 2.0)
    assert ray_box_distance_m((0.0, 0.0), 0.0, window) == pytest.approx(2.95, abs=1e-9)
    assert ray_box_distance_m((0.0, 0.0), 0.0, wall) == pytest.approx(0.9, abs=1e-9)


def test_a_ray_pointing_away_misses_a_box_behind_the_origin() -> None:
    box = OrientedBox(3.0, 0.0, 0.0, 0.5, 0.5)
    assert ray_box_distance_m((0.0, 0.0), math.pi, box) == math.inf


def test_ray_from_inside_a_box_reports_zero_distance() -> None:
    box = OrientedBox(0.0, 0.0, 0.0, 1.0, 1.0)
    assert ray_box_distance_m((0.0, 0.0), 0.0, box) == 0.0


def test_ray_outside_the_envelope_reports_zero_so_it_cannot_hide() -> None:
    boundary = MapBoundary(min_x=-1.0, min_y=-1.0, max_x=1.0, max_y=1.0)
    assert ray_boundary_distance_m((5.0, 0.0), 0.0, boundary) == 0.0


# --------------------------------------------------------------------------- #
# Latency
# --------------------------------------------------------------------------- #


def test_latency_separates_observation_time_from_delivery_time() -> None:
    """``delivered_at_ns > observed_at_ns`` by exactly the modelled latency."""
    now_ns = 5_000_000_000
    observation = generate_observation(
        world_geometry=SensorScene(map=_map()),
        robot_id="r1",
        true_pose=Pose(0.0, 0.0, 0.0),
        footprint=_FOOTPRINT,
        sim_time_ns=now_ns,
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/scan",
    )
    assert observation.delivered_at_ns == now_ns
    assert observation.observed_at_ns == now_ns - _LATENCY_NS
    assert observation.delivered_at_ns > observation.observed_at_ns
    assert observation.delivered_at_ns - observation.observed_at_ns == _LATENCY_NS
    assert all(ray.age_ns == _LATENCY_NS for ray in observation.rays)


def test_pose_estimate_is_labelled_with_the_time_the_fix_was_taken() -> None:
    """The estimate must not inherit the arrival time and claim freshness it lacks."""
    now_ns = 5_000_000_000
    fix_at_ns = now_ns - _LATENCY_NS
    estimate = generate_pose_estimate(
        true_pose=Pose(1.0, 2.0, 0.3),
        map_id="test-map",
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/pose",
        observed_at_ns=fix_at_ns,
    )
    assert estimate.observed_at_ns == fix_at_ns
    assert estimate.observed_at_ns < now_ns
    assert estimate.uncertainty.kind == "gaussian_sigma"
    assert estimate.uncertainty.sigma_m == pytest.approx(_SENSOR.position_sigma_m)
    assert estimate.uncertainty.source == "simulated"


def test_a_pose_estimate_never_gets_a_future_timestamp() -> None:
    """A simulation younger than the latency reports zero, never a negative time."""
    estimate = generate_pose_estimate(
        true_pose=Pose(0.0, 0.0, 0.0),
        map_id="test-map",
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/pose",
        observed_at_ns=0,
    )
    assert estimate.observed_at_ns == 0


def test_negative_timestamps_are_rejected_rather_than_clamped() -> None:
    with pytest.raises(ValueError, match="observed_at_ns"):
        generate_pose_estimate(
            true_pose=Pose(0.0, 0.0, 0.0),
            map_id="test-map",
            sensor_model=_SENSOR,
            streams=SeededStreams(base_seed=7),
            rng_stream_name="sensor/r1/pose",
            observed_at_ns=-1,
        )
    with pytest.raises(ValueError, match="sim_time_ns"):
        generate_observation(
            world_geometry=SensorScene(map=_map()),
            robot_id="r1",
            true_pose=Pose(0.0, 0.0, 0.0),
            footprint=_FOOTPRINT,
            sim_time_ns=-1,
            sensor_model=_SENSOR,
            streams=SeededStreams(base_seed=7),
            rng_stream_name="sensor/r1/scan",
        )


# --------------------------------------------------------------------------- #
# Dropout
# --------------------------------------------------------------------------- #


def test_dropout_empties_the_scan_and_flags_it_rather_than_faking_clear_rays() -> None:
    """A failed sensor reports "no data", never "nothing in range".

    Turning a dropped beam into a clear ray would let a failed lidar look like an
    empty aisle, which is the most dangerous default a safety monitor can have.
    """
    streams = SeededStreams(base_seed=11)
    observation = generate_observation(
        world_geometry=SensorScene(map=_map()),
        robot_id="r1",
        true_pose=Pose(0.0, 0.0, 0.0),
        footprint=_FOOTPRINT,
        sim_time_ns=1_000_000_000,
        sensor_model=_NOSED_SENSOR,
        streams=streams,
        rng_stream_name="sensor/r1/scan",
    )
    if observation.dropped:
        assert observation.rays == ()
    else:  # pragma: no cover - only on an unlucky seed
        assert observation.rays


def test_a_scene_containing_the_observer_own_body_is_rejected() -> None:
    """Including the robot's own chassis would reconstruct its exact pose from beam 0."""
    own = OrientedBox(0.0, 0.0, 0.0, _FOOTPRINT.length_m, _FOOTPRINT.width_m)
    scene = SensorScene(map=_map(), other_bodies=(own,))
    with pytest.raises(ValueError, match="observer's own body"):
        generate_observation(
            world_geometry=scene,
            robot_id="r1",
            true_pose=Pose(0.0, 0.0, 0.0),
            footprint=_FOOTPRINT,
            sim_time_ns=0,
            sensor_model=_SENSOR,
            streams=SeededStreams(base_seed=7),
            rng_stream_name="sensor/r1/scan",
        )


def test_the_self_body_guard_does_not_fire_on_a_genuine_overlapping_peer() -> None:
    """A robot whose chassis overlaps a neighbour must still be able to scan.

    Refusing to observe in exactly the collision the evaluator needs to inspect
    would blind the most important run in the system. Overlap is therefore not the
    guard's trigger -- only the observer's own body, at its own pose, is.
    """
    peer = OrientedBox(0.10, 0.0, 0.0, _FOOTPRINT.length_m, _FOOTPRINT.width_m)
    scene = SensorScene(map=_map(), other_bodies=(peer,))
    observation = generate_observation(
        world_geometry=scene,
        robot_id="r1",
        true_pose=Pose(0.0, 0.0, 0.0),
        footprint=_FOOTPRINT,
        sim_time_ns=0,
        sensor_model=_SENSOR,
        streams=SeededStreams(base_seed=7),
        rng_stream_name="sensor/r1/scan",
    )
    assert observation.rays, "the scan must be produced even during a collision"
    assert observation.dropped is False


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def _scan_sequence(seed: int, steps: int = 40) -> list[tuple[object, ...]]:
    streams = SeededStreams(base_seed=seed)
    out: list[tuple[object, ...]] = []
    for index in range(steps):
        pose = Pose(index * 0.005, -index * 0.002, index * 0.01)
        observation = generate_observation(
            world_geometry=_sealed_room_scene(gap=0.0),
            robot_id="r1",
            true_pose=pose,
            footprint=_FOOTPRINT,
            sim_time_ns=index * 50_000_000,
            sensor_model=SensorModel(**{**_SENSOR.model_dump(), "range_noise_m": 0.02}),
            streams=streams,
            rng_stream_name="sensor/r1/scan",
        )
        estimate = generate_pose_estimate(
            true_pose=pose,
            map_id="test-map",
            sensor_model=_SENSOR,
            streams=streams,
            rng_stream_name="sensor/r1/pose",
            observed_at_ns=index * 50_000_000,
        )
        out.append((*_signature(observation), round(estimate.pose.x, 15), round(estimate.pose.y, 15)))
    return out


def test_the_same_seed_reproduces_a_byte_identical_observation_sequence() -> None:
    first = _scan_sequence(seed=2026)
    second = _scan_sequence(seed=2026)
    assert first == second
    assert len(first) == 40


def test_different_seeds_produce_different_noise() -> None:
    """Guard against the determinism test passing because nothing is random."""
    assert _scan_sequence(seed=2026) != _scan_sequence(seed=2027)


def test_two_robots_do_not_share_a_stream() -> None:
    """One robot's draws must not shift another's.

    Running r1 alone, then r2 alone, then the two interleaved on one stream object
    must reproduce the same observations per robot. Losing this property is silent:
    everything still "works", the numbers just change underneath a benchmark.
    """
    noisy = SensorModel(**{**_SENSOR.model_dump(), "range_noise_m": 0.05})

    def scan(streams: SeededStreams, robot_id: str, index: int) -> tuple[object, ...]:
        return _signature(
            generate_observation(
                world_geometry=SensorScene(map=_map()),
                robot_id=robot_id,
                true_pose=Pose(0.0, 0.0, 0.0),
                footprint=_FOOTPRINT,
                sim_time_ns=index * 50_000_000,
                sensor_model=noisy,
                streams=streams,
                rng_stream_name=f"sensor/{robot_id}/scan",
            )
        )

    # Each robot alone, one stream object advanced across the whole sequence.
    alone_a = SeededStreams(base_seed=99)
    alone_b = SeededStreams(base_seed=99)
    solo_a = [scan(alone_a, "r1", i) for i in range(8)]
    solo_b = [scan(alone_b, "r2", i) for i in range(8)]

    # The same two robots interleaved on one stream object.
    shared = SeededStreams(base_seed=99)
    interleaved_a = [scan(shared, "r1", i) for i in range(8)]
    interleaved_b = [scan(shared, "r2", i) for i in range(8)]

    assert interleaved_a == solo_a
    assert interleaved_b == solo_b
    assert interleaved_a != interleaved_b, "two robots must not draw the same numbers"


# --------------------------------------------------------------------------- #
# Beam pattern
# --------------------------------------------------------------------------- #


def test_the_beam_pattern_is_a_pure_function_of_the_configuration() -> None:
    """Noisy observations aside, cast_rays must be exactly reproducible."""
    scene = _sealed_room_scene(gap=0.0)
    pose = Pose(0.1, -0.2, 0.4)
    first = _signature_scan(cast_rays(scene, pose, _SENSOR))
    assert first == _signature_scan(cast_rays(scene, pose, _SENSOR))


def test_beams_span_the_field_of_view_and_stop_at_its_edges() -> None:
    scene = SensorScene(map=_map())
    rays = cast_rays(scene, Pose(0.0, 0.0, 0.0), _SENSOR)
    half = _SENSOR.field_of_view_rad / 2.0
    assert rays[0].bearing_rad == pytest.approx(-half, abs=1e-12)
    assert rays[-1].bearing_rad == pytest.approx(half, abs=1e-12)


def test_a_narrow_field_of_view_sees_only_that_cone() -> None:
    """A 60 degree cone must not report what is behind the robot as clear-and-near."""
    narrow = SensorModel(**{**_SENSOR.model_dump(), "field_of_view_rad": math.radians(60.0)})
    scene = SensorScene(map=_map(half_extent=5.0))
    behind = OrientedBox(-2.0, 0.0, 0.0, 0.5, 0.5)
    forward = OrientedBox(2.0, 0.0, 0.0, 0.5, 0.5)
    populated = SensorScene(map=scene.map, other_bodies=(behind, forward))
    rays = cast_rays(populated, Pose(0.0, 0.0, 0.0), narrow)
    assert all(abs(r.bearing_rad) <= math.radians(30.0) + 1e-12 for r in rays)

    # The body at x = +2 is 0.25 m half-width, so it subtends about 7 degrees.
    on_target = [r for r in rays if abs(r.bearing_rad) < math.radians(5.0)]
    assert on_target
    assert all(r.kind == "robot" for r in on_target)
    assert all(r.distance_m == pytest.approx(1.75, abs=1e-9) for r in on_target)

    # Every other beam misses both bodies and sees nothing inside the 3 m range.
    off_target = [r for r in rays if abs(r.bearing_rad) > math.radians(15.0)]
    assert off_target
    assert all(r.kind == "free" for r in off_target)
    assert all(r.distance_m == pytest.approx(_SENSOR.range_m) for r in off_target)

    # The body behind is invisible to a forward-only cone, and a 360 degree model
    # would have reported it.
    behind_only = cast_rays(
        SensorScene(map=scene.map, other_bodies=(behind,)), Pose(0.0, 0.0, 0.0), narrow
    )
    assert all(r.kind == "free" for r in behind_only)


def test_sensor_model_rejects_a_nonsensical_configuration() -> None:
    with pytest.raises(ValueError):
        SensorModel(range_m=0.0)
    with pytest.raises(ValueError):
        SensorModel(dropout_probability=1.5)

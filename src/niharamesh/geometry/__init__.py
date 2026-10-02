"""Re-export surface for planar geometry.

The authoritative implementation lives in :mod:`niharamesh.domain.geometry`.
This package exists only so that non-domain layers (simulator, safety,
evaluation) can import geometry as a *capability* (``niharamesh.geometry``)
rather than reaching into the domain's private layout. If that ever creates two
copies of a primitive, the two checkers in :mod:`niharamesh.safety.collision`
could disagree about the same geometry for the wrong reason, which is exactly
the failure mode that module exists to rule out.

There is deliberately **no logic here**: no new primitive, no re-implementation,
no numeric tolerance of its own. Every name resolves to the single domain
object.
"""

from __future__ import annotations

from niharamesh.domain.geometry import (
    OrientedBox,
    Polygon,
    Pose,
    Vec2,
    aabb_contains_point,
    aabb_overlap,
    bbox_of,
    box_corners,
    circle_rect_overlap,
    convex_hull,
    point_in_polygon,
    rotate,
    sat_overlap,
    sat_penetration,
    segment_intersects_segment,
    segment_point_distance,
)
from niharamesh.domain.units import angle_difference, wrap_angle

__all__ = [
    "OrientedBox",
    "Polygon",
    "Pose",
    "Vec2",
    "aabb_contains_point",
    "aabb_overlap",
    "angle_difference",
    "bbox_of",
    "box_corners",
    "circle_rect_overlap",
    "convex_hull",
    "point_in_polygon",
    "rotate",
    "sat_overlap",
    "sat_penetration",
    "segment_intersects_segment",
    "segment_point_distance",
    "wrap_angle",
]

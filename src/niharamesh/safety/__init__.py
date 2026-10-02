"""Safety layer: the veto path and the collision evidence behind it.

Only collision checking lives here at this stage. The gate itself
(:class:`niharamesh.ports.SafetyGatePort`) belongs to the agent side: it decides
whether a command may be *issued*, and it must be testable without a world. The
world, by contrast, always applies a command and lets collision be detected
afterwards -- so the two checkers in :mod:`niharamesh.safety.collision` are the
independent evidence that the applied motion was or was not safe.
"""

from __future__ import annotations

from niharamesh.safety.collision import (
    ORACLE_MAX_SAMPLES,
    CollisionKind,
    CollisionReport,
    min_clearance,
    oracle_overlap,
    oracle_residual_bound_m,
    oracle_swept_translation,
    pairwise_collisions,
    resolve_collision_report,
    swept_body_overlap,
    swept_residual_bound_m,
)

__all__ = [
    "ORACLE_MAX_SAMPLES",
    "CollisionKind",
    "CollisionReport",
    "min_clearance",
    "oracle_overlap",
    "oracle_residual_bound_m",
    "oracle_swept_translation",
    "pairwise_collisions",
    "resolve_collision_report",
    "swept_body_overlap",
    "swept_residual_bound_m",
]

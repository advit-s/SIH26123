"""Units, time domains and shared numeric invariants for NĪHĀRAMESH.

Every length is metres, every angle is radians, every duration is integer
nanoseconds. Time is never a bare number in this codebase: it always carries a
:class:`TimeDomain` so that two values from unrelated clock domains can never be
subtracted by accident.
"""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Final

import numpy as np

__all__ = [
    "MAX_FINITE",
    "PROTOCOL_EPOCH",
    "PROTOCOL_VERSION",
    "SCHEMA_VERSION",
    "SENSOR_NOW",
    "TimeDomain",
    "angle_difference",
    "heading_unit_vector",
    "is_finite",
    "quaternion_yaw",
    "require_finite",
    "wrap_angle",
]

#: Version of the domain/contract schema family. Bumped when a field is removed
#: or its meaning changes. Additive optional fields are still a minor change.
SCHEMA_VERSION: Final[str] = "1.0.0"

#: Version of the *wire* protocol spoken between robots.
PROTOCOL_VERSION: Final[str] = "1.0.0"

#: Membership epoch. Bumped by the launcher whenever the admitted peer set for a
#: run changes. Grants and intents bound to an older epoch are never accepted.
PROTOCOL_EPOCH: Final[str] = "e1"

#: Upper bound used to reject NaN/Inf and absurd magnitudes at the boundary.
MAX_FINITE: Final[float] = 1.0e9


class TimeDomain(StrEnum):
    """Named clock domains. Values are never mixed across domains.

    ``LOGICAL``
        Injected logical simulation time. Freezes when the harness pauses and
        advances under acceleration. Used by the deterministic mode.
    ``SIM_SECONDS``
        Simulation seconds elapsed since the declared common run start. Derived
        from ``LOGICAL``; identical semantics, different unit framing.
    ``MONOTONIC``
        The agent's own ``time.monotonic_ns()``. Never comparable across
        processes without an explicit measured offset *and* uncertainty.
    ``DISPLAY_UTC``
        Wall-clock UTC for human display only. Never used for expiry.
    """

    LOGICAL = "logical"
    SIM_SECONDS = "sim_seconds"
    MONOTONIC = "monotonic"
    DISPLAY_UTC = "display_utc"


#: Sentinel returned by freshness classification when no lower bound on age can
#: be established (unknown clock relationship).
SENSOR_NOW: Final[float] = float("nan")


def is_finite(value: float) -> bool:
    """Return True when *value* is a real, finite number."""
    return isinstance(value, (int, float)) and math.isfinite(float(value))


def require_finite(value: float, *, field: str) -> float:
    """Return *value* as float, raising ``ValueError`` for NaN/Inf.

    Imported from pydantic validators; kept here so the geometry and simulator
    layers can reuse the same rule without importing pydantic.
    """
    if not is_finite(value):
        raise ValueError(f"{field} must be a finite number, got {value!r}")
    return float(value)


def wrap_angle(theta: float) -> float:
    """Wrap *theta* into ``(-pi, pi]``."""
    return float((theta + math.pi) % (2.0 * math.pi) - math.pi)


def angle_difference(a: float, b: float) -> float:
    """Signed smallest difference ``a - b`` in ``(-pi, pi]``."""
    return wrap_angle(a - b)


def heading_unit_vector(theta: float) -> tuple[float, float]:
    """Return the unit forward vector for heading *theta*."""
    return math.cos(theta), math.sin(theta)


def quaternion_yaw(x: float, y: float, z: float, w: float) -> float:
    """Yaw of a ``geometry_msgs/Quaternion`` in radians.

    Kept beside the units module because the ROS 2 boundary must convert
    pose without importing ROS message packages (which are unavailable here).
    """
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def yaw_quaternion(theta: float) -> tuple[float, float, float, float]:
    """Inverse of :func:`quaternion_yaw`."""
    half = theta / 2.0
    return 0.0, 0.0, math.sin(half), math.cos(half)


def array2(x: float, y: float) -> np.ndarray:
    """Small helper so geometry code stays explicit about dtypes."""
    return np.array([float(x), float(y)], dtype=np.float64)

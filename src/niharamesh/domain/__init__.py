"""NĪHĀRAMESH domain contracts.

Everything crossing a process, socket, file or UI boundary is defined here and
nowhere else. Modules in this package are deliberately free of I/O so that
contracts, geometry and protocol logic can be imported by the web API, the
simulator and each agent process without creating a dependency cycle.
"""

from __future__ import annotations

from niharamesh.domain.units import (
    PROTOCOL_EPOCH,
    PROTOCOL_VERSION,
    SCHEMA_VERSION,
    TimeDomain,
)

__all__ = ["PROTOCOL_EPOCH", "PROTOCOL_VERSION", "SCHEMA_VERSION", "TimeDomain"]

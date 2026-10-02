"""Local spatial planning. One robot, one map, one plan.

Authority boundary (AGENTS.md rule 1): every symbol in this package is *local*.
A planner reads one robot's own pose, the immutable shared map
(:class:`~niharamesh.domain.map.WarehouseMap`) and explicit peer reports. It has
no accessor path to another robot's pose, task ownership or the evaluator's
collision verdict. Nothing here coordinates; the zone-grant protocol owns
physical exclusion (AGENTS.md rule 6) and the safety gate owns motion veto
(AGENTS.md rule 7).

Honesty boundary (AGENTS.md rule 2): durations produced here are *configured
estimates* from declared geometry and actuator limits. They are never presented
as measurements, and a plan is never presented as a safety certificate.

The approximate space-time planner lives in :mod:`niharamesh.planning.temporal`
and is deliberately **not** re-exported here. Importing it from outside this
package raises :class:`ImportError` until the run has explicitly opted in via
``FeatureFlags.temporal_planning`` (see :func:`set_temporal_exports_enabled`).
"""

from __future__ import annotations

from typing import Any

from niharamesh.planning.astar import (
    AStarPlanner,
    PathResult,
    PathStatus,
    TurnCost,
    UnreachableReason,
)
from niharamesh.planning.blocked import (
    BlockedRoutePolicy,
    CostComparison,
    RouteAction,
    RouteDecision,
)
from niharamesh.planning.grid import GridTooLargeError, OccupancyGrid
from niharamesh.planning.path import PathPlan, build_plan, smooth
from niharamesh.planning.velocity import Waypoint, velocity_profile

__all__ = [
    "AStarPlanner",
    "BlockedRoutePolicy",
    "CostComparison",
    "GridTooLargeError",
    "OccupancyGrid",
    "PathPlan",
    "PathResult",
    "PathStatus",
    "RouteAction",
    "RouteDecision",
    "TurnCost",
    "UnreachableReason",
    "Waypoint",
    "build_plan",
    "set_temporal_exports_enabled",
    "smooth",
    "temporal_exports_enabled",
    "velocity_profile",
]

#: Latched opt-in for the approximate space-time planner exports. Defaults to
#: ``False`` so that *no* import path outside ``niharamesh.planning`` can reach
#: the approximate planner unless a run declared the feature flag first.
_temporal_exports_enabled = False


def set_temporal_exports_enabled(enabled: bool) -> None:
    """Latch the ``temporal_planning`` feature flag for this process.

    Call this exactly once at launch, from the run's own
    :class:`~niharamesh.domain.config.FeatureFlags`. It exists so the gate is a
    single auditable statement rather than an import-order accident.
    """
    global _temporal_exports_enabled
    _temporal_exports_enabled = bool(enabled)


def temporal_exports_enabled() -> bool:
    """True when :mod:`niharamesh.planning.temporal` may be imported."""
    return _temporal_exports_enabled


def __getattr__(name: str) -> Any:
    """Gate the temporal exports (PEP 562).

    ``from niharamesh.planning import temporal`` and
    ``planning.temporal`` are both routed through here. With the flag off the
    import fails loudly instead of silently producing an "approximate is fine"
    planner in a run whose evidence is being charted.
    """
    if name in ("temporal", "ApproxSippSingleCellPlanner", "TemporalPlan", "TemporalPlanFailure"):
        if not _temporal_exports_enabled:
            raise ImportError(
                "niharamesh.planning.temporal is behind FeatureFlags.temporal_planning "
                "(RoutingPolicy.TEMPORAL_SIPP_APPROX). Call "
                "niharamesh.planning.set_temporal_exports_enabled(True) at launch only "
                "for runs that declared the flag; exports of a run with the flag off must "
                "never be charted as if the planner were complete."
            )
        import importlib

        module = importlib.import_module("niharamesh.planning.temporal")
        return module if name == "temporal" else getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

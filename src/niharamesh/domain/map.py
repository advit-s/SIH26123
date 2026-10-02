"""Warehouse map: obstacles, zones, stations, berths, stop lines, routes.

Validation lives in :mod:`niharamesh.scenario.validation` but the *structural*
invariants that make the map meaningful are enforced here so an invalid map can
never be constructed. Semantic validation (reachability, undersized passages,
zone separation) runs separately and reports every problem at once.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import IdStr, ShortIdStr, ZoneId
from niharamesh.domain.pose import FiniteFloat, Pose2
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "Berth",
    "MapBoundary",
    "Obstacle",
    "ObstacleKind",
    "RouteEdge",
    "Station",
    "StationKind",
    "StopLine",
    "WarehouseMap",
    "Zone",
    "ZoneMovement",
    "ZoneState",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ObstacleKind(StrEnum):
    SHELF = "shelf"
    WALL = "wall"
    PILLAR = "pillar"
    TEMPORARY = "temporary"
    """May appear and disappear at runtime under fault injection."""


class Obstacle(_Frozen):
    id: ShortIdStr
    kind: ObstacleKind = ObstacleKind.SHELF
    pose: Pose2
    length_m: Annotated[float, Field(gt=0.0, le=200.0, allow_inf_nan=False)]
    width_m: Annotated[float, Field(gt=0.0, le=200.0, allow_inf_nan=False)]
    #: Simulated obstacles may be inserted/removed at runtime. Static ones may not.
    dynamic: bool = False


class MapBoundary(_Frozen):
    """Axis-aligned usable envelope of the warehouse, in metres."""

    min_x: FiniteFloat
    min_y: FiniteFloat
    max_x: FiniteFloat
    max_y: FiniteFloat

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.max_x <= self.min_x or self.max_y <= self.min_y:
            raise ValueError("map boundary must have positive area")
        if (self.max_x - self.min_x) > 500.0 or (self.max_y - self.min_y) > 500.0:
            raise ValueError("map boundary exceeds 500 m; refusing to allocate a grid")
        return self


class StationKind(StrEnum):
    PICKUP = "pickup"
    DROP = "drop"
    CHARGE = "charge"


class Station(_Frozen):
    id: ShortIdStr
    kind: StationKind
    pose: Pose2
    #: Service duration at this station. A configured simulation assumption.
    service_time_s: Annotated[float, Field(ge=0.0, le=600.0, allow_inf_nan=False)] = 4.0
    capacity: Annotated[int, Field(ge=1, le=64)] = 1


class Berth(_Frozen):
    """A safe resting place: a place where a stopped robot is *not* holding
    another robot's zone authority."""

    id: ShortIdStr
    pose: Pose2
    capacity: Annotated[int, Field(ge=1, le=16)] = 1


class StopLine(_Frozen):
    """Physical line a robot must not cross without the named authority.

    ``zone_id`` names the authority required. This is the geometric anchor for
    "stop-line violation", which the evaluator checks independently.
    """

    id: ShortIdStr
    zone_id: ZoneId
    start: tuple[FiniteFloat, FiniteFloat]
    end: tuple[FiniteFloat, FiniteFloat]
    #: Which side of the line counts as "past" the line for the requester that
    #: holds the named authority. Recorded so the check is unambiguous.
    approach: str = Field(default="decreasing", pattern="^(increasing|decreasing)$")

    @model_validator(mode="after")
    def _non_degenerate(self) -> Self:
        if abs(self.start[0] - self.end[0]) < 1e-6 and abs(self.start[1] - self.end[1]) < 1e-6:
            raise ValueError("stop line must have non-zero length")
        return self


class ZoneMovement(StrEnum):
    """The protected movement a zone authorises.

    ``FWD``  - traverse along the zone's declared axis, either direction.
    ``REV``  - traverse against the declared axis (used for one-way aisles).
    ``CROSS``- cross the zone (intersections / junctions).
    """

    FWD = "forward"
    REV = "reverse"
    CROSS = "cross"


class ZoneState(StrEnum):
    FREE = "free"
    PROMISED = "promised"
    OCCUPIED = "occupied"
    FENCED = "fenced"
    """A robot failed while holding this zone. Authority is unavailable until a
    supervised, explicit reconciliation completes. There is no force-release."""


class Zone(_Frozen):
    """An exclusive resource with disjoint protected geometry.

    Every exclusive zone's protected geometry must be **disjoint** from every
    other exclusive zone's. Where a traversal needs two adjacent resources with
    no safe berth between them, they must be authored as ONE compound zone
    (see ``members``), not as two zones a robot might partially hold.
    """

    id: ZoneId
    kind: str = Field(default="corridor", max_length=32)
    description: str = Field(default="", max_length=240)
    #: Protected (inflated) geometry, in map coordinates. Used for admission.
    protected_origin: tuple[FiniteFloat, FiniteFloat]
    protected_extent: tuple[FiniteFloat, FiniteFloat]
    entry_pose: Pose2
    exit_pose: Pose2
    stop_line_in: ShortIdStr | None = None
    stop_line_out: ShortIdStr | None = None
    #: Where a requester may safely wait *outside* this zone while queued.
    queue_berth_id: ShortIdStr | None = None
    #: Safe exit/holding berth after the traversal, outside every other zone.
    exit_berth_id: ShortIdStr | None = None
    #: Component zone ids that make up this compound zone. Mutually disjoint set.
    members: tuple[ZoneId, ...] = ()
    allowed_movement: tuple[ZoneMovement, ...] = (ZoneMovement.FWD, ZoneMovement.CROSS)
    #: Optional one-way restriction expressed as the single permitted heading.
    one_way_heading_rad: FiniteFloat | None = None

    @model_validator(mode="after")
    def _extent_positive(self) -> Self:
        if self.protected_extent[0] <= 0.0 or self.protected_extent[1] <= 0.0:
            raise ValueError("zone protected_extent must be positive on both axes")
        if self.id in self.members:
            raise ValueError("compound zone must not contain itself")
        if len(set(self.members)) != len(self.members):
            raise ValueError("duplicate member zone id")
        return self

    @property
    def protected_bounds(self) -> tuple[float, float, float, float]:
        ox, oy = self.protected_origin
        ex, ey = self.protected_extent
        return (ox, oy, ox + ex, oy + ey)

    def contains_point(self, x: float, y: float) -> bool:
        bx = self.protected_bounds
        return bx[0] <= x <= bx[2] and bx[1] <= y <= bx[3]


class RouteEdge(_Frozen):
    """Directed travel edge for the optional directed-route graph.

    When a map declares ``directed_routes``, the planner must respect
    ``one_way`` on each edge. This is a topological *hint*, not authority.
    """

    id: ShortIdStr
    from_pose: Pose2
    to_pose: Pose2
    one_way: bool = True
    cost_m: Annotated[float, Field(gt=0.0, le=1000.0, allow_inf_nan=False)]


class WarehouseMap(_Frozen):
    """Immutable shared map. Every agent receives exactly this object."""

    schema_version: str = SCHEMA_VERSION
    map_id: ShortIdStr
    revision: Annotated[int, Field(ge=1)] = 1
    name: str = Field(default="", max_length=120)
    boundary: MapBoundary
    obstacles: tuple[Obstacle, ...] = ()
    stations: tuple[Station, ...] = ()
    berths: tuple[Berth, ...] = ()
    stop_lines: tuple[StopLine, ...] = ()
    zones: tuple[Zone, ...] = ()
    directed_routes: tuple[RouteEdge, ...] = ()
    #: Grid resolution used by the spatial planner. Configured assumption.
    grid_resolution_m: Annotated[float, Field(gt=0.02, le=0.5, allow_inf_nan=False)] = 0.1
    #: Declared aisle width used for "undersized passage" diagnostics.
    nominal_aisle_width_m: Annotated[float, Field(gt=0.3, le=20.0, allow_inf_nan=False)] = 1.4

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        for label, group in (
            ("obstacle", self.obstacles),
            ("station", self.stations),
            ("berth", self.berths),
            ("stop_line", self.stop_lines),
            ("zone", self.zones),
            ("directed_route", self.directed_routes),
        ):
            ids = [o.id for o in group]
            if len(set(ids)) != len(ids):
                dupes = sorted({i for i in ids if ids.count(i) > 1})
                raise ValueError(f"duplicate {label} id(s): {dupes}")
        known_zones = {z.id for z in self.zones}
        for line in self.stop_lines:
            if line.zone_id not in known_zones:
                raise ValueError(f"stop line {line.id!r} references unknown zone {line.zone_id!r}")
        known_berths = {b.id for b in self.berths}
        for zone in self.zones:
            for ref in (zone.queue_berth_id, zone.exit_berth_id):
                if ref is not None and ref not in known_berths:
                    raise ValueError(f"zone {zone.id!r} references unknown berth {ref!r}")
            for member in zone.members:
                if member not in known_zones:
                    raise ValueError(
                        f"compound zone {zone.id!r} references unknown zone {member!r}"
                    )
        return self

    def zone(self, zone_id: str) -> Zone:
        for z in self.zones:
            if z.id == zone_id:
                return z
        raise KeyError(f"unknown zone {zone_id!r}")

    def station(self, station_id: str) -> Station:
        for s in self.stations:
            if s.id == station_id:
                return s
        raise KeyError(f"unknown station {station_id!r}")

    def berth(self, berth_id: str) -> Berth:
        for b in self.berths:
            if b.id == berth_id:
                return b
        raise KeyError(f"unknown berth {berth_id!r}")

    def stop_line(self, line_id: str) -> StopLine:
        for line in self.stop_lines:
            if line.id == line_id:
                return line
        raise KeyError(f"unknown stop line {line_id!r}")

    def canonical_json(self) -> str:
        """Stable serialisation used for the map hash. Key order is fixed."""
        import json

        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def digest(self) -> IdStr:
        import hashlib

        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()[:32]

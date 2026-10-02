// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/WarehouseMap.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Capacity = number;
export type Id = string;
export type Theta = number;
export type X = number;
export type Y = number;
export type Berths = Berth[];
export type MaxX = number;
export type MaxY = number;
export type MinX = number;
export type MinY = number;
export type CostM = number;
export type Id1 = string;
export type OneWay = boolean;
export type DirectedRoutes = RouteEdge[];
export type GridResolutionM = number;
export type MapId = string;
export type Name = string;
export type NominalAisleWidthM = number;
export type Dynamic = boolean;
export type Id2 = string;
export type ObstacleKind = "shelf" | "wall" | "pillar" | "temporary";
export type LengthM = number;
export type WidthM = number;
export type Obstacles = Obstacle[];
export type Revision = number;
export type SchemaVersion = string;
export type Capacity1 = number;
export type Id3 = string;
export type StationKind = "pickup" | "drop" | "charge";
export type ServiceTimeS = number;
export type Stations = Station[];
export type Approach = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type End = [unknown, unknown];
export type Id4 = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Start = [unknown, unknown];
export type ZoneId = string;
export type StopLines = StopLine[];
/**
 * The protected movement a zone authorises.
 *
 * ``FWD``  - traverse along the zone's declared axis, either direction.
 * ``REV``  - traverse against the declared axis (used for one-way aisles).
 * ``CROSS``- cross the zone (intersections / junctions).
 */
export type ZoneMovement = "forward" | "reverse" | "cross";
export type AllowedMovement = ZoneMovement[];
export type Description = string;
export type ExitBerthId = string | null;
export type Id5 = string;
export type Kind = string;
export type Members = string[];
export type OneWayHeadingRad = number | null;
/**
 * @minItems 2
 * @maxItems 2
 */
export type ProtectedExtent = [unknown, unknown];
/**
 * @minItems 2
 * @maxItems 2
 */
export type ProtectedOrigin = [unknown, unknown];
export type QueueBerthId = string | null;
export type StopLineIn = string | null;
export type StopLineOut = string | null;
export type Zones = Zone[];

/**
 * Immutable shared map. Every agent receives exactly this object.
 */
export interface WarehouseMap {
  berths?: Berths;
  boundary: MapBoundary;
  directed_routes?: DirectedRoutes;
  grid_resolution_m?: GridResolutionM;
  map_id: MapId;
  name?: Name;
  nominal_aisle_width_m?: NominalAisleWidthM;
  obstacles?: Obstacles;
  revision?: Revision;
  schema_version?: SchemaVersion;
  stations?: Stations;
  stop_lines?: StopLines;
  zones?: Zones;
}
/**
 * A safe resting place: a place where a stopped robot is *not* holding
 * another robot's zone authority.
 */
export interface Berth {
  capacity?: Capacity;
  id: Id;
  pose: Pose2;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}
/**
 * Axis-aligned usable envelope of the warehouse, in metres.
 */
export interface MapBoundary {
  max_x: MaxX;
  max_y: MaxY;
  min_x: MinX;
  min_y: MinY;
}
/**
 * Directed travel edge for the optional directed-route graph.
 *
 * When a map declares ``directed_routes``, the planner must respect
 * ``one_way`` on each edge. This is a topological *hint*, not authority.
 */
export interface RouteEdge {
  cost_m: CostM;
  from_pose: Pose2;
  id: Id1;
  one_way?: OneWay;
  to_pose: Pose2;
}
export interface Obstacle {
  dynamic?: Dynamic;
  id: Id2;
  kind?: ObstacleKind;
  length_m: LengthM;
  pose: Pose2;
  width_m: WidthM;
}
export interface Station {
  capacity?: Capacity1;
  id: Id3;
  kind: StationKind;
  pose: Pose2;
  service_time_s?: ServiceTimeS;
}
/**
 * Physical line a robot must not cross without the named authority.
 *
 * ``zone_id`` names the authority required. This is the geometric anchor for
 * "stop-line violation", which the evaluator checks independently.
 */
export interface StopLine {
  approach?: Approach;
  end: End;
  id: Id4;
  start: Start;
  zone_id: ZoneId;
}
/**
 * An exclusive resource with disjoint protected geometry.
 *
 * Every exclusive zone's protected geometry must be **disjoint** from every
 * other exclusive zone's. Where a traversal needs two adjacent resources with
 * no safe berth between them, they must be authored as ONE compound zone
 * (see ``members``), not as two zones a robot might partially hold.
 */
export interface Zone {
  allowed_movement?: AllowedMovement;
  description?: Description;
  entry_pose: Pose2;
  exit_berth_id?: ExitBerthId;
  exit_pose: Pose2;
  id: Id5;
  kind?: Kind;
  members?: Members;
  one_way_heading_rad?: OneWayHeadingRad;
  protected_extent: ProtectedExtent;
  protected_origin: ProtectedOrigin;
  queue_berth_id?: QueueBerthId;
  stop_line_in?: StopLineIn;
  stop_line_out?: StopLineOut;
}

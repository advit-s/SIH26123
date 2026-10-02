// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Zone.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
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
export type Theta = number;
export type X = number;
export type Y = number;
export type ExitBerthId = string | null;
export type Id = string;
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
  id: Id;
  kind?: Kind;
  members?: Members;
  one_way_heading_rad?: OneWayHeadingRad;
  protected_extent: ProtectedExtent;
  protected_origin: ProtectedOrigin;
  queue_berth_id?: QueueBerthId;
  stop_line_in?: StopLineIn;
  stop_line_out?: StopLineOut;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}

// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Station.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Capacity = number;
export type Id = string;
export type StationKind = "pickup" | "drop" | "charge";
export type Theta = number;
export type X = number;
export type Y = number;
export type ServiceTimeS = number;

export interface Station {
  capacity?: Capacity;
  id: Id;
  kind: StationKind;
  pose: Pose2;
  service_time_s?: ServiceTimeS;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}

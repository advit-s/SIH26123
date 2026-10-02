// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Obstacle.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Dynamic = boolean;
export type Id = string;
export type ObstacleKind = "shelf" | "wall" | "pillar" | "temporary";
export type LengthM = number;
export type Theta = number;
export type X = number;
export type Y = number;
export type WidthM = number;

export interface Obstacle {
  dynamic?: Dynamic;
  id: Id;
  kind?: ObstacleKind;
  length_m: LengthM;
  pose: Pose2;
  width_m: WidthM;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}

// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Berth.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Capacity = number;
export type Id = string;
export type Theta = number;
export type X = number;
export type Y = number;

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

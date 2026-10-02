// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Pose2.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Theta = number;
export type X = number;
export type Y = number;

/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}

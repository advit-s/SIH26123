// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RobotStart.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AssignedTaskId = string | null;
export type HoldingTaskId = string | null;
export type Theta = number;
export type X = number;
export type Y = number;
export type RobotId = string;

export interface RobotStart {
  assigned_task_id?: AssignedTaskId;
  holding_task_id?: HoldingTaskId;
  pose: Pose2;
  robot_id: RobotId;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}

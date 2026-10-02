// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/TaskTransition.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AtNs = number;
export type TaskState =
  "available" | "claimed" | "pickup_confirmed" | "in_transit" | "delivered" | "recovery_required" | "abandoned";
export type OwnershipVersion = number;
export type Reason = string;
export type RobotId = string;
export type RobotSession = string;
export type TaskId = string;
export type TransitionSeq = number;

export interface TaskTransition {
  at_ns: AtNs;
  from_state: TaskState;
  ownership_version: OwnershipVersion;
  reason?: Reason;
  robot_id: RobotId;
  robot_session: RobotSession;
  task_id: TaskId;
  to_state: TaskState;
  transition_seq: TransitionSeq;
}

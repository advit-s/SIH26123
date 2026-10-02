// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/TaskBid.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AtNs = number;
export type Name = string;
export type Unit = string;
export type Value = number;
export type Components = BidComponent[];
export type Epoch = string;
export type Feasible = boolean;
export type InfeasibleReason = string;
export type RobotId = string;
export type RobotSession = string;
export type RoundId = string;
export type RunId = string;
export type SchemaVersion = string;
export type TaskId = string;
export type TieBreak = number;
export type TotalCost = number;

/**
 * Computed locally by one robot from its own available state only.
 */
export interface TaskBid {
  at_ns: AtNs;
  components?: Components;
  epoch: Epoch;
  feasible?: Feasible;
  infeasible_reason?: InfeasibleReason;
  robot_id: RobotId;
  robot_session: RobotSession;
  round_id: RoundId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  task_id: TaskId;
  tie_break?: TieBreak;
  total_cost: TotalCost;
}
/**
 * One declared term of a local bid. Shown verbatim in the UI.
 */
export interface BidComponent {
  name: Name;
  unit: Unit;
  value: Value;
}

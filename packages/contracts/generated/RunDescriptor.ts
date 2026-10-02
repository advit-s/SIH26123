// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RunDescriptor.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Collisions = number;
export type CoordinationPolicy = string;
export type CreatedUtcNs = number;
export type EvidenceComplete = boolean;
export type IdempotencyKey = string;
export type MakespanS = number | null;
export type Note = string;
export type RunOutcome =
  | "success"
  | "unsafe"
  | "degraded"
  | "expected_safe_stop"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "incomplete_evidence";
export type RunId = string;
export type ScenarioRevision = number;
export type Seed = number;
export type SimDurationS = number;
export type RunState = "queued" | "running" | "paused" | "completed" | "unsafe" | "failed" | "timed_out" | "cancelled";
export type TasksCompleted = number;
export type TasksTotal = number;

/**
 * Lightweight listing record for the experiments matrix.
 */
export interface RunDescriptor {
  collisions: Collisions;
  coordination_policy: CoordinationPolicy;
  created_utc_ns: CreatedUtcNs;
  evidence_complete?: EvidenceComplete;
  idempotency_key?: IdempotencyKey;
  makespan_s?: MakespanS;
  note?: Note;
  outcome: RunOutcome;
  run_id: RunId;
  scenario_revision: ScenarioRevision;
  seed: Seed;
  sim_duration_s: SimDurationS;
  state: RunState;
  tasks_completed: TasksCompleted;
  tasks_total: TasksTotal;
}

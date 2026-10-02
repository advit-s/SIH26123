// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RunResult.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Collisions = number;
export type Digest = string;
export type EventsPath = string;
export type EventCategory =
  "authority" | "evaluation" | "task" | "planning" | "safety" | "fault" | "command" | "lifecycle" | "telemetry";
export type Cause = string;
export type FromSeq = number;
export type Recovered = boolean;
export type RunId = string;
export type SimTimeFromS = number;
export type SimTimeToS = number;
export type ToSeq = number;
export type Gaps = RecordingGap[];
export type MakespanS = number | null;
export type ManifestDigest = string;
export type MetricAvailability = "measured" | "unavailable" | "excluded";
export type Key = string;
export type Note = string;
export type SampleCount = number | null;
export type Value = number | null;
export type Metrics = MetricValue[];
export type MinClearanceM = number | null;
export type RunOutcome =
  | "success"
  | "unsafe"
  | "degraded"
  | "expected_safe_stop"
  | "failed"
  | "timed_out"
  | "cancelled"
  | "incomplete_evidence";
export type RunId1 = string;
export type SimDurationS = number;
export type RunState = "queued" | "running" | "paused" | "completed" | "unsafe" | "failed" | "timed_out" | "cancelled";
export type StopReason = string;
export type TasksCompleted = number;
export type TasksTotal = number;

/**
 * The outcome of one run, always including failures and timeouts.
 */
export interface RunResult {
  collisions: Collisions;
  digest?: Digest;
  events_path?: EventsPath;
  gaps?: Gaps;
  makespan_s?: MakespanS;
  manifest_digest: ManifestDigest;
  metrics?: Metrics;
  min_clearance_m?: MinClearanceM;
  outcome: RunOutcome;
  run_id: RunId1;
  sim_duration_s: SimDurationS;
  state: RunState;
  stop_reason?: StopReason;
  tasks_completed: TasksCompleted;
  tasks_total: TasksTotal;
}
/**
 * An explicit, visible hole in durable evidence.
 *
 * A run with an unresolved gap in a durable category is marked incomplete and
 * its affected metrics are excluded from claims requiring complete evidence.
 */
export interface RecordingGap {
  category: EventCategory;
  cause: Cause;
  from_seq: FromSeq;
  recovered?: Recovered;
  run_id: RunId;
  sim_time_from_s: SimTimeFromS;
  sim_time_to_s: SimTimeToS;
  to_seq: ToSeq;
}
export interface MetricValue {
  availability: MetricAvailability;
  key: Key;
  note?: Note;
  sample_count?: SampleCount;
  value?: Value;
}

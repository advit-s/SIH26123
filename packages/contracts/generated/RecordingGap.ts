// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RecordingGap.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type EventCategory =
  "authority" | "evaluation" | "task" | "planning" | "safety" | "fault" | "command" | "lifecycle" | "telemetry";
export type Cause = string;
export type FromSeq = number;
export type Recovered = boolean;
export type RunId = string;
export type SimTimeFromS = number;
export type SimTimeToS = number;
export type ToSeq = number;

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

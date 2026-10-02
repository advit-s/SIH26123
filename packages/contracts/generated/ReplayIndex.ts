// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ReplayIndex.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Complete = boolean;
export type EventCount = number;
export type EventsPath = string;
export type FirstSimTimeS = number;
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
export type LastSimTimeS = number;
export type Notes = string;
export type RunId1 = string;

/**
 * Rebuilds the world at any timestamp. Never fabricates future state.
 */
export interface ReplayIndex {
  categories?: Categories;
  complete?: Complete;
  event_count: EventCount;
  events_path: EventsPath;
  first_sim_time_s: FirstSimTimeS;
  gaps?: Gaps;
  last_sim_time_s: LastSimTimeS;
  notes?: Notes;
  run_id: RunId1;
}
export interface Categories {
  [k: string]: number;
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

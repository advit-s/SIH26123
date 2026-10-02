// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/FaultSpec.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type DurationS = number;
export type ExpectedInvariant = string;
export type FaultId = string;
export type SchemaVersion = string;
export type Seed = number;
export type StartAtS = number;
export type FaultChannel = "coordination" | "telemetry";
export type FaultKind =
  | "delay"
  | "loss"
  | "duplicate"
  | "reorder"
  | "partition"
  | "clock_skew"
  | "obstacle_insert"
  | "obstacle_remove"
  | "sensor_stale"
  | "sensor_dropout"
  | "control_overload"
  | "process_crash"
  | "process_restart"
  | "journal_corrupt";
export type MessageKind = string | null;
export type Position = [unknown, unknown] | null;
export type Receiver = string | null;
export type Robot = string | null;
export type Sender = string | null;
export type ZoneId = string | null;

export interface FaultSpec {
  duration_s?: DurationS;
  expected_invariant: ExpectedInvariant;
  fault_id: FaultId;
  params?: Params;
  schema_version?: SchemaVersion;
  seed?: Seed;
  start_at_s?: StartAtS;
  target: FaultTarget;
}
export interface Params {
  [k: string]: number;
}
/**
 * Explicit sender/receiver targeting. A fault with no target is invalid -
 * the brief requires directed fault injection, not a global toggle.
 */
export interface FaultTarget {
  channel: FaultChannel;
  kind: FaultKind;
  message_kind?: MessageKind;
  position?: Position;
  receiver?: Receiver;
  robot?: Robot;
  sender?: Sender;
  zone_id?: ZoneId;
}

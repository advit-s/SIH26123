// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/DomainEvent.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type EventCategory =
  "authority" | "evaluation" | "task" | "planning" | "safety" | "fault" | "command" | "lifecycle" | "telemetry";
export type CorrelationId = string;
export type EventTimeNs = number;
export type FaultId = string | null;
export type Reason = string;
/**
 * Named clock domains. Values are never mixed across domains.
 *
 * ``LOGICAL``
 *     Injected logical simulation time. Freezes when the harness pauses and
 *     advances under acceleration. Used by the deterministic mode.
 * ``SIM_SECONDS``
 *     Simulation seconds elapsed since the declared common run start. Derived
 *     from ``LOGICAL``; identical semantics, different unit framing.
 * ``MONOTONIC``
 *     The agent's own ``time.monotonic_ns()``. Never comparable across
 *     processes without an explicit measured offset *and* uncertainty.
 * ``DISPLAY_UTC``
 *     Wall-clock UTC for human display only. Never used for expiry.
 */
export type TimeDomain = "logical" | "sim_seconds" | "monotonic" | "display_utc";
export type ReceiveTimeNs = number;
export type RobotId = string | null;
export type RunId = string;
export type SchemaVersion = string;
export type Seq = number;
export type EventSeverity = "info" | "attention" | "fault" | "violation";
export type SimTimeS = number;
export type Source = string;
export type SourceSession = string;
export type TaskId = string | null;
export type Type = string;
export type ZoneId = string | null;

/**
 * One durable record. Append-only, globally sequenced by ``seq``.
 */
export interface DomainEvent {
  category: EventCategory;
  correlation_id?: CorrelationId;
  event_time_ns: EventTimeNs;
  fault_id?: FaultId;
  payload?: Payload;
  reason?: Reason;
  receive_time_domain: TimeDomain;
  receive_time_ns: ReceiveTimeNs;
  robot_id?: RobotId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  seq: Seq;
  severity?: EventSeverity;
  sim_time_s?: SimTimeS;
  source: Source;
  source_session?: SourceSession;
  task_id?: TaskId;
  time_domain: TimeDomain;
  type: Type;
  zone_id?: ZoneId;
}
export interface Payload {
  [k: string]: unknown;
}

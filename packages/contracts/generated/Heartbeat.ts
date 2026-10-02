// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Heartbeat.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Degraded = boolean;
export type DegradedReason = string;
export type Epoch = string;
export type RobotId = string;
export type RunId = string;
export type SchemaVersion = string;
export type SentAtNs = number;
export type Seq = number;
export type SessionId = string;
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

/**
 * Liveness only. Explicitly *not* usable intent and *not* clearance.
 */
export interface Heartbeat {
  degraded?: Degraded;
  degraded_reason?: DegradedReason;
  epoch: Epoch;
  robot_id: RobotId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  sent_at_ns: SentAtNs;
  seq: Seq;
  session_id: SessionId;
  time_domain: TimeDomain;
}

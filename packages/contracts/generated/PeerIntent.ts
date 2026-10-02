// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PeerIntent.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Epoch = string;
export type ExpectedZones = string[];
export type MapDigest = string;
export type MapId = string;
export type PlanVersion = number;
export type ProjectedPath = [unknown, unknown, unknown][];
export type ProtocolVersion = string;
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
export type ValidityHorizonNs = number;

/**
 * Predicted path and the resources the sender expects to need.
 *
 * An intent is a *prediction*, never an authorization. Receiving one grants
 * nothing.
 */
export interface PeerIntent {
  epoch: Epoch;
  expected_zones?: ExpectedZones;
  map_digest: MapDigest;
  map_id: MapId;
  plan_version: PlanVersion;
  projected_path?: ProjectedPath;
  protocol_version?: ProtocolVersion;
  robot_id: RobotId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  sent_at_ns: SentAtNs;
  seq: Seq;
  session_id: SessionId;
  time_domain: TimeDomain;
  validity_horizon_ns: ValidityHorizonNs;
}

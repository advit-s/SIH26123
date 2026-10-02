// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneCancelBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type CancelSeq = number;
export type DurablyNonExecutable = boolean;
export type Epoch = string;
export type GrantId = string;
export type ProtocolVersion = string;
export type Reason = string;
export type RequestVersion = number;
export type Requester = string;
export type RequesterSession = string;
export type RunId = string;
export type SchemaVersion = string;
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
export type ZoneId = string;

/**
 * Owner-initiated, durable cancellation.
 *
 * Sent only *after* the owner has persisted ``non_executable = true``. The
 * ``cancel_seq`` makes cancellation idempotent and makes late grants
 * identifiable.
 */
export interface ZoneCancelBody {
  cancel_seq: CancelSeq;
  durably_non_executable: DurablyNonExecutable;
  epoch: Epoch;
  grant_id: GrantId;
  protocol_version?: ProtocolVersion;
  reason: Reason;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  run_id: RunId;
  schema_version?: SchemaVersion;
  time_domain: TimeDomain;
  zone_id: ZoneId;
}

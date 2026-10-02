// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneRequestBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
/**
 * @minItems 3
 * @maxItems 3
 */
export type EntryPose = [unknown, unknown, unknown];
export type Epoch = string;
/**
 * @minItems 3
 * @maxItems 3
 */
export type ExitPose = [unknown, unknown, unknown];
export type ExpiresAtNs = number;
export type MembershipDigest = string;
export type Movement = string;
export type ProtocolVersion = string;
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
 * Request to acquire ``zone_id`` for protected movement ``movement``.
 */
export interface ZoneRequestBody {
  entry_pose: EntryPose;
  epoch: Epoch;
  exit_pose: ExitPose;
  expires_at_ns: ExpiresAtNs;
  membership_digest: MembershipDigest;
  movement: Movement;
  protocol_version?: ProtocolVersion;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  run_id: RunId;
  schema_version?: SchemaVersion;
  time_domain: TimeDomain;
  zone_id: ZoneId;
}

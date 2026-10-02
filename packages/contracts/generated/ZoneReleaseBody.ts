// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneReleaseBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AssertsFullClearance = boolean;
export type Epoch = string;
export type GrantId = string;
export type OccupancySeq = number;
export type ProtocolVersion = string;
export type ReleaseSeq = number;
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
 * Owner declares exit and requests the authority be handed back.
 *
 * Release is **not** effective on send. It becomes effective only after every
 * voter has reconciled the release (a matching release message, never a
 * timeout).
 */
export interface ZoneReleaseBody {
  asserts_full_clearance?: AssertsFullClearance;
  epoch: Epoch;
  grant_id: GrantId;
  occupancy_seq: OccupancySeq;
  protocol_version?: ProtocolVersion;
  release_seq: ReleaseSeq;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  run_id: RunId;
  schema_version?: SchemaVersion;
  time_domain: TimeDomain;
  zone_id: ZoneId;
}

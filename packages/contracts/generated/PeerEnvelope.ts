// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PeerEnvelope.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type CorrelationId = string;
export type Epoch = string;
export type Kind = string;
export type ProtocolVersion = string;
export type RunId = string;
export type Sender = string;
export type SenderSession = string;
export type SentAtNs = number;
export type Seq = number;
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
 * Transport framing metadata. Present on every message, checked on receipt.
 */
export interface PeerEnvelope {
  correlation_id?: CorrelationId;
  epoch: Epoch;
  kind: Kind;
  protocol_version?: ProtocolVersion;
  run_id: RunId;
  sender: Sender;
  sender_session: SenderSession;
  sent_at_ns: SentAtNs;
  seq: Seq;
  time_domain: TimeDomain;
}

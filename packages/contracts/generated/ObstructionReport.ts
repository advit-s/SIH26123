// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ObstructionReport.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Confidence = number;
export type Kind = string;
export type ObservationAgeNs = number;
export type ObservedAtNs = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Position = [unknown, unknown];
export type RobotId = string;
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
export type ZoneId = string | null;

/**
 * Shared observation of an obstruction, with provenance and age.
 */
export interface ObstructionReport {
  confidence?: Confidence;
  kind: Kind;
  observation_age_ns: ObservationAgeNs;
  observed_at_ns: ObservedAtNs;
  position: Position;
  robot_id: RobotId;
  session_id: SessionId;
  time_domain: TimeDomain;
  zone_id?: ZoneId;
}

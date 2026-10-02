// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/MotionCommand.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AngularRadps = number;
export type CommandSeq = number;
export type ExpiresAtNs = number;
export type HoldPosition = boolean;
export type IssuedAtNs = number;
export type LinearMps = number;
export type RobotId = string;
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
 * The only thing an agent may hand to the world.
 *
 * ``expires_at_ns`` is in the agent's declared ``time_domain``; the world
 * compares it against the clock of that same domain. Expiry causes *braking at
 * the configured deceleration*, never an instantaneous stop.
 */
export interface MotionCommand {
  angular_radps: AngularRadps;
  command_seq: CommandSeq;
  expires_at_ns: ExpiresAtNs;
  hold_position?: HoldPosition;
  issued_at_ns: IssuedAtNs;
  linear_mps: LinearMps;
  robot_id: RobotId;
  time_domain: TimeDomain;
}

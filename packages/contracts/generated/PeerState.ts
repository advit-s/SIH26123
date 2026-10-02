// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PeerState.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type BatteryFraction = number | null;
export type BatterySource = string;
export type CarryingTaskId = string | null;
/**
 * @minItems 3
 * @maxItems 3
 */
export type Pose = [unknown, unknown, unknown];
export type RobotId = string;
export type SentAtNs = number;
export type Seq = number;
export type SessionId = string;
export type StopReason = string;
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
export type UncertaintyM = number;
export type UncertaintyRad = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Velocity = [unknown, unknown];

/**
 * Published robot state. A claim, never ground truth.
 */
export interface PeerState {
  battery_fraction?: BatteryFraction;
  battery_source?: BatterySource;
  carrying_task_id?: CarryingTaskId;
  pose: Pose;
  robot_id: RobotId;
  sent_at_ns: SentAtNs;
  seq: Seq;
  session_id: SessionId;
  stop_reason?: StopReason;
  time_domain: TimeDomain;
  uncertainty_m: UncertaintyM;
  uncertainty_rad: UncertaintyRad;
  velocity: Velocity;
}

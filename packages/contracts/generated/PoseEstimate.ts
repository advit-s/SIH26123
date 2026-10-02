// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PoseEstimate.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type FrameId = string;
export type Fused = boolean;
export type MapId = string;
export type ObservedAtNs = number;
export type Theta = number;
export type X = number;
export type Y = number;
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
export type Kind = "gaussian_sigma" | "hard_bound" | "unknown";
export type MaxM = number;
export type SigmaM = number;
export type SigmaRad = number;
export type Source = string;

/**
 * An estimate with its observation time and uncertainty.
 *
 * This is deliberately *not* a pose: an estimate can be stale, and the system
 * must be able to represent "last known pose, age 3.2 s, uncertain".
 */
export interface PoseEstimate {
  frame_id?: FrameId;
  fused?: Fused;
  map_id: MapId;
  observed_at_ns: ObservedAtNs;
  pose: Pose2;
  time_domain: TimeDomain;
  uncertainty: UncertaintyModel;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}
/**
 * Declared localisation uncertainty. Never implicit.
 *
 * ``kind`` must be reported so a consumer can tell a modelled sigma from a
 * hard bound. ``sigma_m`` is the 1-sigma standard deviation of planar
 * position error; ``sigma_rad`` the 1-sigma of heading error.
 */
export interface UncertaintyModel {
  kind: Kind;
  max_m?: MaxM;
  sigma_m?: SigmaM;
  sigma_rad?: SigmaRad;
  source?: Source;
}

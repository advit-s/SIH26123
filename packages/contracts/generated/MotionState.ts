// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/MotionState.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type ActuationEnabled = boolean;
/**
 * Physical state of the actuator chain. Never inferred from a flag.
 */
export type ActuatorState = "enabled" | "disabled" | "braking" | "watchdog_braking" | "estop" | "fault";
export type AngularVelocityRadps = number;
export type CommandExpiresAtNs = number | null;
export type CommandSeq = number;
export type CommandedAngularRadps = number;
export type CommandedLinearMps = number;
export type LinearVelocityMps = number;
/**
 * Why motion is or is not happening. Every stop is attributed.
 */
export type StopReason =
  | "none"
  | "command_expired"
  | "safety_gate_veto"
  | "zone_authority_missing"
  | "freshness_uncertain"
  | "obstacle_in_path"
  | "stale_localisation"
  | "control_loop_stalled"
  | "operator_request"
  | "scheduled_stop"
  | "workload_complete"
  | "crash_recovery"
  | "actuator_fault";

/**
 * Observed motion, the command that was asked for, and the actuator story.
 */
export interface MotionState {
  actuation_enabled?: ActuationEnabled;
  actuator?: ActuatorState;
  angular_velocity_radps?: AngularVelocityRadps;
  command_expires_at_ns?: CommandExpiresAtNs;
  command_seq?: CommandSeq;
  commanded_angular_radps?: CommandedAngularRadps;
  commanded_linear_mps?: CommandedLinearMps;
  linear_velocity_mps?: LinearVelocityMps;
  stop_reason?: StopReason;
}

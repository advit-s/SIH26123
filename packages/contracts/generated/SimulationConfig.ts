// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/SimulationConfig.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AccelMps2 = number;
export type AngularAccelRadps2 = number;
export type CommandTtlS = number;
export type DecelMps2 = number;
export type MaxAngularRadps = number;
export type MaxLinearMps = number;
export type DrainPerMetreC = number;
export type DrainPerSecondIdleC = number;
export type ServiceDrainC = number;
export type Source = string;
export type StartFraction = number;
export type BlockedAwareRouting = boolean;
export type DisableSafetyGate = boolean;
export type FairnessAwarePriority = boolean;
export type TaskReassignment = boolean;
export type TemporalPlanning = boolean;
export type TimerExpiryOccupancy = boolean;
export type UnsafeFlags = string[];
export type UnsafeResearchVariant = boolean;
export type PhysicalActuationEnabled = boolean;
export type PhysicsStepHz = number;
export type CancelTimeoutS = number;
export type ControlPeriodS = number;
export type FreshnessHorizonS = number;
export type HeartbeatPeriodS = number;
export type IntentPublishPeriodS = number;
export type IntentValidityS = number;
export type QueueTiebreakS = number;
export type ReleaseTimeoutS = number;
export type SolicitTimeoutS = number;
export type StatePublishPeriodS = number;
export type SchemaVersion = string;
export type AngularResolutionRad = number;
export type DropoutProbability = number;
export type FieldOfViewRad = number;
export type HeadingSigmaRad = number;
export type ObservationLatencyS = number;
export type PositionSigmaM = number;
export type RangeM = number;
export type RangeNoiseM = number;
export type SimulatedActuationEnabled = boolean;
export type StatePublishHz = number;
export type BrakingDecelMps2 = number;
export type ExtraMarginM = number;
export type MaxSpeedMps = number;
export type ReactionTimeS = number;

export interface SimulationConfig {
  actuator?: ActuatorModel;
  battery?: BatteryModel;
  features?: FeatureFlags;
  physical_actuation_enabled?: PhysicalActuationEnabled;
  physics_step_hz?: PhysicsStepHz;
  protocol?: ProtocolTiming;
  schema_version?: SchemaVersion;
  sensor?: SensorModel;
  simulated_actuation_enabled?: SimulatedActuationEnabled;
  state_publish_hz?: StatePublishHz;
  stopping?: StoppingBudget;
}
export interface ActuatorModel {
  accel_mps2?: AccelMps2;
  angular_accel_radps2?: AngularAccelRadps2;
  command_ttl_s?: CommandTtlS;
  decel_mps2?: DecelMps2;
  max_angular_radps?: MaxAngularRadps;
  max_linear_mps?: MaxLinearMps;
}
/**
 * Declared battery model. UI must state ``source`` alongside any value.
 */
export interface BatteryModel {
  drain_per_metre_c?: DrainPerMetreC;
  drain_per_second_idle_c?: DrainPerSecondIdleC;
  service_drain_c?: ServiceDrainC;
  source?: Source;
  start_fraction?: StartFraction;
}
/**
 * Ablation switches. Unsafe research variants are namespaced so they can
 * never be enabled by accident in a physical deployment.
 */
export interface FeatureFlags {
  blocked_aware_routing?: BlockedAwareRouting;
  disable_safety_gate?: DisableSafetyGate;
  fairness_aware_priority?: FairnessAwarePriority;
  task_reassignment?: TaskReassignment;
  temporal_planning?: TemporalPlanning;
  timer_expiry_occupancy?: TimerExpiryOccupancy;
  unsafe_flags?: UnsafeFlags;
  unsafe_research_variant?: UnsafeResearchVariant;
}
/**
 * All protocol deadlines live in the agent's declared time domain.
 */
export interface ProtocolTiming {
  cancel_timeout_s?: CancelTimeoutS;
  control_period_s?: ControlPeriodS;
  freshness_horizon_s?: FreshnessHorizonS;
  heartbeat_period_s?: HeartbeatPeriodS;
  intent_publish_period_s?: IntentPublishPeriodS;
  intent_validity_s?: IntentValidityS;
  queue_tiebreak_s?: QueueTiebreakS;
  release_timeout_s?: ReleaseTimeoutS;
  solicit_timeout_s?: SolicitTimeoutS;
  state_publish_period_s?: StatePublishPeriodS;
}
/**
 * Declared sensing limits and noise. Every value is a simulation
 * configuration, labelled as such wherever it is displayed.
 */
export interface SensorModel {
  angular_resolution_rad?: AngularResolutionRad;
  dropout_probability?: DropoutProbability;
  field_of_view_rad?: FieldOfViewRad;
  heading_sigma_rad?: HeadingSigmaRad;
  observation_latency_s?: ObservationLatencyS;
  position_sigma_m?: PositionSigmaM;
  range_m?: RangeM;
  range_noise_m?: RangeNoiseM;
}
/**
 * Derived stopping distance parameters.
 *
 * These are *configured assumptions* for a low-speed simulation. They are not
 * certified real-world limits and are never presented as a safety guarantee.
 *
 * Example from the brief at v=0.4 m/s, t_r=0.30 s, a=0.8 m/s^2, margin=0.10 m:
 * reaction 0.12 m + braking 0.10 m + margin 0.10 m = 0.32 m.
 */
export interface StoppingBudget {
  braking_decel_mps2?: BrakingDecelMps2;
  extra_margin_m?: ExtraMarginM;
  max_speed_mps?: MaxSpeedMps;
  reaction_time_s?: ReactionTimeS;
}

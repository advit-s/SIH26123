// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/FeatureFlags.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type BlockedAwareRouting = boolean;
export type DisableSafetyGate = boolean;
export type FairnessAwarePriority = boolean;
export type TaskReassignment = boolean;
export type TemporalPlanning = boolean;
export type TimerExpiryOccupancy = boolean;
export type UnsafeFlags = string[];
export type UnsafeResearchVariant = boolean;

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

// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RunPolicy.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AssignmentPolicy = "none" | "local_auction";
export type ComparisonMode = "coordination_only" | "end_to_end";
/**
 * The two policies that must sit behind identical interfaces.
 */
export type CoordinationPolicy = "stop_and_wait" | "canonical_sequential";
export type FaultSeed = number;
export type PlannerSeed = number;
export type RoutingPolicy = "shortest" | "blocked_aware" | "temporal_sipp_approx";
export type SensorSeed = number;

export interface RunPolicy {
  assignment?: AssignmentPolicy;
  comparison_mode?: ComparisonMode;
  coordination?: CoordinationPolicy;
  fault_seed?: FaultSeed;
  planner_seed?: PlannerSeed;
  routing?: RoutingPolicy;
  sensor_seed?: SensorSeed;
}

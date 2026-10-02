// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/BatteryState.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type DrainModel = string | null;
export type EstimatedRangeM = number | null;
export type Fraction = number | null;
/**
 * Provenance of a battery number. Never guessed.
 */
export type BatterySource = "measured" | "simulated" | "estimated" | "unavailable";

export interface BatteryState {
  drain_model?: DrainModel;
  estimated_range_m?: EstimatedRangeM;
  fraction?: Fraction;
  source: BatterySource;
}

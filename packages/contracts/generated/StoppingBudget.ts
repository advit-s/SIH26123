// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/StoppingBudget.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type BrakingDecelMps2 = number;
export type ExtraMarginM = number;
export type MaxSpeedMps = number;
export type ReactionTimeS = number;

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

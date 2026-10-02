// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/TelemetrySample.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AngularRadps = number;
export type BatteryFraction = number | null;
export type LinearMps = number;
export type RobotId = string;
export type RunId = string;
export type SampleIndex = number;
export type SimTimeS = number;
export type StopReason = string;
export type Theta = number;
export type X = number;
export type Y = number;

/**
 * Replaceable high-rate sample. Never an authority or evaluation record.
 */
export interface TelemetrySample {
  angular_radps: AngularRadps;
  battery_fraction?: BatteryFraction;
  linear_mps: LinearMps;
  robot_id: RobotId;
  run_id: RunId;
  sample_index: SampleIndex;
  sim_time_s: SimTimeS;
  stop_reason?: StopReason;
  theta: Theta;
  x: X;
  y: Y;
}

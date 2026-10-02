// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/MetricValue.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type MetricAvailability = "measured" | "unavailable" | "excluded";
export type Key = string;
export type Note = string;
export type SampleCount = number | null;
export type Value = number | null;

export interface MetricValue {
  availability: MetricAvailability;
  key: Key;
  note?: Note;
  sample_count?: SampleCount;
  value?: Value;
}

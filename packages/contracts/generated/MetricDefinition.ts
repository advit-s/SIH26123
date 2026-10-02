// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/MetricDefinition.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Description = string;
export type Direction = "higher_is_better" | "lower_is_better" | "neutral";
export type Headline = boolean;
export type Key = string;
export type Label = string;
export type Unit = string;
export type ZeroIsNotProof = boolean;

/**
 * A metric is defined once and referenced everywhere.
 */
export interface MetricDefinition {
  description: Description;
  direction?: Direction;
  headline?: Headline;
  key: Key;
  label: Label;
  unit: Unit;
  zero_is_not_proof?: ZeroIsNotProof;
}

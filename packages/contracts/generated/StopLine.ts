// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/StopLine.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Approach = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type End = [unknown, unknown];
export type Id = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Start = [unknown, unknown];
export type ZoneId = string;

/**
 * Physical line a robot must not cross without the named authority.
 *
 * ``zone_id`` names the authority required. This is the geometric anchor for
 * "stop-line violation", which the evaluator checks independently.
 */
export interface StopLine {
  approach?: Approach;
  end: End;
  id: Id;
  start: Start;
  zone_id: ZoneId;
}

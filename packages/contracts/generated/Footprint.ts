// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Footprint.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type LengthM = number;
export type PayloadLengthM = number;
export type PayloadOffsetM = number;
export type PayloadWidthM = number;
export type TurningRadiusM = number;
export type WidthM = number;

/**
 * Finite robot geometry, plus payload overhang when carrying.
 *
 * ``length_m``/``width_m`` describe the chassis. ``payload_length_m`` and
 * ``payload_width_m`` describe the largest carried load. ``payload_offset_m``
 * is the distance from the chassis centre to the payload centre along the
 * chassis ``+x`` axis (positive = front overhang).
 */
export interface Footprint {
  length_m: LengthM;
  payload_length_m?: PayloadLengthM;
  payload_offset_m?: PayloadOffsetM;
  payload_width_m?: PayloadWidthM;
  turning_radius_m?: TurningRadiusM;
  width_m: WidthM;
}

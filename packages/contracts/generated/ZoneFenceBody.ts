// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneFenceBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Epoch = string;
export type FencedBy = string;
export type OperatorAuthorised = boolean;
export type PreviousHolder = string | null;
export type PreviousRequesterSession = string | null;
export type Reason = string;
export type RunId = string;
export type SchemaVersion = string;
export type ZoneId = string;

/**
 * Supervised, explicit fencing of a zone whose holder failed.
 *
 * There is deliberately no "force release" message. Fencing makes the zone
 * unavailable and is logged as an explicit, operator-visible state change.
 */
export interface ZoneFenceBody {
  epoch: Epoch;
  fenced_by: FencedBy;
  operator_authorised?: OperatorAuthorised;
  previous_holder?: PreviousHolder;
  previous_requester_session?: PreviousRequesterSession;
  reason: Reason;
  run_id: RunId;
  schema_version?: SchemaVersion;
  zone_id: ZoneId;
}

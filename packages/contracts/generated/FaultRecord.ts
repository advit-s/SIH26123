// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/FaultRecord.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Digest = string;
export type EndedAtNs = number | null;
export type FaultId = string;
export type InjectedBy = string;
export type Manual = boolean;
export type Note = string;
export type StartedAtNs = number;
export type FaultState = "scheduled" | "active" | "elapsed" | "cancelled" | "failed";

/**
 * A runtime observation of a fault's state. Manual injections become
 * timestamped run events; scheduled ones are part of the scenario snapshot.
 */
export interface FaultRecord {
  digest?: Digest;
  ended_at_ns?: EndedAtNs;
  fault_id: FaultId;
  injected_by?: InjectedBy;
  manual?: Manual;
  note?: Note;
  started_at_ns: StartedAtNs;
  state: FaultState;
}

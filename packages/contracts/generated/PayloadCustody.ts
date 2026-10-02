// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PayloadCustody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type CustodyVersion = number;
export type DeliveredAtNs = number | null;
export type Holder = string | null;
export type HolderSession = string | null;
export type PickedUpAtNs = number | null;
export type CustodyState = "at_station" | "attached" | "delivered" | "awaiting_recovery";
export type TaskId = string;

/**
 * Physical possession. Never inferred from ownership.
 */
export interface PayloadCustody {
  custody_version?: CustodyVersion;
  delivered_at_ns?: DeliveredAtNs;
  holder?: Holder;
  holder_session?: HolderSession;
  picked_up_at_ns?: PickedUpAtNs;
  state?: CustodyState;
  task_id: TaskId;
}

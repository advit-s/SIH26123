// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/TaskOwnership.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AllocationRound = number;
export type AwardedAtNs = number;
export type BidSetDigest = string;
export type Evidence = string;
export type Owner = string | null;
export type OwnerSession = string | null;
export type OwnershipVersion = number;
export type TaskOwnershipState = "unowned" | "reserved" | "owned" | "released" | "recovery_required";
export type TaskId = string;

/**
 * Logical ownership. Monotonic version; stale transitions are refused.
 */
export interface TaskOwnership {
  allocation_round: AllocationRound;
  awarded_at_ns: AwardedAtNs;
  bid_set_digest?: BidSetDigest;
  evidence?: Evidence;
  owner?: Owner;
  owner_session?: OwnerSession;
  ownership_version?: OwnershipVersion;
  state?: TaskOwnershipState;
  task_id: TaskId;
}

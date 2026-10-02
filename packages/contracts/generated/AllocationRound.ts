// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/AllocationRound.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Epoch = string;
export type Index = number;
export type OpenedAtNs = number;
export type ReleasedTaskIds = string[];
export type ReserveCapacityOnTimeout = boolean;
export type RoundId = string;
export type RunId = string;
export type SnapshotDigest = string;

/**
 * Immutable round identity. Serialising rounds is what prevents a robot
 * winning two auctions against the same availability.
 */
export interface AllocationRound {
  epoch: Epoch;
  index: Index;
  opened_at_ns: OpenedAtNs;
  released_task_ids?: ReleasedTaskIds;
  reserve_capacity_on_timeout?: ReserveCapacityOnTimeout;
  round_id: RoundId;
  run_id: RunId;
  snapshot_digest: SnapshotDigest;
}

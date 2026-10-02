// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/TaskAward.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AnnouncedBy = string;
export type AtNs = number;
export type BidSetDigest = string;
export type Epoch = string;
export type ExplicitNoBid = boolean;
export type OwnershipVersion = number;
export type RoundId = string;
export type RunId = string;
export type SchemaVersion = string;
export type TaskId = string;
export type Winner = string;
export type WinnerSession = string;

/**
 * Announcement of the outcome of one allocation round.
 *
 * Awarding is deterministic given the same bid set: lowest ``total_cost``
 * among feasible bids, ties broken by ``tie_break`` then ``robot_id``. A robot
 * computes this locally from received bids; no backend picks winners.
 */
export interface TaskAward {
  announced_by?: AnnouncedBy;
  at_ns: AtNs;
  bid_set_digest: BidSetDigest;
  epoch: Epoch;
  explicit_no_bid?: ExplicitNoBid;
  ownership_version: OwnershipVersion;
  round_id: RoundId;
  run_id: RunId;
  schema_version?: SchemaVersion;
  task_id: TaskId;
  winner: Winner;
  winner_session: WinnerSession;
}

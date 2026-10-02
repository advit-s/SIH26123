// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Membership.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type CanonicalOrder = string[];
export type Digest = string;
export type Epoch = string;
export type Members = string[];
export type RunId = string;
/**
 * Controlled reconciliation state of the peer set.
 */
export type MembershipState = "frozen" | "reconciling" | "fenced";

/**
 * The immutable peer set for a run epoch, plus its reconciliation state.
 */
export interface Membership {
  canonical_order?: CanonicalOrder;
  digest?: Digest;
  epoch: Epoch;
  members: Members;
  run_id: RunId;
  state?: MembershipState;
}

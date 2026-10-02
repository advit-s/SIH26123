"""Distributed task allocation: local bids, round-serialised awards, custody.

Authority boundaries encoded here (AGENTS.md rules 1, 3 and 6):

* **Bids are local.** :func:`~niharamesh.allocation.bids.compute_bid` is a pure
  function of what *one* robot believes - its own pose, its own battery, its own
  planner output and the zone claims *it* has been told. No backend, evaluator or
  simulator state reaches it, and it is deterministic.
* **Awards are computed locally by every robot** from the same bid set. No
  component picks a winner; see
  :func:`~niharamesh.allocation.auction.compute_award`.
* **Rounds are serialised**, so a robot cannot win two auctions against the same
  availability.
* **Disagreement is reported, never papered over.** If two robots compute
  different bid-set digests, the result is
  :class:`~niharamesh.allocation.auction.PartitionConsensusState.INCONSISTENT` and
  the contested task pauses.

Nothing here is I/O. Every exchange is a typed value object.
"""

from __future__ import annotations

from niharamesh.allocation.auction import (
    AllocationEvent,
    AllocationEventKind,
    AllocationKind,
    AllocationMessage,
    AllocationMessageEnvelope,
    AwardOutcome,
    LocalAuction,
    PartitionConsensusState,
    RoundSerialisationError,
    bid_set_digest,
    compute_award,
)
from niharamesh.allocation.bids import (
    BidComponentValues,
    BidRequest,
    BidStreams,
    CostModel,
    TravelEstimate,
    ZoneClaim,
    compute_bid,
    tie_break_of,
)
from niharamesh.allocation.custody import (
    CustodyEffect,
    CustodyLedger,
    CustodyViolation,
    RecoveryOutcome,
    RecoveryPath,
)

__all__ = [
    "AllocationEvent",
    "AllocationEventKind",
    "AllocationKind",
    "AllocationMessage",
    "AllocationMessageEnvelope",
    "AwardOutcome",
    "BidComponentValues",
    "BidRequest",
    "BidStreams",
    "CostModel",
    "CustodyEffect",
    "CustodyLedger",
    "CustodyViolation",
    "LocalAuction",
    "PartitionConsensusState",
    "RecoveryOutcome",
    "RecoveryPath",
    "RoundSerialisationError",
    "TravelEstimate",
    "ZoneClaim",
    "bid_set_digest",
    "compute_award",
    "compute_bid",
    "tie_break_of",
]

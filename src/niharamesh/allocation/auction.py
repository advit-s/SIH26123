"""Round-serialised local auction. Every robot computes the award; none is told.

The award rule
--------------
Given the bids a robot holds for one task, the winner is the first of::

    sorted(feasible bids, key=lambda b: (b.total_cost, b.tie_break, b.robot_id))

and :func:`bid_set_digest` is the sha256 over those same rows in that same order.
Both are pure functions of the bid set, so two robots holding the same bids *must*
agree - and when they do not, that is an observable inconsistency to record, not
something to reconcile silently.

Round serialisation
-------------------
One round at a time, per robot, with an immutable ``snapshot_digest``:

* a bid whose ``round_id`` differs from the open round is discarded;
* a bid whose ``snapshot_digest`` differs is discarded - it was priced against a
  different world;
* a robot holds **at most one live bid per round**. While that bid is live its
  capacity is reserved and it refuses to bid on anything else. This is what makes
  winning two auctions against the same availability impossible. It protects
  *assignment feasibility* only; it says nothing about physical coexistence,
  which is the zone-grant protocol's job (and only that job).

Wire contract
-------------
The domain :class:`~niharamesh.domain.coordination.PeerMessage` body union carries
no auction body, and this module does not edit a file another workstream owns. It
therefore defines its own typed record, :class:`AllocationMessage`, and documents
the mapping point explicitly:

* ``TASK_BID`` / ``EXPLICIT_NO_BID`` both carry a
  :class:`~niharamesh.domain.task.TaskBid`. An *explicit no-bid* is an infeasible
  ``TaskBid`` with a reason - silence is never acceptable, because a missing
  message is indistinguishable from a lost one.
* ``TASK_AWARD`` carries a :class:`~niharamesh.domain.task.TaskAward`. A round
  nobody bid on produces an explicit no-bid record, never a ``TaskAward`` with a
  fabricated winner (that type requires a real ``RobotId``).

:meth:`LocalAuction.handle` accepts either an ``AllocationMessage`` or a
``PeerMessage``. A ``PeerMessage`` whose kind is not an auction kind is recorded
in :attr:`LocalAuction.rejected_messages` and logged - recorded, not dropped.

Partition behaviour
-------------------
:meth:`LocalAuction.consensus` returns:

``agreed``
    Every admitted member reported a bid or an explicit no-bid for this task in
    this round, and no peer's announced award contradicts the local computation.
``paused``
    Some admitted member has not been heard from. The contested assignment pauses:
    the robot does not start the task, because it cannot establish agreement.
``inconsistent``
    Every member has been heard from, yet a peer's announced award names a
    different winner or a different bid-set digest. Recorded as an event.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from niharamesh.allocation.bids import BidRequest, BidStreams, CostModel, compute_bid, tie_break_of
from niharamesh.domain.coordination import PeerMessage
from niharamesh.domain.identity import Membership
from niharamesh.domain.task import (
    AllocationRound,
    Task,
    TaskAward,
    TaskBid,
    TaskOwnership,
    TaskOwnershipState,
    TaskState,
    TaskTransition,
    is_legal_task_transition,
)
from niharamesh.domain.units import TimeDomain

__all__ = [
    "AllocationEvent",
    "AllocationEventKind",
    "AllocationKind",
    "AllocationMessage",
    "AllocationMessageEnvelope",
    "AwardOutcome",
    "LocalAuction",
    "PartitionConsensusState",
    "RoundSerialisationError",
    "TransitionOutcome",
    "bid_set_digest",
    "compute_award",
]


class RoundSerialisationError(RuntimeError):
    """A round was opened while another was still open, or bid on outside one."""


class AllocationKind(StrEnum):
    TASK_BID = "task_bid"
    EXPLICIT_NO_BID = "explicit_no_bid"
    TASK_AWARD = "task_award"


class PartitionConsensusState(StrEnum):
    AGREED = "agreed"
    PAUSED = "paused"
    INCONSISTENT = "inconsistent"


class AllocationEventKind(StrEnum):
    ROUND_OPENED = "round_opened"
    ROUND_CLOSED = "round_closed"
    BID_SENT = "bid_sent"
    NO_BID_SENT = "no_bid_sent"
    BID_RECEIVED = "bid_received"
    NO_BID_RECEIVED = "no_bid_received"
    BID_DISCARDED_ROUND = "bid_discarded_round"
    BID_DISCARDED_SNAPSHOT = "bid_discarded_snapshot"
    BID_DISCARDED_REPLAY = "bid_discarded_replay"
    BID_DISCARDED_EPOCH = "bid_discarded_epoch"
    MESSAGE_UNSUPPORTED = "message_unsupported"
    AWARD_COMPUTED = "award_computed"
    AWARD_ANNOUNCED = "award_announced"
    EXPLICIT_NO_BID = "explicit_no_bid"
    CONSENSUS_AGREED = "consensus_agreed"
    CONSENSUS_PAUSED = "consensus_paused"
    CONSENSUS_INCONSISTENT = "consensus_inconsistent"
    STALE_OWNERSHIP_REFUSED = "stale_ownership_refused"
    CAPACITY_REFUSED = "capacity_refused"
    PEER_CAPACITY_VIOLATION = "peer_capacity_violation"
    TRANSITION_REFUSED = "transition_refused"
    TRANSITION_APPLIED = "transition_applied"


@dataclass(frozen=True, slots=True)
class AllocationEvent:
    """One explicit, attributable thing that happened."""

    kind: AllocationEventKind
    detail: str
    task_id: str = ""
    robot_id: str = ""
    at_ns: int = 0


@dataclass(frozen=True, slots=True)
class AllocationMessageEnvelope:
    """Per-message framing. ``snapshot_digest`` is what makes staleness checkable."""

    kind: AllocationKind
    sender: str
    sender_session: str
    seq: int
    sent_at_ns: int
    round_id: str
    snapshot_digest: str
    time_domain: TimeDomain = TimeDomain.LOGICAL


@dataclass(frozen=True, slots=True)
class AllocationMessage:
    """Typed auction wire record. See the module docstring for the mapping point."""

    envelope: AllocationMessageEnvelope
    body: TaskBid | TaskAward

    @property
    def task_id(self) -> str:
        return self.body.task_id

    @property
    def round_id(self) -> str:
        return self.envelope.round_id

    @property
    def sender(self) -> str:
        return self.envelope.sender

    def is_no_bid(self) -> bool:
        return self.envelope.kind is AllocationKind.EXPLICIT_NO_BID

    @staticmethod
    def of_bid(bid: TaskBid, sender_session: str, seq: int, snapshot_digest: str) -> AllocationMessage:
        kind = AllocationKind.TASK_BID if bid.feasible else AllocationKind.EXPLICIT_NO_BID
        return AllocationMessage(
            envelope=AllocationMessageEnvelope(
                kind=kind,
                sender=bid.robot_id,
                sender_session=sender_session or bid.robot_session,
                seq=seq,
                sent_at_ns=bid.at_ns,
                round_id=bid.round_id,
                snapshot_digest=snapshot_digest,
            ),
            body=bid,
        )

    @staticmethod
    def of_award(award: TaskAward, sender_session: str, seq: int, snapshot_digest: str) -> AllocationMessage:
        return AllocationMessage(
            envelope=AllocationMessageEnvelope(
                kind=AllocationKind.TASK_AWARD,
                sender=award.announced_by,
                sender_session=sender_session,
                seq=seq,
                sent_at_ns=award.at_ns,
                round_id=award.round_id,
                snapshot_digest=snapshot_digest,
            ),
            body=award,
        )


@dataclass(frozen=True, slots=True)
class AwardOutcome:
    """The locally computed result for one task in one round.

    Exactly one of ``award`` / ``no_bid`` is set. ``no_bid`` is an explicit
    record that nobody bid, so a silent round is impossible.
    """

    task_id: str
    round_id: str
    bid_set_digest: str
    winner: str = ""
    explicit_no_bid: bool = False
    no_bid_reason: str = ""
    award: TaskAward | None = None
    no_bid: AllocationMessage | None = None
    feasible_bids: int = 0

    @property
    def decided(self) -> bool:
        return self.award is not None or self.explicit_no_bid


@dataclass(frozen=True, slots=True)
class TransitionOutcome:
    accepted: bool
    reason: str
    task_id: str
    to_state: TaskState
    from_state: TaskState
    ownership_version: int


def bid_set_digest(bids: Iterable[TaskBid]) -> str:
    """sha256 over the sorted feasible bid rows. 64 lowercase hex characters.

    Only *feasible* bids are hashed: an infeasible bid cannot win, so including it
    would make the digest depend on whether a robot happened to mention something
    irrelevant. Infeasible bids still matter for the *explicit no-bid* count,
    which is why they are retained in the bid set itself.
    """
    rows = sorted(
        (bid.robot_id, bid.robot_session, f"{bid.total_cost:.6f}", str(bid.tie_break))
        for bid in bids
        if bid.feasible
    )
    payload = "\n".join("|".join(row) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_award(
    task_id: str,
    bids: Sequence[TaskBid],
    *,
    run_id: str,
    epoch: str,
    round_id: str,
    round_index: int,
    now_ns: int,
    announced_by: str,
) -> AwardOutcome:
    """The award rule as a free function. No backend role exists anywhere.

    ``award.ownership_version`` is ``round_index + 1`` and is only a *nominal*
    value; the authoritative monotonic version lives in
    :class:`~niharamesh.domain.task.TaskOwnership`, which
    :meth:`LocalAuction.commit` increments. Nominal is honest; fabricating a
    version here without consulting the ledger would not be.
    """
    digest = bid_set_digest(bids)
    feasible = [bid for bid in bids if bid.feasible]
    if not feasible:
        reason = "no_bid_in_round" if not bids else "no_feasible_bid_in_round"
        return AwardOutcome(
            task_id=task_id,
            round_id=round_id,
            bid_set_digest=digest,
            explicit_no_bid=True,
            no_bid_reason=reason,
            feasible_bids=0,
        )
    ranked = sorted(feasible, key=lambda b: (b.total_cost, b.tie_break, b.robot_id))
    winner = ranked[0]
    award = TaskAward(
        run_id=run_id,
        epoch=epoch,
        task_id=task_id,
        round_id=round_id,
        winner=winner.robot_id,
        winner_session=winner.robot_session,
        ownership_version=round_index + 1,
        bid_set_digest=digest,
        explicit_no_bid=False,
        announced_by=announced_by,
        at_ns=now_ns,
    )
    return AwardOutcome(
        task_id=task_id,
        round_id=round_id,
        bid_set_digest=digest,
        winner=winner.robot_id,
        award=award,
        feasible_bids=len(feasible),
    )


def bid_rank(bid: TaskBid) -> tuple[float, int, str]:
    """The total order used everywhere: cost, then tie-break, then task id."""
    return (bid.total_cost, bid.tie_break, bid.task_id)


class LocalAuction:
    """One robot's half of the allocation protocol. Implements ``TaskAllocator``."""

    def __init__(
        self,
        *,
        robot_id: str,
        robot_session: str,
        run_id: str,
        epoch: str,
        membership: Membership,
        capacity: int = 1,
        cost_model: CostModel | None = None,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if not membership.contains(robot_id):
            raise ValueError("this robot is not an admitted member of the membership")
        self.robot_id = robot_id
        self.robot_session = robot_session
        self.run_id = run_id
        self.epoch = epoch
        self.membership = membership
        self.capacity = capacity
        self.cost_model = cost_model if cost_model is not None else CostModel()
        self.events: list[AllocationEvent] = []
        self.rejected_messages: list[tuple[str, str]] = []
        self._round: AllocationRound | None = None
        self._seq = 0
        self._own_bids: dict[str, TaskBid] = {}
        self._received: dict[str, dict[str, TaskBid]] = {}
        self._last_seq: dict[str, int] = {}
        self._sessions: dict[str, str] = {self.robot_id: robot_session}
        self._ownership: dict[str, TaskOwnership] = {}
        self._task_state: dict[str, TaskState] = {}
        self._round_awards: list[TaskAward] = []
        self._live_bid_task: str | None = None
        self._disagreements: dict[str, str] = {}
        self._peer_winners: dict[tuple[str, str], str] = {}
        self._consensus_seen: dict[str, PartitionConsensusState] = {}

    # ------------------------------------------------------------------
    # round lifecycle
    # ------------------------------------------------------------------

    @property
    def round(self) -> AllocationRound | None:
        return self._round

    @property
    def live_bid_task(self) -> str | None:
        """Task this robot has bid on in the open round, if any."""
        return self._live_bid_task

    def open_round(self, allocation_round: AllocationRound, *, now_ns: int = 0) -> None:
        """Open a caller-declared round. Identity comes from the task feed."""
        if self._round is not None:
            detail = f" with a live bid on {self._live_bid_task}" if self._live_bid_task else ""
            raise RoundSerialisationError(f"round {self._round.round_id} is still open{detail}")
        if allocation_round.run_id != self.run_id:
            raise ValueError("AllocationRound.run_id does not match this allocator")
        if allocation_round.epoch != self.epoch:
            raise ValueError("AllocationRound.epoch does not match this allocator")
        self._round = allocation_round
        self._own_bids = {}
        self._received = {}
        self._round_awards = []
        self._live_bid_task = None
        self._disagreements = {}
        self._peer_winners = {}
        self._consensus_seen = {}
        self._log(
            AllocationEventKind.ROUND_OPENED,
            f"round {allocation_round.round_id} snapshot {allocation_round.snapshot_digest}",
            at_ns=now_ns,
        )

    def close_round(self, *, now_ns: int = 0) -> None:
        """Close the round. Refuses while a bid is live.

        Closing with a live bid would leave peers holding a reservation this robot
        cannot honour, so the caller must resolve the bid first. No timer closes a
        round on a robot's behalf.
        """
        if self._round is None:
            return
        if self._live_bid_task is not None:
            raise RoundSerialisationError(
                f"cannot close round {self._round.round_id}: bid on {self._live_bid_task} is still live"
            )
        self._log(AllocationEventKind.ROUND_CLOSED, f"round {self._round.round_id}", at_ns=now_ns)
        self._round = None

    # ------------------------------------------------------------------
    # bidding
    # ------------------------------------------------------------------

    def submit(
        self,
        task: Task,
        robot_state: BidRequest,
        streams: BidStreams,
        *,
        cost_model: CostModel | None = None,
    ) -> TaskBid:
        """Price *task* locally. Nothing is committed until :meth:`consider`."""
        if self._round is None:
            raise RoundSerialisationError("no allocation round is open")
        model = cost_model if cost_model is not None else self.cost_model
        return compute_bid(task, robot_state, model, streams)

    def consider(self, bid: TaskBid) -> TaskBid:
        """Commit at most one live bid for the open round.

        A live bid reserves this robot's capacity for the rest of the round: every
        further request returns an explicit ``live_bid_reserved`` no-bid rather
        than a second commitment.
        """
        if self._round is None:
            raise RoundSerialisationError("no allocation round is open")
        if bid.round_id != self._round.round_id:
            raise RoundSerialisationError(
                f"bid for round {bid.round_id} while {self._round.round_id} is open"
            )
        self._own_bids[bid.task_id] = bid
        self._received.setdefault(bid.task_id, {})[self.robot_id] = bid
        if not bid.feasible:
            self._log(
                AllocationEventKind.NO_BID_SENT,
                f"explicit no-bid: {bid.infeasible_reason}",
                task_id=bid.task_id,
                at_ns=bid.at_ns,
            )
            return bid
        if self._live_bid_task is not None and self._live_bid_task != bid.task_id:
            self._log(
                AllocationEventKind.CAPACITY_REFUSED,
                f"capacity reserved by live bid on {self._live_bid_task}",
                task_id=bid.task_id,
                at_ns=bid.at_ns,
            )
            reserved = self._no_bid_for(bid.task_id, "live_bid_reserved", bid.at_ns)
            self._own_bids[bid.task_id] = reserved
            self._received[bid.task_id][self.robot_id] = reserved
            return reserved
        self._live_bid_task = bid.task_id
        self._log(
            AllocationEventKind.BID_SENT,
            f"bid {bid.total_cost:.6f} on {bid.task_id}",
            task_id=bid.task_id,
            at_ns=bid.at_ns,
        )
        return bid

    def consider_best(self, bids: Sequence[TaskBid]) -> TaskBid | None:
        """Pick the best feasible offer by ``(total_cost, tie_break, task_id)``."""
        feasible = [bid for bid in bids if bid.feasible]
        if not feasible:
            return None
        return self.consider(min(feasible, key=bid_rank))

    def bid(self, now_ns: int) -> list[object]:
        """``TaskAllocator`` entry point: the messages this robot emits now.

        One bid plus an explicit no-bid record for every released task it did not
        bid on. Silence is never acceptable: a peer must be able to tell "I
        declined" from "my message was lost".
        """
        if self._round is None:
            self._log(AllocationEventKind.NO_BID_SENT, "no allocation round is open", at_ns=now_ns)
            return []
        digest = self._round.snapshot_digest
        out: list[object] = []
        if self._live_bid_task is not None:
            out.append(self._emit(self._own_bids[self._live_bid_task], digest))
            for task_id in self._round.released_task_ids:
                if task_id == self._live_bid_task:
                    continue
                record = self._own_bids.get(task_id)
                if record is None or record.feasible:
                    # A released task this robot is not bidding on is announced as
                    # an explicit no-bid, never left to silence.
                    record = self._no_bid_for(task_id, "live_bid_reserved", now_ns)
                    self._own_bids[task_id] = record
                    self._received.setdefault(task_id, {})[self.robot_id] = record
                out.append(self._emit(record, digest))
            return out
        for task_id in self._round.released_task_ids:
            record = self._own_bids.get(task_id)
            if record is None:
                record = self._no_bid_for(task_id, "not_bid_no_feasible_option", now_ns)
                self._own_bids[task_id] = record
                self._received.setdefault(task_id, {})[self.robot_id] = record
            out.append(self._emit(record, digest))
        return out

    def _emit(self, record: TaskBid, digest: str) -> AllocationMessage:
        self._seq += 1
        return AllocationMessage.of_bid(record, self.robot_session, self._seq, digest)

    def _no_bid_for(self, task_id: str, reason: str, at_ns: int) -> TaskBid:
        assert self._round is not None
        return TaskBid(
            run_id=self.run_id,
            epoch=self.epoch,
            task_id=task_id,
            robot_id=self.robot_id,
            robot_session=self.robot_session,
            round_id=self._round.round_id,
            total_cost=0.0,
            components=(),
            feasible=False,
            infeasible_reason=reason,
            at_ns=at_ns,
            tie_break=tie_break_of(self._round.round_id, task_id, self.robot_id),
        )

    # ------------------------------------------------------------------
    # receiving
    # ------------------------------------------------------------------

    def handle(self, message: PeerMessage | AllocationMessage) -> None:
        """Accept one peer record. Foreign ``PeerMessage`` kinds are recorded."""
        if isinstance(message, AllocationMessage):
            self._handle_allocation(message)
            return
        detail = "domain PeerMessage body union carries no auction body yet"
        self.rejected_messages.append((message.envelope.kind, detail))
        self._log(
            AllocationEventKind.MESSAGE_UNSUPPORTED,
            f"{message.envelope.kind!r}: {detail}",
            robot_id=message.envelope.sender,
            at_ns=message.envelope.sent_at_ns,
        )

    def _handle_allocation(self, message: AllocationMessage) -> None:
        env = message.envelope
        body = message.body
        last = self._last_seq.get(env.sender, -1)
        if env.seq <= last:
            self._log(
                AllocationEventKind.BID_DISCARDED_REPLAY,
                f"seq {env.seq} <= last {last}",
                task_id=message.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        if body.run_id != self.run_id or body.epoch != self.epoch:
            self._log(
                AllocationEventKind.BID_DISCARDED_EPOCH,
                f"run/epoch mismatch {body.run_id}/{body.epoch}",
                task_id=message.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        known = self._sessions.get(env.sender)
        if known is not None and known != env.sender_session:
            # A rebooted robot is a different incarnation. Accepting its bid would let
            # two sessions of one robot both hold capacity in the same round.
            self._log(
                AllocationEventKind.BID_DISCARDED_EPOCH,
                f"session {env.sender_session} superseded by {known}",
                task_id=message.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        self._sessions[env.sender] = env.sender_session
        if self._round is None or env.round_id != self._round.round_id:
            self._log(
                AllocationEventKind.BID_DISCARDED_ROUND,
                f"round {env.round_id!r} is not the open round",
                task_id=message.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        if env.snapshot_digest != self._round.snapshot_digest:
            self._log(
                AllocationEventKind.BID_DISCARDED_SNAPSHOT,
                f"snapshot {env.snapshot_digest[:12]} != {self._round.snapshot_digest[:12]}",
                task_id=message.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        self._last_seq[env.sender] = env.seq
        if isinstance(body, TaskBid):
            self._received.setdefault(body.task_id, {})[env.sender] = body
            self._log(
                AllocationEventKind.BID_RECEIVED if body.feasible else AllocationEventKind.NO_BID_RECEIVED,
                f"total {body.total_cost:.6f}" if body.feasible else body.infeasible_reason,
                task_id=body.task_id,
                robot_id=env.sender,
                at_ns=env.sent_at_ns,
            )
            return
        self._handle_award(body, env.sender, env.sent_at_ns)

    def _handle_award(self, award: TaskAward, sender: str, at_ns: int) -> None:
        # One robot may win at most one task per round, whoever announced it.
        claim_key = (award.winner, award.round_id)
        previous_task = self._peer_winners.get(claim_key)
        if previous_task is not None and previous_task != award.task_id:
            note = (
                f"{award.winner} was awarded {previous_task} and also won "
                f"{award.task_id} in round {award.round_id}"
            )
            self._disagreements[award.task_id] = note
            self._log(
                AllocationEventKind.PEER_CAPACITY_VIOLATION,
                note,
                task_id=award.task_id,
                robot_id=sender,
                at_ns=at_ns,
            )
        self._peer_winners[claim_key] = award.task_id
        if award.task_id not in self._received:
            return
        local = self.compute_award(award.task_id, now_ns=at_ns)
        note = ""
        if local.bid_set_digest != award.bid_set_digest:
            note = f"bid_set_digest {local.bid_set_digest[:12]} != {award.bid_set_digest[:12]}"
        elif local.award is not None and local.winner != award.winner:
            note = f"winner {local.winner} != {award.winner}"
        if note:
            self._disagreements[award.task_id] = note
            self._log(
                AllocationEventKind.CONSENSUS_INCONSISTENT,
                note,
                task_id=award.task_id,
                robot_id=sender,
                at_ns=at_ns,
            )

    # ------------------------------------------------------------------
    # local award computation
    # ------------------------------------------------------------------

    def bids_for(self, task_id: str) -> tuple[TaskBid, ...]:
        """Every bid held for *task_id*, in ascending sender order."""
        table = self._received.get(task_id, {})
        return tuple(table[key] for key in sorted(table))

    def compute_award(self, task_id: str, *, now_ns: int = 0) -> AwardOutcome:
        """Recompute the award locally. This is the only award computation."""
        outcome = compute_award(
            task_id,
            self.bids_for(task_id),
            run_id=self.run_id,
            epoch=self.epoch,
            round_id=self._round.round_id if self._round is not None else "",
            round_index=self._round.index if self._round is not None else 0,
            now_ns=now_ns,
            announced_by=self.robot_id,
        )
        self._log(
            AllocationEventKind.AWARD_COMPUTED,
            f"digest {outcome.bid_set_digest[:12]} winner {outcome.winner or 'none'}",
            task_id=task_id,
            at_ns=now_ns,
        )
        if outcome.explicit_no_bid:
            self._log(
                AllocationEventKind.EXPLICIT_NO_BID,
                "no feasible bid in this round; recorded explicitly",
                task_id=task_id,
                at_ns=now_ns,
            )
        return outcome

    def announce(self, task_id: str, *, now_ns: int = 0) -> AllocationMessage:
        """Emit this robot's own computed outcome for *task_id*."""
        if self._round is None:
            raise RoundSerialisationError("no allocation round is open")
        outcome = self.compute_award(task_id, now_ns=now_ns)
        self._seq += 1
        if outcome.award is not None:
            return AllocationMessage.of_award(
                outcome.award, self.robot_session, self._seq, self._round.snapshot_digest
            )
        self._log(
            AllocationEventKind.EXPLICIT_NO_BID,
            f"announcing explicit no-bid for {task_id}",
            task_id=task_id,
            at_ns=now_ns,
        )
        return AllocationMessage.of_bid(
            self._no_bid_for(task_id, "no_feasible_bid_in_round", now_ns),
            self.robot_session,
            self._seq,
            self._round.snapshot_digest,
        )

    def commit(self, outcome: AwardOutcome, *, now_ns: int = 0) -> TaskOwnership | None:
        """Record ownership for this robot, enforcing one award per round.

        Returns the resulting :class:`TaskOwnership`, or ``None`` when the award was
        not this robot's, or when committing it would break the one-award-per-round
        rule.
        """
        award = outcome.award
        if award is None or award.winner != self.robot_id:
            return None
        if self._round is None:
            raise RoundSerialisationError("no allocation round is open")
        held = [a for a in self._round_awards if a.task_id != award.task_id]
        if held:
            self._log(
                AllocationEventKind.CAPACITY_REFUSED,
                f"already awarded {held[0].task_id} in this round",
                task_id=award.task_id,
                at_ns=now_ns,
            )
            return None
        previous = self._ownership.get(award.task_id)
        if previous is not None and previous.owner not in (None, self.robot_id):
            self._log(
                AllocationEventKind.STALE_OWNERSHIP_REFUSED,
                f"task owned by {previous.owner} at version {previous.ownership_version}",
                task_id=award.task_id,
                at_ns=now_ns,
            )
            return None
        version = 1 if previous is None else previous.ownership_version + 1
        ownership = TaskOwnership(
            task_id=award.task_id,
            owner=self.robot_id,
            owner_session=self.robot_session,
            ownership_version=version,
            allocation_round=self._round.index,
            state=TaskOwnershipState.OWNED,
            awarded_at_ns=now_ns,
            bid_set_digest=award.bid_set_digest,
            evidence=f"local recomputation over {len(self.bids_for(award.task_id))} held bids",
        )
        self._ownership[award.task_id] = ownership
        self._task_state[award.task_id] = TaskState.CLAIMED
        self._round_awards.append(award)
        self._live_bid_task = None
        return ownership

    # ------------------------------------------------------------------
    # consensus
    # ------------------------------------------------------------------

    def heard_from(self, task_id: str) -> frozenset[str]:
        return frozenset(self._received.get(task_id, {}))

    def missing_peers(self, task_id: str) -> tuple[str, ...]:
        heard = self.heard_from(task_id)
        return tuple(m for m in self.membership.members if m not in heard)

    def consensus(self, task_id: str, *, now_ns: int = 0) -> PartitionConsensusState:
        """Agreement state for one task.

        ``paused`` is reported before ``inconsistent`` on purpose: if a member has
        not been heard from, the honest diagnosis is that this robot's view is
        incomplete, not that anyone has computed something different.
        """
        missing = self.missing_peers(task_id)
        if missing:
            return self._settle(
                task_id,
                PartitionConsensusState.PAUSED,
                AllocationEventKind.CONSENSUS_PAUSED,
                f"no report from {', '.join(missing)}",
                now_ns,
            )
        if task_id in self._disagreements:
            return self._settle(
                task_id,
                PartitionConsensusState.INCONSISTENT,
                AllocationEventKind.CONSENSUS_INCONSISTENT,
                self._disagreements[task_id],
                now_ns,
            )
        return self._settle(
            task_id,
            PartitionConsensusState.AGREED,
            AllocationEventKind.CONSENSUS_AGREED,
            f"all {self.membership.voter_count} members reported",
            now_ns,
        )

    def _settle(
        self,
        task_id: str,
        state: PartitionConsensusState,
        kind: AllocationEventKind,
        detail: str,
        now_ns: int,
    ) -> PartitionConsensusState:
        """Log only on a state *change*, so repeated queries do not flood events."""
        if self._consensus_seen.get(task_id) is not state:
            self._consensus_seen[task_id] = state
            self._log(kind, detail, task_id=task_id, at_ns=now_ns)
        return state

    def may_start(self, task_id: str, *, now_ns: int = 0) -> bool:
        """Only an agreed, locally recomputed award permits starting work."""
        if self.consensus(task_id, now_ns=now_ns) is not PartitionConsensusState.AGREED:
            return False
        ownership = self._ownership.get(task_id)
        if ownership is None or ownership.owner != self.robot_id:
            return False
        if ownership.state is not TaskOwnershipState.OWNED:
            return False
        return self.compute_award(task_id, now_ns=now_ns).winner == self.robot_id

    def owned_task(self) -> str | None:
        """The task this robot may currently start, or ``None``."""
        for task_id in sorted(self._ownership):
            if self.may_start(task_id):
                return task_id
        return None

    def tick(self, now_ns: int) -> None:
        """No timer releases anything here. Deliberately.

        A lost heartbeat never releases capacity, never clears a bid and never
        empties an aisle (AGENTS.md rule 4). A round closes when its participants
        agree to close it, which is why :meth:`close_round` refuses while a bid is
        live.
        """
        return

    # ------------------------------------------------------------------
    # ownership transitions
    # ------------------------------------------------------------------

    def ownership(self, task_id: str) -> TaskOwnership | None:
        return self._ownership.get(task_id)

    def task_state(self, task_id: str) -> TaskState:
        return self._task_state.get(task_id, TaskState.AVAILABLE)

    def apply_transition(self, transition: TaskTransition, *, now_ns: int = 0) -> TransitionOutcome:
        """Apply one task transition, refusing stale versions and illegal states."""
        ownership = self._ownership.get(transition.task_id)
        current = self.task_state(transition.task_id)
        if ownership is not None and transition.ownership_version < ownership.ownership_version:
            return self._refuse(
                transition,
                AllocationEventKind.STALE_OWNERSHIP_REFUSED,
                f"stale_ownership_version:{transition.ownership_version}<{ownership.ownership_version}",
                current,
                ownership.ownership_version,
                now_ns,
            )
        if (
            ownership is not None
            and ownership.state is TaskOwnershipState.OWNED
            and ownership.owner != transition.robot_id
        ):
            return self._refuse(
                transition,
                AllocationEventKind.TRANSITION_REFUSED,
                f"not_owner:{ownership.owner}",
                current,
                ownership.ownership_version,
                now_ns,
            )
        if not is_legal_task_transition(current, transition.to_state):
            return self._refuse(
                transition,
                AllocationEventKind.TRANSITION_REFUSED,
                f"illegal_transition:{current.value}->{transition.to_state.value}",
                current,
                ownership.ownership_version if ownership is not None else 0,
                now_ns,
            )
        self._task_state[transition.task_id] = transition.to_state
        self._log(
            AllocationEventKind.TRANSITION_APPLIED,
            f"{current.value} -> {transition.to_state.value}",
            task_id=transition.task_id,
            robot_id=transition.robot_id,
            at_ns=now_ns,
        )
        return TransitionOutcome(
            True,
            "applied",
            transition.task_id,
            transition.to_state,
            current,
            transition.ownership_version,
        )

    def _refuse(
        self,
        transition: TaskTransition,
        kind: AllocationEventKind,
        reason: str,
        current: TaskState,
        version: int,
        now_ns: int,
    ) -> TransitionOutcome:
        self._log(
            kind,
            reason,
            task_id=transition.task_id,
            robot_id=transition.robot_id,
            at_ns=now_ns,
        )
        return TransitionOutcome(False, reason, transition.task_id, transition.to_state, current, version)

    # ------------------------------------------------------------------
    # logging
    # ------------------------------------------------------------------

    def _log(
        self,
        kind: AllocationEventKind,
        detail: str,
        *,
        task_id: str = "",
        robot_id: str = "",
        at_ns: int = 0,
    ) -> None:
        self.events.append(
            AllocationEvent(
                kind=kind,
                detail=detail,
                task_id=task_id,
                robot_id=robot_id,
                at_ns=at_ns,
            )
        )

    def event_kinds(self) -> tuple[AllocationEventKind, ...]:
        return tuple(event.kind for event in self.events)

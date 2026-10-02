"""The requester half: canonical sequential acquisition, one voter at a time.

The walk is deliberately dumb and deliberately ordered:

1. solicit voter ``order()[0]`` - which for one requester is itself - and wait
   for an explicit grant or an explicit refusal;
2. on a grant, advance to the next index; on a refusal, stop;
3. entry is permitted only once every voter has granted **and** the advertised
   ``required_set_digest`` equals the one this robot computes locally.

Never pre-reserve your own voter. If a requester took its own grant first it
would hold authority for a *later* index than every peer, and two robots could
each hold the other's next requirement - exactly the cyclic wait the project
brief warns about.

Cancellation is durable here *first*: ``durably_non_executable`` is written to
the journal before a single ``ZoneCancelBody`` is emitted, so a grant that
arrives afterwards is recorded as ``LATE_GRANT_IGNORED`` and answered with a
cancel; it is never converted into authority.

See ``docs/protocol/ZONE_PROTOCOL.md`` sections 3, 6 and 9.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from niharamesh.coordination.recovery import RECORD_CANCEL, RECORD_OCCUPANCY, RECORD_RELEASE
from niharamesh.coordination.voter import Refusal, ZoneVoter, required_set_digest
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    RejectionReason,
    VoterSlotState,
    ZoneCancelAckBody,
    ZoneCancelBody,
    ZoneGrantBody,
    ZoneOccupyBody,
    ZoneReleaseBody,
    ZoneRequestBody,
)
from niharamesh.domain.map import ZoneMovement
from niharamesh.ports import AuthorityJournal

__all__ = [
    "LATE_GRANT_IGNORED",
    "TERMINAL_PHASES",
    "Acquisition",
    "AdmissionContext",
    "BlockingClass",
    "BlockingReport",
    "ProtocolEvent",
    "SafetyCheck",
    "VoterSlot",
    "ZoneRequester",
]

#: Bounded backoff: ``solicit_timeout`` doubled per refusal, capped, then
#: multiplied by a deterministic per-transaction offset so two robots refused in
#: the same instant do not re-race in lockstep forever (ADR 0003 section 7).
MAX_BACKOFF_STEPS: Final[int] = 3
#: Refusals after which the blocking report stops calling it "healthy contention".
RETRY_REFUSALS: Final[int] = 3
LATE_GRANT_IGNORED: Final[str] = "LATE_GRANT_IGNORED"

TERMINAL_PHASES: Final[frozenset[AcquisitionPhase]] = frozenset(
    {
        AcquisitionPhase.REJECTED,
        AcquisitionPhase.CANCELLED,
        AcquisitionPhase.RELEASED,
        AcquisitionPhase.FAILED,
    }
)

#: Phases in which this owner **retains** authority over its zone. A grant arriving
#: in one of these is a duplicate of an answer already given, never a new authority
#: and never a reason to withdraw. Kept here rather than inlined because
#: :meth:`ZoneRequester.on_grant` branches on it and ``agent.runtime`` keeps a
#: matching set for its own evidence; two definitions of "has authority" that can
#: drift is the bug this list exists to prevent.
AUTHORITY_PHASES_OWNER: Final[frozenset[AcquisitionPhase]] = frozenset(
    {
        AcquisitionPhase.GRANTED,
        AcquisitionPhase.OCCUPYING,
        AcquisitionPhase.OCCUPIED,
        AcquisitionPhase.RELEASING,
    }
)


class BlockingClass(StrEnum):
    """Why entry or progress is withheld. Every class names its recovery."""

    NONE = "none"
    IDLE = "idle"
    ACQUIRING = "acquiring"
    PARTIAL_ACQUISITION = "partial_acquisition"
    HEALTHY_CONTENTION = "healthy_contention"
    GRANT_HELD = "grant_held"
    PARTITION_STOP = "partition_stop"
    ZONE_FENCED = "zone_fenced"
    PHYSICAL_OBSTRUCTION = "physical_obstruction"
    DEADLOCK_SUSPECTED = "deadlock_suspected"
    LIVELOCK_SUSPECTED = "livelock_suspected"
    STARVATION_SUSPECTED = "starvation_suspected"
    SAFETY_GATE = "safety_gate"
    PEER_STATE_STALE = "peer_state_stale"
    DIGEST_MISMATCH = "digest_mismatch"
    JOURNAL_UNAVAILABLE = "journal_unavailable"
    RELEASING = "releasing"


@dataclass(frozen=True, slots=True)
class BlockingReport:
    """Machine-readable blocking reason plus the blocking parties."""

    kind: BlockingClass
    detail: str
    blocking_request: str | None = None
    blocking_peer: str | None = None
    blocking_resource: str | None = None

    def render(self) -> str:
        parts = [f"blocked={self.kind.value}", f"detail={self.detail}"]
        if self.blocking_request is not None:
            parts.append(f"blocking_request={self.blocking_request}")
        if self.blocking_peer is not None:
            parts.append(f"blocking_peer={self.blocking_peer}")
        if self.blocking_resource is not None:
            parts.append(f"blocking_resource={self.blocking_resource}")
        return "; ".join(parts)


@dataclass(frozen=True, slots=True)
class ProtocolEvent:
    """Append-only, operator-visible. No state lives here."""

    at_ns: int
    kind: str
    zone_id: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class AdmissionContext:
    """Everything the local safety gate is allowed to see about an entry."""

    zone_id: str
    movement: ZoneMovement
    entry_pose: tuple[float, float, float]
    exit_pose: tuple[float, float, float]
    required_voters: tuple[str, ...]
    held_voters: tuple[str, ...]
    required_set_digest: str
    now_ns: int


SafetyCheck = Callable[[AdmissionContext], tuple[bool, str]]


@dataclass(slots=True)
class VoterSlot:
    voter: str
    index: int
    state: VoterSlotState = VoterSlotState.PENDING
    grant_id: str = ""
    persistence_record_id: str = ""
    required_set_digest: str = ""
    attempts: int = 0
    next_attempt_ns: int = 0
    last_refusal: Refusal | None = None
    is_self: bool = False


@dataclass(frozen=True, slots=True)
class ProtocolAction:
    """One thing the transport layer should do. No sockets, no asyncio.

    The requester decides *what* and *to whom*; ``ZoneProtocol`` turns it into a
    framed :class:`~niharamesh.domain.coordination.PeerMessage`. Keeping the
    split means the state machine is testable with a plain list.
    """

    kind: str
    target: str
    request: ZoneRequestBody | None = None
    cancel: ZoneCancelBody | None = None
    occupy: ZoneOccupyBody | None = None
    release: ZoneReleaseBody | None = None

    @property
    def is_local(self) -> bool:
        return False  # overwritten by ZoneProtocol for the self-voter case


@dataclass(slots=True)
class Acquisition:
    """One zone transaction. Immutable identity, mutable lifecycle."""

    zone_id: str
    request: ZoneRequestBody
    movement: ZoneMovement
    slots: list[VoterSlot]
    phase: AcquisitionPhase = AcquisitionPhase.INITIATED
    cursor: int = 0
    cancel_seq: int = 0
    cancel_sent: set[str] = field(default_factory=set)
    #: When the current reconciliation pass was emitted, so a lost cancellation is
    #: re-sent after ``cancel_timeout_ns`` instead of ending the reconciliation.
    cancel_sent_ns: int = 0
    cancel_acked: set[str] = field(default_factory=set)
    #: Every voter that ever granted this transaction. Cancellation reconciles
    #: with all of them, so no peer keeps a record of a promise the owner has
    #: already made non-executable.
    ever_granted: set[str] = field(default_factory=set)
    #: Voters that granted *after* the owner durably cancelled. Their record must
    #: still converge, so they are cancelled too - but they never become
    #: authority for this robot.
    late_granted: set[str] = field(default_factory=set)
    durably_non_executable: bool = False
    cancel_reason: str = ""
    reject_reason: RejectionReason | None = None
    reject_detail: str = ""
    occupancy_seq: int = 0
    occupy_emitted: bool = False
    release_seq: int = 0
    release_emitted: bool = False
    release_sent_ns: int = 0
    refusals_seen: int = 0
    entry_commit_record: str = ""
    granted_at_ns: int = 0
    last_progress_ns: int = 0

    def held(self) -> tuple[str, ...]:
        return tuple(s.voter for s in self.slots if s.state is VoterSlotState.GRANTED)

    def pending_slot(self) -> VoterSlot | None:
        if self.cursor >= len(self.slots):
            return None
        return self.slots[self.cursor]

    def all_slots_granted(self) -> bool:
        return bool(self.slots) and all(s.state is VoterSlotState.GRANTED for s in self.slots)

    def digests(self) -> tuple[str, ...]:
        return tuple(s.required_set_digest for s in self.slots if s.state is VoterSlotState.GRANTED)

    def last_refusal(self) -> Refusal | None:
        for slot in reversed(self.slots):
            if slot.last_refusal is not None:
                return slot.last_refusal
        return None


def _stable_offset(txn: str) -> int:
    """Deterministic 0..255 spread derived from a transaction id."""
    return int(txn[:2], 16)


def blocking_from_refusal(refusal: Refusal) -> BlockingReport:
    kind = {
        RejectionReason.ZONE_PROMISED: BlockingClass.HEALTHY_CONTENTION,
        RejectionReason.GRANT_HELD: BlockingClass.GRANT_HELD,
        RejectionReason.ZONE_FENCED: BlockingClass.ZONE_FENCED,
        RejectionReason.NOT_READY: BlockingClass.PARTITION_STOP,
        RejectionReason.REQUESTER_NOT_ADMITTED: BlockingClass.PARTITION_STOP,
        RejectionReason.PROTOCOL_MISMATCH: BlockingClass.PARTITION_STOP,
        RejectionReason.SCHEMA_MISMATCH: BlockingClass.PARTITION_STOP,
        RejectionReason.EPOCH_MISMATCH: BlockingClass.PARTITION_STOP,
        RejectionReason.MAP_MISMATCH: BlockingClass.PARTITION_STOP,
        RejectionReason.REQUEST_VERSION_REPLAY: BlockingClass.PARTITION_STOP,
    }.get(refusal.reason, BlockingClass.PARTITION_STOP)
    return BlockingReport(
        kind=kind,
        detail=f"{refusal.reason.value}: {refusal.detail}",
        blocking_request=refusal.blocking_grant_id,
        blocking_peer=refusal.blocking_requester or refusal.blocking_voter,
        blocking_resource=refusal.blocking_zone or refusal.zone_id,
    )


class ZoneRequester:
    """One robot's outbound acquisition state machine. Pure logic, no I/O."""

    def __init__(
        self,
        *,
        robot_id: str,
        session_id: str,
        journal: AuthorityJournal,
        voter: ZoneVoter,
        solicit_timeout_ns: int,
        cancel_timeout_ns: int,
        release_timeout_ns: int,
        safety_check: SafetyCheck,
    ) -> None:
        self.robot_id = robot_id
        self.session_id = session_id
        self.journal = journal
        self.voter = voter
        self.solicit_timeout_ns = max(1, solicit_timeout_ns)
        self.cancel_timeout_ns = max(1, cancel_timeout_ns)
        self.release_timeout_ns = max(1, release_timeout_ns)
        self._safety_check = safety_check
        self._active: Acquisition | None = None
        self._versions: dict[str, int] = {}
        self._history: list[Acquisition] = []
        self._events: list[ProtocolEvent] = []
        self._last_rejection: Refusal | None = None
        self._retry_at_ns = 0
        self._retries = 0
        self._obstructions: set[str] = set()

    # ------------------------------------------------------------------ views

    @property
    def active(self) -> Acquisition | None:
        return self._active

    @property
    def events(self) -> tuple[ProtocolEvent, ...]:
        return tuple(self._events)

    @property
    def history(self) -> tuple[Acquisition, ...]:
        return tuple(self._history)

    @property
    def last_rejection(self) -> Refusal | None:
        """The specific reason the previous attempt ended, kept after it closed."""
        return self._last_rejection

    @property
    def retry_at_ns(self) -> int:
        return self._retry_at_ns

    @property
    def held_grants(self) -> int:
        """Global single-outstanding-grant count. Must never exceed one set."""
        return 0 if self._active is None else len(self._active.held())

    def phase(self) -> AcquisitionPhase:
        return AcquisitionPhase.INITIATED if self._active is None else self._active.phase

    def next_request_version(self, zone_id: str) -> int:
        return self._versions.get(zone_id, 0) + 1

    def log(self, at_ns: int, kind: str, zone_id: str, detail: str = "") -> None:
        self._events.append(ProtocolEvent(at_ns=at_ns, kind=kind, zone_id=zone_id, detail=detail))

    # ------------------------------------------------------------- initiation

    def begin(self, body: ZoneRequestBody, movement: ZoneMovement, now_ns: int) -> Acquisition:
        """Start a fresh transaction. Refuses a second concurrent one.

        ``AGENTS.md`` invariant 6, requester side: a robot that already holds an
        outstanding grant may not start another walk. Its own local voter also
        refuses the resulting solicitation with ``GRANT_HELD``.
        """
        if self._active is not None and self._active.phase not in TERMINAL_PHASES:
            raise RuntimeError(
                f"robot {self.robot_id} already holds an outstanding transaction for "
                f"{self._active.zone_id!r} ({self._active.phase.value}); invariant 6 permits "
                "one outstanding grant globally"
            )
        expected = self.next_request_version(body.zone_id)
        if body.request_version != expected:
            raise ValueError(
                f"request_version {body.request_version} is not the next version "
                f"{expected} for zone {body.zone_id!r}"
            )
        self._versions[body.zone_id] = body.request_version
        slots = [
            VoterSlot(voter=voter, index=index, is_self=voter == self.robot_id)
            for index, voter in enumerate(self.voter.required_voters)
        ]
        acq = Acquisition(
            zone_id=body.zone_id,
            request=body,
            movement=movement,
            slots=slots,
            last_progress_ns=now_ns,
        )
        self._active = acq
        self._history.append(acq)
        self._last_rejection = None
        self._retry_at_ns = 0
        self.log(now_ns, "REQUEST_INITIATED", body.zone_id, f"v={body.request_version}")
        return acq

    def backoff_ns(self, acq: Acquisition) -> int:
        """Bounded exponential backoff with a deterministic per-transaction offset.

        The offset comes from the transaction id, so two robots refused in the
        same instant do not re-race in lockstep forever. It never reorders
        authority that was already issued - it only spaces out *retries*.
        """
        step = min(acq.refusals_seen, MAX_BACKOFF_STEPS)
        offset = 1 + _stable_offset(acq.request.txn) % RETRY_REFUSALS
        return self.solicit_timeout_ns * (1 << step) * offset

    def retry_due(self, now_ns: int) -> bool:
        """True when a refused attempt may be retried as a *new* transaction.

        The old transaction object is kept (it is the audit trail, and it is what
        turns a late grant into ``LATE_GRANT_IGNORED``); a retry is always a new
        ``request_version``, never a mutation of the outstanding order.
        """
        acq = self._active
        if acq is None or acq.phase not in (AcquisitionPhase.REJECTED, AcquisitionPhase.CANCELLED):
            return False
        if self._last_rejection is None:
            # A voluntary cancellation is not a failure; retrying is the caller's
            # decision, so nothing re-arms on its own.
            return False
        return now_ns >= self._retry_at_ns

    # ----------------------------------------------------------------- timers

    def tick(self, now_ns: int) -> list[ProtocolAction]:
        """Advance timers and report exactly which messages are due.

        Retries re-send the *same bytes*. Nothing here ever revokes authority: a
        ``GRANTED`` transaction has no timeout that can un-grant it, and an
        occupied zone has no timeout that can free it.
        """
        acq = self._active
        if acq is None:
            return []
        actions: list[ProtocolAction] = []
        # Reconciliation with peers outlives the phase change: a cancellation is
        # only finished when every peer that ever granted us has acknowledged.
        #
        # A **rejected** attempt needs the same treatment, and its absence here was
        # a livelock rather than a leak. The protocol deliberately retries with a
        # fresh ``request_version`` (see :meth:`retry_due`), so a voter still holding
        # a promise from the failed attempt refuses the retry with ``ZONE_PROMISED``
        # -- for the *same zone, by the same robot*. The promise can never match the
        # new version, so the retry can never succeed, and the aisle stays held
        # forever by a robot that has already given up. Withdrawing the partial
        # promises of a failed attempt is safe precisely because the attempt never
        # reached ``GRANTED``, so nobody could have entered on it.
        if acq.phase is AcquisitionPhase.REJECTED or (
            acq.durably_non_executable and acq.phase is not AcquisitionPhase.RELEASING
        ):
            # Reconciliation is **retransmitted**, not sent once. ``cancel_timeout_ns``
            # is plumbed all the way from ``ProtocolTiming.cancel_timeout_s`` for
            # exactly this and was previously never read, so a single lost
            # ``zone_cancel`` ended the reconciliation permanently: ``CANCELLING`` is
            # not a terminal phase, so ``begin()`` refuses and ``retry_due`` returns
            # false, and the robot kept a stale promise at that peer with no way to
            # clear it or to ask again. Reproduced: after 60 further rounds,
            # ``phase=cancelling, held=('r1',), acked=['r2']`` with ``r1`` still
            # ``PROMISED``.
            #
            # This mirrors the release retransmission below: the same
            # ``release_timeout_ns`` reasoning, the same reason. A reconciliation
            # that assumes its own messages arrive is not a reconciliation.
            for voter in self.cancel_targets(acq):
                if voter in acq.cancel_sent and now_ns - acq.cancel_sent_ns < self.cancel_timeout_ns:
                    # Sent on the current pass and the retransmit window has not
                    # elapsed. Waiting here is a rate limit on *duplicate* frames,
                    # never a completion criterion: a voter that has not
                    # acknowledged is retried when the window opens, however many
                    # times that takes.
                    continue
                acq.cancel_sent.add(voter)
                acq.cancel_sent_ns = now_ns
                actions.append(ProtocolAction("cancel", voter, cancel=self.cancel_body(acq)))
        if acq.phase in (AcquisitionPhase.CANCELLED, AcquisitionPhase.REJECTED):
            return actions
        if acq.phase is AcquisitionPhase.INITIATED:
            acq.phase = AcquisitionPhase.ACQUIRING
            acq.last_progress_ns = now_ns
        if acq.phase is AcquisitionPhase.ACQUIRING:
            slot = acq.pending_slot()
            if (
                slot is not None
                and slot.state is VoterSlotState.PENDING
                and (slot.attempts == 0 or now_ns >= slot.next_attempt_ns)
            ):
                slot.attempts += 1
                slot.next_attempt_ns = now_ns + self.solicit_timeout_ns
                acq.last_progress_ns = now_ns
                self.log(now_ns, "SOLICIT", acq.zone_id, f"voter={slot.voter} n={slot.attempts}")
                actions.append(ProtocolAction("solicit", slot.voter, request=acq.request))
            return actions
        if acq.phase is AcquisitionPhase.OCCUPIED and not acq.occupy_emitted:
            acq.occupy_emitted = True
            for voter in self.voter.required_voters:
                actions.append(ProtocolAction("occupy", voter, occupy=self.occupy_body(acq)))
            return actions
        if acq.phase is AcquisitionPhase.RELEASING and (
            not acq.release_emitted or now_ns - acq.release_sent_ns >= self.release_timeout_ns
        ):
            acq.release_emitted = True
            acq.release_sent_ns = now_ns
            self.log(now_ns, "RELEASE", acq.zone_id, f"seq={acq.release_seq}")
            for voter in self.voter.required_voters:
                actions.append(ProtocolAction("release", voter, release=self.release_body(acq)))
        return actions

    # ------------------------------------------------------ inbound handling

    def on_grant(self, voter: str, body: ZoneGrantBody, now_ns: int) -> None:
        """Record a grant for the current index and advance the walk."""
        acq = self._active
        if acq is None:
            return
        if acq.phase is AcquisitionPhase.ACQUIRING and acq.durably_non_executable:
            self._answer_late_grant(acq, voter, now_ns)
            return
        if acq.phase in AUTHORITY_PHASES_OWNER:
            # A grant for a transaction that already holds authority is a
            # **duplicate**, not a late grant. It is evidence of nothing: a
            # duplicated frame, a retransmission, a peer answering a request it had
            # already answered. Routing it into the late-grant path revoked live
            # authority -- see ``_answer_late_grant`` -- which contradicts
            # :meth:`cancel`'s own rule that entry cannot be undone by a
            # cancellation. Reproduced: a single duplicated grant frame moved an
            # ``OCCUPIED`` transaction to ``CANCELLING`` with
            # ``durably_non_executable = True``.
            self.log(
                now_ns,
                LATE_GRANT_IGNORED,
                acq.zone_id,
                f"voter={voter} duplicate grant for an already-authorised transaction",
            )
            return
        if acq.phase is not AcquisitionPhase.ACQUIRING:
            # Not authorised and not acquiring: a genuinely late grant for a
            # transaction that was withdrawn. The peer still holds a promise, so
            # its record must be reconciled -- but only by a cancellation this
            # robot has actually made durable.
            self._answer_late_grant(acq, voter, now_ns)
            return
        slot = acq.pending_slot()
        if slot is None or slot.voter != voter:
            self.log(now_ns, LATE_GRANT_IGNORED, acq.zone_id, f"unexpected voter {voter}")
            return
        if body.grant_id != acq.request.grant_id:
            self.log(now_ns, LATE_GRANT_IGNORED, acq.zone_id, "grant_id mismatch")
            return
        slot.state = VoterSlotState.GRANTED
        slot.grant_id = body.grant_id
        slot.persistence_record_id = body.persistence_record_id
        slot.required_set_digest = body.required_set_digest
        acq.ever_granted.add(voter)
        acq.last_progress_ns = now_ns
        acq.cursor += 1
        self.log(now_ns, "GRANT_RECEIVED", acq.zone_id, f"voter={voter}")
        if acq.all_slots_granted():
            self._enter_granted(acq, now_ns)

    def _enter_granted(self, acq: Acquisition, now_ns: int) -> None:
        computed = self.compute_digest(acq)
        advertised = acq.digests()
        if not advertised or any(d != computed for d in advertised):
            self.log(
                now_ns,
                "GRANT_SET_DIGEST_MISMATCH",
                acq.zone_id,
                f"computed={computed[:12]} advertised={advertised}",
            )
            acq.reject_reason = RejectionReason.PROTOCOL_VIOLATION
            acq.reject_detail = "advertised required_set_digest differs from the computed set"
            self.cancel("grant_set_digest_mismatch")
            return
        acq.phase = AcquisitionPhase.GRANTED
        acq.granted_at_ns = now_ns
        self.log(now_ns, "GRANTED", acq.zone_id, f"digest={computed[:12]}")

    def compute_digest(self, acq: Acquisition) -> str:
        return required_set_digest(
            acq.request.run_id,
            acq.request.epoch,
            acq.zone_id,
            acq.request.requester,
            acq.request.requester_session,
            acq.request.request_version,
            self.voter.required_voters,
            self.voter.sessions(),
        )

    def _answer_late_grant(self, acq: Acquisition, voter: str, now_ns: int) -> None:
        """A grant after durable cancellation gets a cancel, never authority.

        The peer's record must still converge, so this voter is added to the
        reconciliation set -- but the grant creates no authority here, and the
        transaction can never become ``GRANTED`` again.

        The cancellation is made durable **first, and the write is checked**, exactly
        as :meth:`cancel` does. Setting an in-memory flag and then emitting a
        withdrawal is the failure this guards: a journal that refuses the write
        leaves ``durably_non_executable = True`` set and every peer's promise
        withdrawn on the strength of a cancellation that exists nowhere on disk
        (invariant 5, AGENTS.md). Reproduced with both failure modes: a port
        returning an empty record id, and the shipped SQLite journal raising.

        Failing closed means **no withdrawal is emitted**, not that authority is
        invented. The peer keeps a promise this robot will reconcile later, which is
        the conservative direction: an over-held aisle stops somebody, whereas a
        prematurely freed one lets two bodies meet.
        """
        if acq.cancel_seq == 0:
            acq.cancel_seq = 1
            record = self._append_cancel(acq, f"late_grant:{voter}", now_ns)
            if not record:
                acq.cancel_seq = 0
                self.log(
                    now_ns,
                    "CANCEL_NOT_DURABLE",
                    acq.zone_id,
                    f"voter={voter}; no withdrawal emitted because the record is not durable",
                )
                return
            acq.durably_non_executable = True
            acq.cancel_reason = f"late_grant:{voter}"
            self.log(
                now_ns,
                "CANCEL_DURABLE",
                acq.zone_id,
                f"seq={acq.cancel_seq} reason=late_grant:{voter}",
            )
        acq.late_granted.add(voter)
        if acq.phase not in AUTHORITY_PHASES_OWNER:
            acq.phase = AcquisitionPhase.CANCELLING
        self.log(
            now_ns,
            LATE_GRANT_IGNORED,
            acq.zone_id,
            f"voter={voter} answered with a cancel so the peer's record converges",
        )

    def _append_cancel(self, acq: Acquisition, reason: str, now_ns: int) -> str:
        """Write one cancellation record. Returns ``""`` when it did not persist.

        Wraps the append rather than trusting it, because the shipped journal
        raises when its underlying storage fails and :meth:`ZoneProtocol.ingest` is
        the single inbound entry point the transport calls: an exception escaping
        here takes down the reader task on a path whose entire purpose is to answer
        a stale frame gracefully.
        """
        try:
            return self.journal.append(
                RECORD_CANCEL,
                {
                    "zone_id": acq.zone_id,
                    "requester": acq.request.requester,
                    "request_version": acq.request.request_version,
                    "grant_id": acq.request.grant_id,
                    "cancel_seq": acq.cancel_seq,
                    "durably_non_executable": True,
                    "reason": reason,
                    "owner": self.robot_id,
                },
            )
        except Exception as exc:
            self.log(now_ns, "CANCEL_NOT_DURABLE", acq.zone_id, f"journal raised: {exc}")
            return ""

    def on_refusal(self, refusal: Refusal, now_ns: int) -> None:
        """Explicit refusal from a voter: stop this attempt, name the reason."""
        acq = self._active
        if acq is None:
            return
        if acq.phase is not AcquisitionPhase.ACQUIRING:
            self.log(now_ns, "REFUSAL_IGNORED", acq.zone_id, refusal.reason.value)
            return
        slot = acq.pending_slot()
        if slot is not None and (slot.voter == refusal.blocking_voter or slot.voter != refusal.zone_id):
            slot.last_refusal = refusal
            slot.state = VoterSlotState.REJECTED
        acq.refusals_seen += 1
        acq.reject_reason = refusal.reason
        acq.reject_detail = refusal.detail
        self.log(now_ns, "REFUSED", acq.zone_id, refusal.describe())
        if acq.held():
            self.cancel(f"refused:{refusal.reason.value}", now_ns=now_ns)
        else:
            self._finish_refused(acq, refusal, now_ns)

    def _finish_refused(self, acq: Acquisition, refusal: Refusal, now_ns: int) -> None:
        acq.phase = AcquisitionPhase.REJECTED
        self._last_rejection = refusal
        self._retries += 1
        self._retry_at_ns = now_ns + self.backoff_ns(acq)
        self.log(
            now_ns,
            "REJECTED",
            acq.zone_id,
            f"reason={refusal.reason.value} retry_at_ns={self._retry_at_ns}",
        )

    def on_cancel_ack(self, body: ZoneCancelAckBody, now_ns: int) -> None:
        acq = self._active
        if acq is None or body.zone_id != acq.zone_id or body.cancel_seq != acq.cancel_seq:
            return
        acq.cancel_acked.add(body.voter)
        for slot in acq.slots:
            if slot.voter == body.voter:
                slot.state = VoterSlotState.CANCELLED
        self._settle_cancellation(acq, now_ns)

    def _settle_cancellation(self, acq: Acquisition, now_ns: int) -> None:
        if acq.phase in (AcquisitionPhase.CANCELLED, AcquisitionPhase.REJECTED):
            return
        if acq.held() or self.cancel_targets(acq):
            return  # still holding, or still reconciling with a peer
        refusal = acq.last_refusal()
        acq.phase = AcquisitionPhase.CANCELLED if refusal is None else AcquisitionPhase.REJECTED
        self.log(now_ns, acq.phase.value.upper(), acq.zone_id, acq.cancel_reason)
        if refusal is not None:
            self._last_rejection = refusal
            self._retries += 1
            self._retry_at_ns = now_ns + self.backoff_ns(acq)

    # --------------------------------------------------------- cancellation

    def cancel(self, reason: str, now_ns: int | None = None) -> bool:
        """Durable non-executable **first**, then peer reconciliation.

        Returns False when cancellation is illegal: once the robot has declared
        physical entry, a pre-entry cancellation is meaningless and the only
        honest way out is exit-then-release.
        """
        acq = self._active
        if acq is None or acq.phase in TERMINAL_PHASES:
            return False
        when = acq.last_progress_ns if now_ns is None else now_ns
        if acq.phase in (
            AcquisitionPhase.OCCUPYING,
            AcquisitionPhase.OCCUPIED,
            AcquisitionPhase.RELEASING,
        ):
            self.log(
                when,
                "CANCEL_REFUSED_POST_ENTRY",
                acq.zone_id,
                "the robot may be inside the zone; exit and release instead",
            )
            return False
        if acq.durably_non_executable:
            return True
        acq.cancel_seq += 1
        acq.cancel_reason = reason
        # Durable FIRST. Nothing is emitted until this append returns a record id.
        record = self._append_cancel(acq, reason, when)
        if not record:
            acq.cancel_seq -= 1
            self.log(when, "CANCEL_NOT_DURABLE", acq.zone_id, reason)
            return False
        acq.durably_non_executable = True
        acq.phase = AcquisitionPhase.CANCELLING
        acq.last_progress_ns = when
        acq.cancel_sent = set()
        acq.cancel_sent_ns = when
        self.log(when, "CANCEL_DURABLE", acq.zone_id, f"seq={acq.cancel_seq} reason={reason}")
        self._settle_cancellation(acq, when)
        return True

    def cancel_targets(self, acq: Acquisition) -> tuple[str, ...]:
        """Peers whose record may still mention this transaction.

        Everyone who ever granted us, plus anyone who granted *late*, **minus the
        ones that have acknowledged**.

        The previous version subtracted ``cancel_sent`` -- peers already *told* --
        which is the wrong set. A cancellation is not complete when it has been
        sent; it is complete when every peer has acknowledged it. Subtracting
        ``cancel_sent`` therefore meant the reconciliation could never revisit a
        peer whose acknowledgement was lost, and this function returned empty while
        the peer still held ``PROMISED``. That is the whole of the
        ``cancel_timeout_ns`` defect: ``cancel_sent`` is a rate-limit bookkeeping
        detail, not a completion criterion, and using it as one ended the
        reconciliation on the first pass.

        Late grants are handled by the same rule, which is what makes a late grant
        converge: ``late_granted`` puts the peer back into ``owed``, and because it
        has not acknowledged, it is targeted again even though it was cancelled in
        the first pass.
        """
        owed = set(acq.ever_granted) | set(acq.late_granted)
        return tuple(v for v in self.voter.required_voters if v in owed and v not in acq.cancel_acked)

    def cancel_body(self, acq: Acquisition) -> ZoneCancelBody:
        return ZoneCancelBody(
            run_id=acq.request.run_id,
            epoch=acq.request.epoch,
            zone_id=acq.zone_id,
            requester=acq.request.requester,
            requester_session=acq.request.requester_session,
            request_version=acq.request.request_version,
            grant_id=acq.request.grant_id,
            cancel_seq=max(1, acq.cancel_seq),
            durably_non_executable=True,
            reason=(acq.cancel_reason or "cancelled")[:64],
            time_domain=acq.request.time_domain,
        )

    # ------------------------------------------------------------- occupancy

    def declare_occupy(self, now_ns: int) -> bool:
        acq = self._active
        if acq is None or acq.phase is not AcquisitionPhase.GRANTED:
            return False
        acq.occupancy_seq += 1
        record = self.journal.append(
            RECORD_OCCUPANCY,
            {
                "zone_id": acq.zone_id,
                "requester": acq.request.requester,
                "request_version": acq.request.request_version,
                "occupancy_seq": acq.occupancy_seq,
                "owner": self.robot_id,
            },
        )
        if not record:
            self.log(now_ns, "OCCUPY_NOT_DURABLE", acq.zone_id)
            return False
        acq.occupy_emitted = False
        acq.phase = AcquisitionPhase.OCCUPIED
        self.log(now_ns, "OCCUPIED", acq.zone_id, f"seq={acq.occupancy_seq}")
        return True

    def occupy_body(self, acq: Acquisition) -> ZoneOccupyBody:
        return ZoneOccupyBody(
            run_id=acq.request.run_id,
            epoch=acq.request.epoch,
            zone_id=acq.zone_id,
            requester=acq.request.requester,
            requester_session=acq.request.requester_session,
            request_version=acq.request.request_version,
            grant_id=acq.request.grant_id,
            occupancy_seq=acq.occupancy_seq,
        )

    # --------------------------------------------------------------- release

    def declare_release(self, now_ns: int) -> bool:
        acq = self._active
        if acq is None or acq.phase not in (AcquisitionPhase.OCCUPIED,):
            return False
        acq.release_seq += 1
        record = self.journal.append(
            RECORD_RELEASE,
            {
                "zone_id": acq.zone_id,
                "requester": acq.request.requester,
                "request_version": acq.request.request_version,
                "occupancy_seq": acq.occupancy_seq,
                "release_seq": acq.release_seq,
                "asserts_full_clearance": True,
                "owner": self.robot_id,
            },
        )
        if not record:
            self.log(now_ns, "RELEASE_NOT_DURABLE", acq.zone_id)
            return False
        acq.phase = AcquisitionPhase.RELEASING
        acq.release_sent_ns = now_ns
        acq.release_emitted = False
        self.log(now_ns, "RELEASING", acq.zone_id, f"seq={acq.release_seq}")
        return True

    def release_body(self, acq: Acquisition) -> ZoneReleaseBody:
        return ZoneReleaseBody(
            run_id=acq.request.run_id,
            epoch=acq.request.epoch,
            zone_id=acq.zone_id,
            requester=acq.request.requester,
            requester_session=acq.request.requester_session,
            request_version=acq.request.request_version,
            grant_id=acq.request.grant_id,
            occupancy_seq=acq.occupancy_seq,
            release_seq=acq.release_seq,
            asserts_full_clearance=True,
            time_domain=acq.request.time_domain,
        )

    def settle_release(self, now_ns: int) -> None:
        """The owner's own record is clear and the release reached every voter.

        ``RELEASED`` is the owner closing its books, not a claim that the aisle is
        empty: the authoritative ``FREE`` state lives at each voter, and a voter
        that never reconciled keeps the zone ``OCCUPIED``.
        """
        acq = self._active
        if acq is None or acq.phase is not AcquisitionPhase.RELEASING:
            return
        acq.phase = AcquisitionPhase.RELEASED
        self.log(now_ns, "RELEASED", acq.zone_id, f"seq={acq.release_seq}")

    # ------------------------------------------------------------- admission

    def may_enter(self, now_ns: int) -> bool:
        return self.admission(now_ns).kind is BlockingClass.NONE

    def admission(self, now_ns: int) -> BlockingReport:
        """Every admission condition, explicit and reported."""
        acq = self._active
        if acq is None:
            return BlockingReport(BlockingClass.IDLE, "no outstanding zone request")
        if acq.phase in TERMINAL_PHASES and self._last_rejection is None:
            return BlockingReport(BlockingClass.IDLE, f"transaction ended as {acq.phase.value}")
        if acq.phase in (AcquisitionPhase.INITIATED, AcquisitionPhase.ACQUIRING):
            slot = acq.pending_slot()
            held = acq.held()
            return BlockingReport(
                kind=(BlockingClass.PARTIAL_ACQUISITION if held else BlockingClass.ACQUIRING),
                detail=(
                    "walking canonical order"
                    if slot is not None
                    else "every voter granted; awaiting admission"
                ),
                blocking_peer=slot.voter if slot is not None else None,
                blocking_resource=slot.voter if slot is not None else acq.zone_id,
            )
        if acq.phase in (AcquisitionPhase.CANCELLING, AcquisitionPhase.CANCELLED):
            return BlockingReport(
                BlockingClass.PARTITION_STOP,
                f"durably non-executable ({acq.cancel_reason or 'cancelling'})",
                blocking_resource=acq.zone_id,
            )
        if acq.phase is AcquisitionPhase.RELEASING:
            return BlockingReport(
                BlockingClass.RELEASING,
                "release not yet reconciled at every voter",
                blocking_resource=acq.zone_id,
            )
        if acq.phase is not AcquisitionPhase.GRANTED:
            return BlockingReport(
                BlockingClass.IDLE, f"phase is {acq.phase.value}", blocking_resource=acq.zone_id
            )
        if acq.durably_non_executable:
            return BlockingReport(
                BlockingClass.PARTITION_STOP, "durably non-executable", blocking_resource=acq.zone_id
            )
        if not acq.all_slots_granted() or self.held_grants != len(self.voter.required_voters):
            return BlockingReport(
                BlockingClass.PARTIAL_ACQUISITION,
                "the grant set is incomplete",
                blocking_resource=acq.zone_id,
            )
        computed = self.compute_digest(acq)
        advertised = acq.digests()
        if not advertised or any(d != computed for d in advertised):
            first = advertised[0][:12] if advertised else "none"
            return BlockingReport(
                BlockingClass.DIGEST_MISMATCH,
                f"computed {computed[:12]} != advertised {first}",
                blocking_resource=acq.zone_id,
            )
        if not self.journal.healthy:
            return BlockingReport(
                BlockingClass.JOURNAL_UNAVAILABLE,
                "authority journal is unhealthy; entry needs a durable commitment",
                blocking_resource=acq.zone_id,
            )
        if acq.entry_commit_record == "":
            record = self.journal.append(
                "entry_commit",
                {
                    "zone_id": acq.zone_id,
                    "requester": acq.request.requester,
                    "request_version": acq.request.request_version,
                    "grant_id": acq.request.grant_id,
                    "required_set_digest": computed,
                },
            )
            if not record:
                return BlockingReport(
                    BlockingClass.JOURNAL_UNAVAILABLE,
                    "could not journal the entry commitment",
                    blocking_resource=acq.zone_id,
                )
            acq.entry_commit_record = record
        permitted, reason = self._safety_check(
            AdmissionContext(
                zone_id=acq.zone_id,
                movement=acq.movement,
                entry_pose=acq.request.entry_pose,
                exit_pose=acq.request.exit_pose,
                required_voters=self.voter.required_voters,
                held_voters=acq.held(),
                required_set_digest=computed,
                now_ns=now_ns,
            )
        )
        if not permitted:
            return BlockingReport(
                BlockingClass.SAFETY_GATE,
                f"local safety gate vetoed entry: {reason}",
                blocking_resource=acq.zone_id,
            )
        return BlockingReport(BlockingClass.NONE, "entry permitted", blocking_resource=acq.zone_id)

    def set_obstruction(self, zone_id: str, obstructed: bool) -> None:
        if obstructed:
            self._obstructions.add(zone_id)
        else:
            self._obstructions.discard(zone_id)

    def obstructions(self) -> tuple[str, ...]:
        return tuple(sorted(self._obstructions))

    def wait_for(self) -> str | None:
        """The peer this robot is blocked on, if any.

        An edge exists only while this robot *holds* something it must eventually
        release. A robot that is merely queued behind somebody blocks nobody, so
        it contributes no edge - which is what keeps the published wait-for graph
        acyclic (ADR 0003 section 4). One edge per robot is published, so the
        operator/API layer can run
        :func:`niharamesh.coordination.recovery.detect_wait_for_cycle` over the
        whole fleet and disprove a deadlock claim.
        """
        acq = self._active
        if acq is None or acq.phase is not AcquisitionPhase.ACQUIRING or not acq.held():
            return None
        slot = acq.pending_slot()
        return None if slot is None else slot.voter

    def is_pending(self, voter: str) -> bool:
        """True when ``voter`` is the single outstanding solicitation."""
        acq = self._active
        if acq is None or acq.phase is not AcquisitionPhase.ACQUIRING:
            return False
        slot = acq.pending_slot()
        return slot is not None and slot.voter == voter and slot.state is VoterSlotState.PENDING

    def blocking_report(self, now_ns: int) -> BlockingReport:
        """Fold the lifecycle, the contention history and obstructions together.

        The classes are distinguished on purpose: ``HEALTHY_CONTENTION`` means a
        peer is using the zone, ``STARVATION_SUSPECTED`` means this robot keeps
        losing that race, ``LIVELOCK_SUSPECTED`` means it keeps being refused
        with *no* holder named, and ``DEADLOCK_SUSPECTED`` is only ever raised by
        an actual cycle over the published wait-for edges.
        """
        acq = self._active
        if acq is not None and acq.zone_id in self._obstructions:
            return BlockingReport(
                BlockingClass.PHYSICAL_OBSTRUCTION,
                "an obstruction was reported inside this zone",
                blocking_resource=acq.zone_id,
            )
        report = self.admission(now_ns)
        refusal = acq.last_refusal() if acq is not None else self._last_rejection
        if refusal is None:
            return report
        refusals = acq.refusals_seen if acq is not None else self._retries
        if refusals < RETRY_REFUSALS:
            return blocking_from_refusal(refusal)
        holder = refusal.blocking_requester
        kind = BlockingClass.STARVATION_SUSPECTED if holder else BlockingClass.LIVELOCK_SUSPECTED
        detail = (
            f"refused {refusals} times with {refusal.reason.value}"
            f"{f'; {holder} is using the zone' if holder else '; no holder is progressing'}"
        )
        return BlockingReport(
            kind=kind,
            detail=detail,
            blocking_peer=holder or refusal.blocking_voter,
            blocking_resource=refusal.blocking_zone or refusal.zone_id,
            blocking_request=refusal.blocking_grant_id,
        )

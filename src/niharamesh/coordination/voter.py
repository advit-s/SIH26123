"""The voter half: what this robot promises other robots, and what it durably holds.

The voter is where safety is decided for everyone else, so every rule here is
written as an *explicit refusal with a reason* rather than as a silent ``None``:
a requester that is told nothing has to wait for a timeout, and a timeout looks
exactly like a partition.

Three rules, in the order they are checked:

``P1`` one promise per (voter, zone)
    A zone may be promised to exactly one transaction at a time.
    Refused as ``ZONE_PROMISED``.

``P2`` one promise per (voter, requester), across all zones
    ``AGENTS.md`` invariant 6 in the direction this module can enforce: if this
    voter already owes *this requester* an outstanding grant somewhere, a new
    solicitation is refused as ``GRANT_HELD``. This is the voter-side
    cross-check for the requester-side rule.

``P3`` durability before acknowledgement
    The promise is appended to the journal *before* the grant is returned. A
    failed append is ``NOT_READY`` and no authority exists.

See ``docs/protocol/ZONE_PROTOCOL.md`` sections 5-7 and
``docs/adr/0003-single-outstanding-grant.md``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from niharamesh.coordination.recovery import (
    RECORD_CANCEL,
    RECORD_FENCE,
    RECORD_OCCUPANCY,
    RECORD_PROMISE,
    RECORD_REFUSAL,
    RECORD_RELEASE,
    FenceDetails,
    FencedZone,
    FencedZoneReader,
    FenceOutcome,
    RecoveryReport,
    RecoveryState,
    fence_zone,
    inspect_fenced_zones,
    recover_from_journal,
)
from niharamesh.domain.coordination import (
    RejectionReason,
    ZoneCancelAckBody,
    ZoneCancelBody,
    ZoneFenceBody,
    ZoneGrantBody,
    ZoneOccupyBody,
    ZoneReleaseBody,
    ZoneRequestBody,
    grant_identity,
    transaction_id,
)
from niharamesh.domain.identity import Membership, MembershipState
from niharamesh.domain.map import ZoneState
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION
from niharamesh.ports import AuthorityJournal

__all__ = [
    "DEFAULT_QUEUE_TTL_NS",
    "REFUSAL_PREFIX",
    "REFUSAL_SEQ",
    "CancelOutcome",
    "GrantRecord",
    "QueueEntry",
    "Refusal",
    "VoterOutcome",
    "ZoneRecord",
    "ZoneVoter",
    "decode_refusal",
    "encode_refusal",
    "required_set_digest",
]

#: Bounded replay window on the request version of a (zone, requester) pair.
REPLAY_WINDOW_VERSIONS: Final[int] = 8

#: How long a waiting requester keeps its queue position. This expires
#: *permission to assume the queue head will return* - never physical occupancy
#: and never an issued promise - so a crashed queue head cannot wedge a zone for
#: good. ``ZoneProtocol`` derives the real value from ``solicit_timeout_s``.
DEFAULT_QUEUE_TTL_NS: Final[int] = 4_000_000_000

#: ``ZoneCancelAckBody.cancel_seq`` value the voter uses for a *refusal*.
#: A genuine cancellation acknowledgement always echoes the owner's cancel_seq,
#: which is 1 or more, so this is distinguished by the slot state as well.
REFUSAL_SEQ: Final[int] = 1

#: Prefix under which the refusing voter encodes its ``RejectionReason`` in the
#: negative acknowledgement's ``PeerEnvelope.correlation_id``.
#:
#: The wire vocabulary in ``domain/coordination.py`` has no rejection body, and a
#: requester that is told nothing has to wait for a timeout - which looks exactly
#: like a partition. So the reason travels in a bounded framing field, and the
#: *authoritative* record of the refusal stays the voter's own durable
#: ``refusal`` journal entry plus :meth:`ZoneVoter.last_refusal`.
REFUSAL_PREFIX: Final[str] = "nack:"


def encode_refusal(reason: RejectionReason) -> str:
    """Encode a refusal reason into a bounded framing field."""
    return f"{REFUSAL_PREFIX}{reason.value}"[:64]


def decode_refusal(correlation_id: str) -> RejectionReason | None:
    """Decode a refusal reason, or ``None`` when the field carries nothing."""
    if not correlation_id.startswith(REFUSAL_PREFIX):
        return None
    try:
        return RejectionReason(correlation_id[len(REFUSAL_PREFIX) :])
    except ValueError:
        return RejectionReason.PROTOCOL_VIOLATION


def required_set_digest(
    run_id: str,
    epoch: str,
    zone_id: str,
    requester: str,
    requester_session: str,
    request_version: int,
    order: Sequence[str],
    sessions: Mapping[str, str],
) -> str:
    """The one definition of the required-set digest.

    SHA-256 over the ascending list of ``(robot_id, session_id, grant_id)`` for
    the *whole* required set. Every ``grant_id`` is derivable from the request
    alone, so an advertising voter and a verifying requester compute the same
    value without having talked to each other; if their views of the membership
    or of a peer's boot differ, the digests differ and entry is withheld.
    """
    rows: list[str] = []
    for robot_id in sorted(order):
        session_id = sessions[robot_id]
        gid = grant_identity(run_id, epoch, zone_id, requester, requester_session, request_version)
        rows.append(f"{robot_id}|{session_id}|{gid}")
    return hashlib.sha256("|".join(rows).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Refusal:
    """An explicit refusal. Always carries a reason and the blocking parties."""

    reason: RejectionReason
    detail: str
    zone_id: str
    requester: str
    request_version: int
    blocking_requester: str | None = None
    blocking_zone: str | None = None
    blocking_grant_id: str | None = None
    blocking_voter: str | None = None

    def describe(self) -> str:
        parts = [
            f"reason={self.reason.value}",
            f"zone={self.zone_id}",
            f"requester={self.requester}",
        ]
        if self.blocking_requester is not None:
            parts.append(f"blocking_requester={self.blocking_requester}")
        if self.blocking_zone is not None:
            parts.append(f"blocking_zone={self.blocking_zone}")
        if self.blocking_voter is not None:
            parts.append(f"blocking_voter={self.blocking_voter}")
        parts.append(f"detail={self.detail}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class GrantRecord:
    """A durable promise that exists *after* the journal append succeeded."""

    zone_id: str
    grant_id: str
    requester: str
    requester_session: str
    request_version: int
    persistence_record_id: str
    required_set_digest: str
    is_self_voter: bool


@dataclass(slots=True)
class VoterOutcome:
    """Result of one solicitation: exactly one of ``grant`` / ``refusal``."""

    grant: GrantRecord | None = None
    refusal: Refusal | None = None
    duplicate: bool = False

    @property
    def granted(self) -> bool:
        return self.grant is not None

    @property
    def reason(self) -> RejectionReason | None:
        return None if self.refusal is None else self.refusal.reason


@dataclass(slots=True)
class QueueEntry:
    """One waiting requester at a voter, for one zone.

    The queue is *fairness ordering only*. It is never authority: an entry does
    not reserve the zone, and it never reorders authority that was already
    issued. It exists because without it canonical sequential acquisition is
    structurally monopolised by the lowest-index robot - see ADR 0003 section 6.
    """

    requester: str
    requester_session: str
    request_version: int
    queued_at_ns: int

    def matches(self, body: ZoneRequestBody) -> bool:
        return self.requester == body.requester and self.requester_session == (body.requester_session)


def _payload(
    zone_id: str,
    requester: str,
    requester_session: str,
    request_version: int,
    grant_id: str,
    **extra: object,
) -> dict[str, object]:
    """The identity every zone journal record carries, plus its own fields.

    One definition, so the voter and the requester can never drift on which
    fields identify a transaction. :func:`reconcile_records` folds exactly these.
    """
    return {
        "zone_id": zone_id,
        "requester": requester,
        "requester_session": requester_session,
        "request_version": request_version,
        "grant_id": grant_id,
        **extra,
    }


@dataclass(frozen=True, slots=True)
class ReleaseOutcome:
    """Result of reconciling one ``ZoneReleaseBody``.

    ``relay_to`` is the relay set: a voter forwards the owner's release onward so
    every required voter can observe that *every* peer reconciled it. Relays are
    loop-bounded - each ``(voter, sender)`` pair forwards at most once per
    ``(zone, grant_id)`` - so the message count stays ``O(n^2)``.
    """

    zone_id: str
    grant_id: str
    released_by: frozenset[str]
    free: bool
    relay_to: tuple[str, ...] = ()

    @property
    def detail(self) -> str:
        if self.free:
            return "release reconciled by every required voter"
        return f"release partially reconciled by {sorted(self.released_by)}"


@dataclass(frozen=True, slots=True)
class CancelOutcome:
    """Result of reconciling one ``ZoneCancelBody``.

    ``refusal`` is set only when *this* call refused, so a caller never has to
    guess whether an older refusal record is still relevant.
    """

    ack: ZoneCancelAckBody
    refusal: Refusal | None = None

    @property
    def no_record(self) -> bool:
        return self.ack.no_record


@dataclass(slots=True)
class ZoneRecord:
    """Durable per-zone state held by this voter."""

    zone_id: str
    state: ZoneState
    requester: str
    requester_session: str
    request_version: int
    grant_id: str
    txn: str
    persistence_record_id: str
    required_set_digest: str = ""
    occupancy_seq: int = 0
    release_seq: int = 0
    released_by: set[str] = field(default_factory=set)
    cancel_seq: int = 0
    durably_non_executable: bool = False
    fenced_by: str | None = None
    fence_reason: str | None = None
    previous_holder: str | None = None
    previous_requester_session: str | None = None
    operator_authorised: bool = False
    fenced_at_ns: int = 0

    def released_fully(self) -> bool:
        """True when every required voter reconciled the release."""
        return self.state is ZoneState.FREE


class ZoneVoter:
    """One robot's durable promise store. No sockets, no asyncio, no I/O."""

    def __init__(
        self,
        *,
        robot_id: str,
        session_id: str,
        membership: Membership,
        journal: AuthorityJournal,
        session_registry: Callable[[str], str | None],
        known_zones: frozenset[str] = frozenset(),
        queue_ttl_ns: int = DEFAULT_QUEUE_TTL_NS,
    ) -> None:
        self.robot_id = robot_id
        self.session_id = session_id
        self.membership = membership
        self.journal = journal
        self.known_zones = known_zones
        self.queue_ttl_ns = max(1, queue_ttl_ns)
        self._session_registry = session_registry
        self._records: dict[str, ZoneRecord] = {}
        self._refusals: dict[str, Refusal] = {}
        self._queues: dict[str, list[QueueEntry]] = {}
        self._release_seen: dict[str, set[str]] = {}
        #: Grant identities whose zone was fully released and reconciled. A bounded
        #: tombstone: it exists so a replayed ``zone_occupy`` for a *finished*
        #: transaction is refused, while an unrecorded occupancy for a transaction
        #: this voter merely lost is still adopted. See :meth:`apply_occupy`.
        self._released_grants: set[str] = set()
        self._highest_version: dict[tuple[str, str], int] = {}
        self._recovery: RecoveryReport = RecoveryReport(
            recovery_state=RecoveryState.UNKNOWN_STOPPED,
            degraded=True,
            outstanding_zones=(),
            reasons=("not_started",),
            zones={},
        )

    # ------------------------------------------------------------------ state

    @property
    def recovery_state(self) -> RecoveryState:
        return self._recovery.recovery_state

    @property
    def degraded(self) -> bool:
        return self._recovery.degraded

    @property
    def recovery(self) -> RecoveryReport:
        return self._recovery

    @property
    def required_voters(self) -> tuple[str, ...]:
        """Canonical order, ascending ``robot_id``. Everyone walks this list."""
        return self.membership.order()

    def sessions(self) -> dict[str, str]:
        """Boot ids of every admitted member; incomplete sets are explicit."""
        out: dict[str, str] = {}
        for robot_id in self.membership.members:
            session = self._session_registry(robot_id)
            if session is None:
                continue
            out[robot_id] = session
        return out

    def state_of(self, zone_id: str) -> ZoneState:
        record = self._records.get(zone_id)
        return ZoneState.FREE if record is None else record.state

    def record(self, zone_id: str) -> ZoneRecord | None:
        return self._records.get(zone_id)

    def records(self) -> tuple[ZoneRecord, ...]:
        return tuple(self._records[k] for k in sorted(self._records))

    def fence_details(self, zone_id: str) -> FenceDetails | None:
        record = self._records.get(zone_id)
        if record is None or record.state is not ZoneState.FENCED or record.fenced_by is None:
            return None
        return FenceDetails(
            zone_id=zone_id,
            fenced_by=record.fenced_by,
            fence_reason=record.fence_reason or "",
            previous_holder=record.previous_holder,
            previous_requester_session=record.previous_requester_session,
            operator_authorised=record.operator_authorised,
            fenced_at_ns=record.fenced_at_ns,
        )

    def last_refusal(self, zone_id: str) -> Refusal | None:
        return self._refusals.get(zone_id)

    def outstanding_promises(self) -> tuple[ZoneRecord, ...]:
        """Promises this voter has issued that have not been released."""
        return tuple(r for r in self.records() if r.state in (ZoneState.PROMISED, ZoneState.OCCUPIED))

    def promised_zones_for(self, requester: str) -> tuple[str, ...]:
        return tuple(r.zone_id for r in self.outstanding_promises() if r.requester == requester)

    def fenced_zones(self, zone_ids: Sequence[str]) -> tuple[FencedZone, ...]:
        return inspect_fenced_zones(self, zone_ids)

    def reader(self) -> FencedZoneReader:
        return self

    # --------------------------------------------------------------- recovery

    @staticmethod
    def _slot_int(slot: Mapping[str, object], key: str) -> int:
        """Journal payloads are ``object``-typed; narrow before converting."""
        value = slot.get(key)
        if isinstance(value, bool):
            return 0
        return value if isinstance(value, int) else 0

    @staticmethod
    def _slot_text(slot: Mapping[str, object], key: str) -> str:
        value = slot.get(key)
        return value if isinstance(value, str) else ""

    def recover_from_journal(self) -> RecoveryReport:
        """Re-derive outstanding promises at boot.

        A promise is never forgotten. If the journal is unhealthy or carries a
        record we cannot attribute to a zone, this robot enters
        ``UNKNOWN_STOPPED``: it grants nothing and reports degraded.
        """
        report = recover_from_journal(self.journal)
        self._records = {}
        self._highest_version = {}
        self._refusals = {}
        self._queues = {}
        self._release_seen = {}
        if report.grants_nothing:
            self._recovery = report
            return report
        for zone_id, slot in sorted(report.zones.items()):
            state = ZoneState(self._slot_text(slot, "state") or ZoneState.FREE.value)
            if state is ZoneState.FREE:
                continue
            record = ZoneRecord(
                zone_id=zone_id,
                state=state,
                requester=self._slot_text(slot, "requester"),
                requester_session=self._slot_text(slot, "requester_session"),
                request_version=self._slot_int(slot, "request_version"),
                grant_id=self._slot_text(slot, "grant_id"),
                txn=self._slot_text(slot, "txn"),
                persistence_record_id=self._slot_text(slot, "persistence_record_id"),
                occupancy_seq=self._slot_int(slot, "occupancy_seq"),
                release_seq=self._slot_int(slot, "release_seq"),
            )
            self._records[zone_id] = record
            if record.request_version > 0:
                self._highest_version[(zone_id, record.requester)] = record.request_version
        self._recovery = report
        return report

    # ------------------------------------------------------------ solicitation

    def _record_refusal(self, refusal: Refusal) -> VoterOutcome:
        self._refusals[refusal.zone_id] = refusal
        self.journal.append(
            RECORD_REFUSAL,
            {
                "zone_id": refusal.zone_id,
                "requester": refusal.requester,
                "request_version": refusal.request_version,
                "reason": refusal.reason.value,
                "detail": refusal.detail,
                "blocking_requester": refusal.blocking_requester or "",
                "blocking_zone": refusal.blocking_zone or "",
            },
        )
        return VoterOutcome(refusal=refusal)

    def _refuse(
        self,
        reason: RejectionReason,
        detail: str,
        body: ZoneRequestBody,
        *,
        blocking_requester: str | None = None,
        blocking_zone: str | None = None,
        blocking_grant_id: str | None = None,
        blocking_voter: str | None = None,
    ) -> VoterOutcome:
        return self._record_refusal(
            Refusal(
                reason=reason,
                detail=detail,
                zone_id=body.zone_id,
                requester=body.requester,
                request_version=body.request_version,
                blocking_requester=blocking_requester,
                blocking_zone=blocking_zone,
                blocking_grant_id=blocking_grant_id,
                blocking_voter=blocking_voter,
            )
        )

    def _admission_checks(self, body: ZoneRequestBody) -> Refusal | None:
        """Identity, version and shared-map binding, in a specific order."""
        if body.schema_version != SCHEMA_VERSION:
            return Refusal(
                RejectionReason.SCHEMA_MISMATCH,
                "request schema version",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        if body.protocol_version != PROTOCOL_VERSION:
            return Refusal(
                RejectionReason.PROTOCOL_MISMATCH,
                "request protocol version",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        if not self.membership.contains(body.requester):
            return Refusal(
                RejectionReason.REQUESTER_NOT_ADMITTED,
                "requester is not in the admitted peer set",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return Refusal(
                RejectionReason.EPOCH_MISMATCH,
                "run or membership epoch differs",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        if body.membership_digest != self.membership.digest:
            return Refusal(
                RejectionReason.MAP_MISMATCH,
                "requester's peer-set digest differs from the immutable shared map",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        if self.membership.state is not MembershipState.FROZEN:
            return Refusal(
                RejectionReason.NOT_READY,
                f"membership is {self.membership.state.value}",
                body.zone_id,
                body.requester,
                body.request_version,
            )
        return None

    def _version_check(self, body: ZoneRequestBody) -> Refusal | None:
        key = (body.zone_id, body.requester)
        highest = self._highest_version.get(key, 0)
        if body.request_version > highest:
            return None
        record = self._records.get(body.zone_id)
        same_transaction = (
            record is not None
            and record.grant_id == body.grant_id
            and record.requester_session == body.requester_session
            and record.request_version == body.request_version
        )
        if same_transaction:
            return None  # idempotent re-solicitation of a promise we already hold
        return Refusal(
            RejectionReason.REQUEST_VERSION_REPLAY,
            f"request_version {body.request_version} is not newer than {highest}",
            body.zone_id,
            body.requester,
            body.request_version,
            blocking_requester=record.requester if record is not None else None,
            blocking_zone=body.zone_id,
        )

    def solicit(self, body: ZoneRequestBody, now_ns: int) -> VoterOutcome:
        """Decide one solicitation. Never partial: grant or explicit refusal."""
        if self._recovery.grants_nothing:
            return self._refuse(
                RejectionReason.NOT_READY,
                f"stopped in {self._recovery.recovery_state.value}; grants nothing",
                body,
            )
        blocked = self._admission_checks(body)
        if blocked is not None:
            return self._record_refusal(blocked)
        replayed = self._version_check(body)
        if replayed is not None:
            return self._record_refusal(replayed)

        existing = self._records.get(body.zone_id)
        if existing is not None and existing.state is ZoneState.FENCED:
            return self._refuse(
                RejectionReason.ZONE_FENCED,
                "a previous holder failed here; there is no force release",
                body,
                blocking_requester=existing.previous_holder,
                blocking_zone=body.zone_id,
            )

        if existing is not None and existing.state is not ZoneState.FREE:
            if existing.grant_id == body.grant_id and existing.requester_session == body.requester_session:
                # Honour our own durable promise: re-grant idempotently.
                grant = self._build_grant(body, existing.persistence_record_id, existing.required_set_digest)
                return VoterOutcome(grant=grant, duplicate=True)
            position = self._enqueue(body, now_ns)
            return self._refuse(
                RejectionReason.ZONE_PROMISED,
                f"zone already {existing.state.value}; queued at position {position}",
                body,
                blocking_requester=existing.requester,
                blocking_zone=body.zone_id,
                blocking_grant_id=existing.grant_id,
                blocking_voter=self.robot_id,
            )

        # The zone is free here. Serve the head of the fairness queue rather than
        # simply whoever happened to arrive first; see ADR 0003 section 6.
        position = self._enqueue(body, now_ns)
        if position > 1:
            head = self._queues[body.zone_id][0]
            return self._refuse(
                RejectionReason.ZONE_PROMISED,
                f"zone is free but queued at position {position} behind {head.requester}",
                body,
                blocking_requester=head.requester,
                blocking_zone=body.zone_id,
                blocking_voter=self.robot_id,
            )

        # P2: this voter must not owe the same requester two promises.
        held = self.promised_zones_for(body.requester)
        if held:
            return self._refuse(
                RejectionReason.GRANT_HELD,
                f"already owes {body.requester} an outstanding grant for {held[0]!r}",
                body,
                blocking_requester=body.requester,
                blocking_zone=held[0],
                blocking_voter=self.robot_id,
            )

        sessions = self.sessions()
        if len(sessions) != self.membership.voter_count:
            missing = sorted(set(self.membership.members) - set(sessions))
            return self._refuse(
                RejectionReason.NOT_READY,
                f"boot identity unavailable for {missing}; the required set cannot be hashed",
                body,
            )
        if not self.journal.healthy:
            return self._refuse(
                RejectionReason.NOT_READY,
                "authority journal is unhealthy; an unpersisted promise is never acknowledged",
                body,
            )
        digest = required_set_digest(
            body.run_id,
            body.epoch,
            body.zone_id,
            body.requester,
            body.requester_session,
            body.request_version,
            self.required_voters,
            sessions,
        )
        record_id = self.journal.append(
            RECORD_PROMISE,
            {
                "zone_id": body.zone_id,
                "requester": body.requester,
                "requester_session": body.requester_session,
                "request_version": body.request_version,
                "grant_id": body.grant_id,
                "txn": body.txn,
                "persistence_record_id": "",
                "required_set_digest": digest,
            },
        )
        if not record_id:
            return self._refuse(
                RejectionReason.NOT_READY,
                "authority journal append failed; nothing was promised",
                body,
            )
        record = ZoneRecord(
            zone_id=body.zone_id,
            state=ZoneState.PROMISED,
            requester=body.requester,
            requester_session=body.requester_session,
            request_version=body.request_version,
            grant_id=body.grant_id,
            txn=body.txn,
            persistence_record_id=record_id,
            required_set_digest=digest,
        )
        self._records[body.zone_id] = record
        self._highest_version[(body.zone_id, body.requester)] = body.request_version
        self._leave_queue(body)
        return VoterOutcome(grant=self._build_grant(body, record_id, digest))

    # ------------------------------------------------------- fairness queue

    def queue(self, zone_id: str) -> tuple[QueueEntry, ...]:
        """The current fairness queue for ``zone_id``, oldest first."""
        return tuple(self._queues.get(zone_id, ()))

    def _prune(self, zone_id: str, now_ns: int) -> None:
        queue = self._queues.get(zone_id)
        if not queue:
            return
        kept = [e for e in queue if now_ns - e.queued_at_ns <= self.queue_ttl_ns]
        if len(kept) != len(queue):
            self._queues[zone_id] = kept

    def _enqueue(self, body: ZoneRequestBody, now_ns: int) -> int:
        """Join, or refresh, the fairness queue. Returns the 1-based position.

        A retry keeps the position it already had. Moving a retry to the back
        would let a robot lose its place by being slow, which is exactly the
        unfairness the queue exists to remove.
        """
        self._prune(body.zone_id, now_ns)
        queue = self._queues.setdefault(body.zone_id, [])
        for index, entry in enumerate(queue):
            if entry.matches(body):
                entry.request_version = body.request_version
                entry.queued_at_ns = now_ns
                return index + 1
        queue.append(
            QueueEntry(
                requester=body.requester,
                requester_session=body.requester_session,
                request_version=body.request_version,
                queued_at_ns=now_ns,
            )
        )
        return len(queue)

    def _leave_queue(self, body: ZoneRequestBody) -> None:
        queue = self._queues.get(body.zone_id)
        if not queue:
            return
        remaining = [e for e in queue if not e.matches(body)]
        if remaining:
            self._queues[body.zone_id] = remaining
        else:
            self._queues.pop(body.zone_id, None)

    def _build_grant(self, body: ZoneRequestBody, record_id: str, digest: str) -> GrantRecord:
        return GrantRecord(
            zone_id=body.zone_id,
            grant_id=body.grant_id,
            requester=body.requester,
            requester_session=body.requester_session,
            request_version=body.request_version,
            persistence_record_id=record_id,
            required_set_digest=digest,
            is_self_voter=self.robot_id == body.requester,
        )

    def to_wire(self, body: ZoneRequestBody, grant: GrantRecord) -> ZoneGrantBody:
        return ZoneGrantBody(
            run_id=body.run_id,
            epoch=body.epoch,
            zone_id=body.zone_id,
            requester=body.requester,
            requester_session=body.requester_session,
            request_version=body.request_version,
            grant_id=grant.grant_id,
            required_set_digest=grant.required_set_digest,
            is_self_voter=grant.is_self_voter,
            persistence_record_id=grant.persistence_record_id,
        )

    # ------------------------------------------------------- inbound messages

    def apply_cancel(self, body: ZoneCancelBody) -> CancelOutcome:
        """Owner-initiated durable cancellation.

        Idempotent in ``cancel_seq``: a repeat is a no-op that still answers, so
        a lost acknowledgement cannot strand the owner in ``CANCELLING``.
        """
        record = self._records.get(body.zone_id)
        if record is None or record.grant_id != body.grant_id:
            return CancelOutcome(
                ZoneCancelAckBody(
                    zone_id=body.zone_id,
                    requester=body.requester,
                    requester_session=body.requester_session,
                    request_version=body.request_version,
                    cancel_seq=body.cancel_seq,
                    voter=self.robot_id,
                    voter_session=self.session_id,
                    no_record=True,
                )
            )
        if body.cancel_seq <= record.cancel_seq:
            return CancelOutcome(
                ZoneCancelAckBody(
                    zone_id=body.zone_id,
                    requester=body.requester,
                    requester_session=body.requester_session,
                    request_version=body.request_version,
                    cancel_seq=record.cancel_seq,
                    voter=self.robot_id,
                    voter_session=self.session_id,
                    no_record=False,
                )
            )
        if record.state is ZoneState.OCCUPIED:
            # Invariant 4. A pre-entry cancellation is not evidence of clearance,
            # and the robot may physically be inside the aisle right now.
            refusal = Refusal(
                reason=RejectionReason.PROTOCOL_VIOLATION,
                detail="refused to release an occupied zone on a pre-entry cancellation",
                zone_id=body.zone_id,
                requester=body.requester,
                request_version=body.request_version,
                blocking_requester=record.requester,
                blocking_zone=body.zone_id,
            )
            self._refusals[body.zone_id] = refusal
            record.durably_non_executable = True
            return CancelOutcome(
                ZoneCancelAckBody(
                    zone_id=body.zone_id,
                    requester=body.requester,
                    requester_session=body.requester_session,
                    request_version=body.request_version,
                    cancel_seq=max(1, body.cancel_seq),
                    voter=self.robot_id,
                    voter_session=self.session_id,
                    no_record=False,
                ),
                refusal,
            )
        self.journal.append(
            RECORD_CANCEL,
            {
                "zone_id": body.zone_id,
                "requester": body.requester,
                "request_version": body.request_version,
                "grant_id": body.grant_id,
                "cancel_seq": body.cancel_seq,
                "durably_non_executable": body.durably_non_executable,
                "reason": body.reason,
                "from": self.robot_id,
            },
        )
        record.cancel_seq = body.cancel_seq
        record.durably_non_executable = body.durably_non_executable
        self._records.pop(body.zone_id, None)
        return CancelOutcome(
            ZoneCancelAckBody(
                zone_id=body.zone_id,
                requester=body.requester,
                requester_session=body.requester_session,
                request_version=body.request_version,
                cancel_seq=body.cancel_seq,
                voter=self.robot_id,
                voter_session=self.session_id,
                no_record=False,
            )
        )

    def apply_occupy(self, body: ZoneOccupyBody) -> None:
        """Declaration of physical entry. Moves the zone to OCCUPIED.

        An occupancy declaration for a zone this voter has **no record of** is
        adopted rather than discarded. That is a deliberate change from the
        previous behaviour, which returned on a missing record.

        The reason is that the only correct direction for this message is
        ``PROMISED -> OCCUPIED``, never ``FREE -> FREE``. A missing record means
        this voter has lost its own book of promises -- by a lost cancellation, a
        restart, or a message that never arrived -- and the body making the
        declaration is inside the protected geometry right now. Discarding that
        leaves the voter reading ``FREE`` while a robot is physically in the
        aisle, which is the precise state in which two robots can be granted the
        same zone. Recovering to ``OCCUPIED`` is the conservative direction: it can
        only ever refuse somebody.

        The grant identity is still checked against this voter's own record, and a
        record that exists but belongs to a *different* transaction is still
        refused -- a mismatched grant must never overwrite a live one.
        """
        record = self._records.get(body.zone_id)
        if record is not None and record.grant_id != body.grant_id:
            return
        if record is None and body.grant_id in self._released_grants:
            # This grant completed and was released. An occupancy declaration for it
            # is a replay, not news, and adopting it would re-occupy an aisle every
            # voter has already declared clear.
            return
        if record is not None and (
            record.state is ZoneState.FENCED or body.occupancy_seq < record.occupancy_seq
        ):
            return  # fenced is terminal; a stale enter/exit never applies backwards
        record_id = self.journal.append(
            RECORD_OCCUPANCY,
            {
                "zone_id": body.zone_id,
                "requester": body.requester,
                "request_version": body.request_version,
                "occupancy_seq": body.occupancy_seq,
                "grant_id": body.grant_id,
                "from": self.robot_id,
                "adopted_without_prior_record": record is None,
            },
        )
        if record is None:
            # No prior promise of our own, yet the body is declaring itself inside.
            # Adopt it as ``OCCUPIED`` -- see the method docstring -- with the
            # identity the declaration itself carries.
            #
            # Unless adopting it would leave this voter owing the **same requester**
            # two outstanding grants. That is not a corner case: it is invariant 6,
            # "at most one outstanding grant per robot, globally", and the property
            # suite found it -- a fuzzed ordering has a requester collecting a
            # promise for one zone and then declaring occupancy in another, leaving
            # this voter holding two. Invariant 6 is checked on every solicitation,
            # so the one place that can break it without passing through a check is
            # this adoption.
            #
            # Refusing is the conservative choice *for this specific case*, and it
            # leaves a hole the other branch above is careful about: this zone then
            # reads ``FREE`` here while a body is inside it. That hole is bounded to
            # "the peer already holds an authority elsewhere from me", and it is
            # recorded rather than hidden. Which of the two violations to commit is a
            # judgement, and it is stated rather than left implicit: an aisle nobody
            # arbitrates can stall, whereas two overlapping authorities cannot be
            # undone once granted.
            for other in self._records.values():
                if (
                    other.zone_id != body.zone_id
                    and other.requester == body.requester
                    and other.state in (ZoneState.PROMISED, ZoneState.OCCUPIED)
                ):
                    return
            # An adopted record must carry a real persistence id: the grant it
            # answers later echoes this back, and an empty id would fail
            # ``ZoneGrantBody``'s own validation -- turning a conservative recovery
            # into a hard failure on the next solicitation.
            persistence_record_id = record_id or f"adopted:{body.grant_id}"
            record = ZoneRecord(
                zone_id=body.zone_id,
                state=ZoneState.OCCUPIED,
                requester=body.requester,
                requester_session=body.requester_session,
                request_version=body.request_version,
                grant_id=body.grant_id,
                txn=transaction_id(body.run_id, body.request_version, body.zone_id, body.requester),
                persistence_record_id=persistence_record_id,
                occupancy_seq=body.occupancy_seq,
            )
            self._records[body.zone_id] = record
            self._highest_version[(body.zone_id, body.requester)] = body.request_version
            return
        record.occupancy_seq = body.occupancy_seq
        record.state = ZoneState.OCCUPIED

    def apply_release(self, body: ZoneReleaseBody, from_sender: str) -> ReleaseOutcome:
        """Record clearance evidence and leave ``OCCUPIED`` only with full consensus.

        A voter's record leaves ``OCCUPIED`` only when *every* required voter has
        reconciled a matching release - never on a timer, and never because a
        majority have. The owner broadcasts the release to every voter and each
        voter relays it onward once, so every voter ends up holding the complete
        set of reconciliation evidence. A lost release therefore leaves the zone
        occupied **everywhere**, not partially free, and any later solicitation is
        refused with ``ZONE_PROMISED``.
        """
        record = self._records.get(body.zone_id)
        if record is None or record.grant_id != body.grant_id:
            return ReleaseOutcome(body.zone_id, body.grant_id, frozenset(), False)
        if record.state is ZoneState.FENCED:
            return ReleaseOutcome(body.zone_id, body.grant_id, frozenset(record.released_by), False)
        if body.occupancy_seq < record.occupancy_seq:
            # A stale exit is refused, never applied backwards.
            return ReleaseOutcome(body.zone_id, body.grant_id, frozenset(record.released_by), False)
        seen = self._release_seen.setdefault(body.zone_id, set())
        first_time = from_sender not in seen
        seen.add(from_sender)
        record.release_seq = max(record.release_seq, body.release_seq)
        record.released_by.add(self.robot_id)
        record.released_by.add(from_sender)
        self.journal.append(
            RECORD_RELEASE,
            {
                "zone_id": body.zone_id,
                "requester": body.requester,
                "request_version": body.request_version,
                "occupancy_seq": body.occupancy_seq,
                "release_seq": body.release_seq,
                "asserts_full_clearance": body.asserts_full_clearance,
                "reconciled_from": from_sender,
            },
        )
        free = set(self.required_voters).issubset(record.released_by)
        if free:
            record.state = ZoneState.FREE
            # Remember that *this grant* is finished. Dropping the record is what
            # lets the next request in, but it also removes the only thing that
            # could distinguish a replayed ``zone_occupy`` for a transaction that
            # completed from one for a record this voter merely lost. Without the
            # tombstone, adopting an unrecorded occupancy (see
            #: :meth:`apply_occupy`) would resurrect a zone that was properly
            # released -- the exact conservatism being traded for, in the other
            # direction.
            self._released_grants.add(record.grant_id)
            self._records.pop(body.zone_id, None)
            self._release_seen.pop(body.zone_id, None)
        relay: tuple[str, ...] = ()
        if first_time:
            relay = tuple(v for v in self.required_voters if v != self.robot_id)
        return ReleaseOutcome(body.zone_id, body.grant_id, frozenset(record.released_by), free, relay)

    def apply_fence(self, body: ZoneFenceBody, now_ns: int) -> FenceOutcome:
        """The only path out of an abandoned zone. Explicit, authorised, logged.

        A voter with no record of the zone still records the fence, so the zone
        is blocked everywhere at once rather than only where the failed holder's
        promise happened to be journaled.
        """
        outcome = fence_zone(
            body,
            known_zones=self.known_zones,
            current_state=self.state_of(body.zone_id),
        )
        if not outcome.applied or outcome.already_fenced:
            return outcome
        existing = self._records.get(body.zone_id)
        previous_holder = body.previous_holder or (existing.requester if existing else None)
        previous_session = body.previous_requester_session or (
            existing.requester_session if existing else None
        )
        self.journal.append(
            RECORD_FENCE,
            {
                "zone_id": body.zone_id,
                "fenced_by": body.fenced_by,
                "reason": body.reason,
                "previous_holder": previous_holder or "",
                "previous_requester_session": previous_session or "",
                "operator_authorised": body.operator_authorised,
                "at_ns": now_ns,
            },
        )
        record = existing or ZoneRecord(
            zone_id=body.zone_id,
            state=ZoneState.PROMISED,
            requester=previous_holder or "",
            requester_session=previous_session or "",
            request_version=0,
            grant_id="",
            txn="",
            persistence_record_id="",
        )
        record.state = ZoneState.FENCED
        record.fenced_by = body.fenced_by
        record.fence_reason = body.reason
        record.previous_holder = previous_holder
        record.previous_requester_session = previous_session
        record.operator_authorised = body.operator_authorised
        record.fenced_at_ns = now_ns
        record.released_by.clear()
        self._records[body.zone_id] = record
        return outcome

    def release_reconciled(self, zone_id: str) -> bool:
        """True when this voter no longer holds the zone for any reason."""
        record = self._records.get(zone_id)
        return record is None or record.state is ZoneState.FREE

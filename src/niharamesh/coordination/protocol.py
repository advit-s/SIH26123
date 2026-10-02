"""``ZoneProtocol``: one robot's complete exclusive-zone coordination instance.

This is the object the agent runtime drives. It owns exactly two things - a
:class:`~niharamesh.coordination.voter.ZoneVoter` (what it promises peers) and a
:class:`~niharamesh.coordination.requester.ZoneRequester` (what it asks for) -
plus the framing, identity validation and freshness bookkeeping that connect them.

It implements :class:`niharamesh.ports.ZoneCoordinator` and adds:

* :meth:`ingest` - the same work as :meth:`handle`, but returning the explicit
  outcome so a caller (and a test) can read the exact ``RejectionReason``;
* an **outbox** of ``(peer_id, PeerMessage)`` pairs. There is no ``await`` and no
  socket anywhere in this package: the transport drains the outbox.

Every refusal is explicit. No path in this module leaves a peer waiting for a
timeout to learn that it was refused.

See ``docs/protocol/ZONE_PROTOCOL.md``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from niharamesh.clocks import SharedClockEstimator
from niharamesh.coordination.freshness import (
    ClockJumpGuard,
    FreshnessTable,
    classify_heartbeat,
    classify_intent,
    classify_peer_state,
)
from niharamesh.coordination.recovery import (
    FencedZone,
    FenceOutcome,
    RecoveryState,
    detect_wait_for_cycle,
)
from niharamesh.coordination.requester import (
    BlockingClass,
    BlockingReport,
    ProtocolAction,
    ProtocolEvent,
    SafetyCheck,
    ZoneRequester,
)
from niharamesh.coordination.voter import (
    REFUSAL_SEQ,
    Refusal,
    ZoneVoter,
    decode_refusal,
    encode_refusal,
    required_set_digest,
)
from niharamesh.domain.config import ProtocolTiming
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    FreshnessClass,
    Heartbeat,
    ObstructionReport,
    PeerEnvelope,
    PeerIntent,
    PeerMessage,
    PeerMessageBodyT,
    PeerState,
    RejectionReason,
    ZoneCancelAckBody,
    ZoneCancelBody,
    ZoneFenceBody,
    ZoneGrantBody,
    ZoneOccupyBody,
    ZoneReleaseBody,
    ZoneRequestBody,
    build_message,
)
from niharamesh.domain.identity import Membership
from niharamesh.domain.map import WarehouseMap, ZoneMovement, ZoneState
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION, TimeDomain
from niharamesh.ports import AuthorityJournal, FreshnessVerdict

__all__ = [
    "IngestOutcome",
    "ReplayWindow",
    "SeqVerdict",
    "ZoneProtocol",
]

NS_PER_S: Final[int] = 1_000_000_000
#: Bounded replay protection on the per-sender envelope sequence.
REPLAY_WINDOW: Final[int] = 64
#: Advertised traversal budget when the caller does not state one.
DEFAULT_TRAVERSE_BUDGET_NS: Final[int] = 30 * NS_PER_S


class SeqVerdict(StrEnum):
    NEW = "new"
    DUPLICATE = "duplicate"
    """Inside the replay window and already applied: an idempotent no-op."""
    REPLAYED = "replayed"
    """Below the replay window. Refused as ``SEQUENCE_REPLAY``."""


@dataclass(slots=True)
class ReplayWindow:
    """Bounded per-sender replay protection that still tolerates reordering."""

    window: int = REPLAY_WINDOW
    _max: dict[str, int] = field(default_factory=dict, repr=False)
    _seen: dict[str, set[int]] = field(default_factory=dict, repr=False)

    def check(self, sender: str, seq: int) -> SeqVerdict:
        highest = self._max.get(sender, -1)
        seen = self._seen.setdefault(sender, set())
        if seq > highest:
            self._max[sender] = seq
            seen.add(seq)
            self._trim(sender)
            return SeqVerdict.NEW
        if seq <= highest - self.window:
            return SeqVerdict.REPLAYED
        if seq in seen:
            return SeqVerdict.DUPLICATE
        seen.add(seq)
        self._trim(sender)
        return SeqVerdict.NEW

    def _trim(self, sender: str) -> None:
        seen = self._seen.get(sender)
        if seen is None:
            return
        floor = self._max.get(sender, 0) - self.window
        for seq in sorted(s for s in seen if s <= floor):
            seen.discard(seq)


@dataclass(frozen=True, slots=True)
class IngestOutcome:
    """What happened to one inbound message. Never a bare ``None``."""

    accepted: bool
    reason: RejectionReason | None = None
    detail: str = ""
    kind: str = ""
    answered: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return self.accepted


class ZoneProtocol:
    """One robot process's exclusive-zone coordination instance."""

    def __init__(
        self,
        *,
        robot_id: str,
        session_id: str,
        membership: Membership,
        journal: AuthorityJournal,
        warehouse_map: WarehouseMap,
        timing: ProtocolTiming | None = None,
        safety_check: SafetyCheck | None = None,
        time_domain: TimeDomain = TimeDomain.LOGICAL,
        session_registry: Callable[[str], str | None] | None = None,
        clock_estimator: SharedClockEstimator | None = None,
    ) -> None:
        if not membership.contains(robot_id):
            raise ValueError(f"{robot_id!r} is not an admitted member of this run")
        if not membership.digest:
            raise ValueError(
                "membership digest is empty; the shared-map binding is not established, "
                "so no zone transaction can be admitted"
            )
        self.robot_id = robot_id
        self.session_id = session_id
        self.membership = membership
        self.timing = timing or ProtocolTiming()
        self.time_domain = time_domain
        self.warehouse_map = warehouse_map
        self._map_digest = warehouse_map.digest()
        self._sessions: dict[str, str] = {}
        if session_registry is not None:
            for rid in membership.members:
                self._sessions[rid] = session_registry(rid) or ""
        self.voter = ZoneVoter(
            robot_id=robot_id,
            session_id=session_id,
            membership=membership,
            journal=journal,
            session_registry=lambda rid: self._sessions.get(rid) or None,
            known_zones=frozenset(z.id for z in warehouse_map.zones),
            queue_ttl_ns=int(self.timing.solicit_timeout_s * NS_PER_S) * 4,
        )
        self.requester = ZoneRequester(
            robot_id=robot_id,
            session_id=session_id,
            journal=journal,
            voter=self.voter,
            solicit_timeout_ns=int(self.timing.solicit_timeout_s * NS_PER_S),
            cancel_timeout_ns=int(self.timing.cancel_timeout_s * NS_PER_S),
            release_timeout_ns=int(self.timing.release_timeout_s * NS_PER_S),
            safety_check=safety_check or _safety_unavailable,
        )
        self.freshness = FreshnessTable(
            local_domain=time_domain,
            horizon_ns=int(self.timing.freshness_horizon_s * NS_PER_S),
            estimator=clock_estimator,
            guard=ClockJumpGuard(),
        )
        self.outbox: list[tuple[str, PeerMessage]] = []
        self.replay = ReplayWindow()
        self.quarantined: set[str] = set()
        self.refusals: list[ProtocolEvent] = []
        self._now_ns = 0
        self._seq = 0
        self._retry_zone: str | None = None

    # ------------------------------------------------------------------ state

    @property
    def now_ns(self) -> int:
        return self._now_ns

    @property
    def recovery_state(self) -> RecoveryState:
        return self.voter.recovery_state

    @property
    def degraded(self) -> bool:
        return self.voter.degraded

    @property
    def stopped(self) -> bool:
        """Unknown recovery: this robot grants nothing and enters nothing."""
        return self.voter.recovery.grants_nothing

    @property
    def events(self) -> tuple[ProtocolEvent, ...]:
        return (*self.requester.events, *self.refusals)

    def start(self) -> RecoveryState:
        """Boot: re-derive outstanding promises before anything else happens."""
        return self.voter.recover_from_journal().recovery_state

    def phase(self) -> AcquisitionPhase:
        return self.requester.phase()

    # ------------------------------------------- ports.ZoneCoordinator surface

    def required_voters(self, requester: str) -> tuple[str, ...]:
        del requester  # the canonical order does not depend on who is asking
        return self.voter.required_voters

    def required_set_digest(self, requester: str, zone_id: str) -> str:
        """The digest this robot advertises for ``requester``'s next attempt."""
        return required_set_digest(
            self.membership.run_id,
            self.membership.epoch,
            zone_id,
            requester,
            self._sessions.get(requester) or "",
            self.requester.next_request_version(zone_id),
            self.voter.required_voters,
            self.voter.sessions(),
        )

    def may_enter(self, zone_id: str) -> bool:
        acq = self.requester.active
        if acq is None or acq.zone_id != zone_id:
            return False
        if self.stopped:
            return False
        if self._suspended_peers():
            return False
        return self.requester.may_enter(self._now_ns)

    def why_blocked(self, zone_id: str) -> str:
        acq = self.requester.active
        if acq is not None and acq.zone_id != zone_id:
            return BlockingReport(
                BlockingClass.IDLE,
                f"the outstanding transaction is for {acq.zone_id}, not {zone_id}",
            ).render()
        if self.stopped:
            return BlockingReport(
                BlockingClass.PARTITION_STOP,
                f"stopped in {self.recovery_state.value}; durable promises cannot be re-derived",
                blocking_resource=zone_id,
            ).render()
        if self.voter.state_of(zone_id) is ZoneState.FENCED:
            details = self.voter.fence_details(zone_id)
            suffix = f" ({details.fence_reason})" if details is not None else ""
            return BlockingReport(
                BlockingClass.ZONE_FENCED,
                f"a previous holder failed here; an authorised fence is required{suffix}",
                blocking_resource=zone_id,
            ).render()
        suspended = self._suspended_peers()
        if suspended:
            return BlockingReport(
                BlockingClass.PEER_STATE_STALE,
                f"peer claims are not usable: {list(suspended)}",
                blocking_peer=suspended[0],
                blocking_resource=zone_id,
            ).render()
        return self.requester.blocking_report(self._now_ns).render()

    def begin_acquire(self, zone_id: str, *, traverse_budget_ns: int = DEFAULT_TRAVERSE_BUDGET_NS) -> None:
        """Start a canonical sequential acquisition of ``zone_id``.

        Refused outright while this robot is in ``unknown_stopped`` recovery: it
        cannot make a promise durable, so it must not ask anybody else to make one
        on its behalf either.
        """
        if self.stopped:
            self.refusals.append(
                ProtocolEvent(
                    at_ns=self._now_ns,
                    kind="ACQUIRE_REFUSED_STOPPED",
                    zone_id=zone_id,
                    detail=f"{self.recovery_state.value}; durable promises cannot be re-derived",
                )
            )
            return
        zone = self.warehouse_map.zone(zone_id)
        movement: ZoneMovement = zone.allowed_movement[0] if zone.allowed_movement else ZoneMovement.FWD
        body = ZoneRequestBody(
            run_id=self.membership.run_id,
            epoch=self.membership.epoch,
            zone_id=zone_id,
            requester=self.robot_id,
            requester_session=self.session_id,
            request_version=self.requester.next_request_version(zone_id),
            movement=movement.value,
            entry_pose=(zone.entry_pose.x, zone.entry_pose.y, zone.entry_pose.theta),
            exit_pose=(zone.exit_pose.x, zone.exit_pose.y, zone.exit_pose.theta),
            expires_at_ns=self._now_ns + max(0, traverse_budget_ns),
            time_domain=self.time_domain,
            membership_digest=self.membership.digest,
        )
        self.requester.begin(body, movement, self._now_ns)
        self._retry_zone = zone_id

    def cancel(self, reason: str) -> None:
        self.requester.cancel(reason, now_ns=self._now_ns)
        self._emit_actions(self.requester.tick(self._now_ns))

    def release(self) -> None:
        if self.requester.declare_release(self._now_ns):
            self._emit_actions(self.requester.tick(self._now_ns))

    def handle(self, message: PeerMessage) -> None:
        self.ingest(message)

    def tick(self, now_ns: int) -> None:
        self._now_ns = now_ns
        self.freshness.observe_now(now_ns)
        if self._retry_zone is not None and self.requester.retry_due(now_ns):
            self.begin_acquire(self._retry_zone)
        self._emit_actions(self.requester.tick(now_ns))
        acq = self.requester.active
        if (
            acq is not None
            and acq.phase is AcquisitionPhase.RELEASING
            and acq.release_emitted
            and self.voter.release_reconciled(acq.zone_id)
        ):
            self.requester.settle_release(now_ns)

    # ------------------------------------------------------------- lifecycle

    def mark_entered(self, zone_id: str) -> bool:
        acq = self.requester.active
        if acq is None or acq.zone_id != zone_id or not self.may_enter(zone_id):
            return False
        if not self.requester.declare_occupy(self._now_ns):
            return False
        self._emit_actions(self.requester.tick(self._now_ns))
        return True

    def apply_fence(self, body: ZoneFenceBody) -> FenceOutcome:
        return self.voter.apply_fence(body, self._now_ns)

    def fenced_zones(self) -> tuple[FencedZone, ...]:
        return self.voter.fenced_zones([z.id for z in self.warehouse_map.zones])

    def wait_for_graph(self) -> dict[str, str]:
        """The one wait-for edge this robot publishes, if any."""
        peer = self.requester.wait_for()
        return {} if peer is None else {self.robot_id: peer}

    def detect_deadlock(self, edges: Mapping[str, str]) -> tuple[str, ...] | None:
        """Cycle check over the published edges. ``None`` means acyclic."""
        return detect_wait_for_cycle(edges)

    def holders(self) -> dict[str, str]:
        """This robot's outstanding promises: ``zone_id -> requester``."""
        return {r.zone_id: r.requester for r in self.voter.outstanding_promises()}

    def last_refusal(self, zone_id: str) -> Refusal | None:
        """This voter's own durable record of the last refusal for ``zone_id``."""
        return self.voter.last_refusal(zone_id)

    # ---------------------------------------------------------------- ingest

    def _zone_of(self, message: PeerMessage) -> str:
        zone = getattr(message.body, "zone_id", "")
        return zone if isinstance(zone, str) else ""

    def _reject(self, reason: RejectionReason, detail: str, message: PeerMessage) -> IngestOutcome:
        self.refusals.append(
            ProtocolEvent(
                at_ns=self._now_ns,
                kind="INGEST_REFUSED",
                zone_id=self._zone_of(message),
                detail=f"{reason.value}: {detail} from {message.envelope.sender}",
            )
        )
        return IngestOutcome(False, reason, detail, message.envelope.kind)

    def _envelope_checks(self, message: PeerMessage) -> IngestOutcome | None:
        envelope = message.envelope
        schema = getattr(message.body, "schema_version", SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            return self._reject(RejectionReason.SCHEMA_MISMATCH, f"body schema {schema!r}", message)
        if envelope.protocol_version != PROTOCOL_VERSION:
            return self._reject(
                RejectionReason.PROTOCOL_MISMATCH,
                f"envelope protocol {envelope.protocol_version!r}",
                message,
            )
        if not self.membership.contains(envelope.sender):
            return self._reject(
                RejectionReason.REQUESTER_NOT_ADMITTED,
                f"{envelope.sender!r} is not an admitted member",
                message,
            )
        if envelope.run_id != self.membership.run_id:
            return self._reject(
                RejectionReason.PROTOCOL_MISMATCH,
                f"run {envelope.run_id!r} != {self.membership.run_id!r}",
                message,
            )
        if envelope.epoch != self.membership.epoch:
            return self._reject(
                RejectionReason.EPOCH_MISMATCH,
                f"epoch {envelope.epoch!r} != {self.membership.epoch!r}",
                message,
            )
        known = self._sessions.get(envelope.sender) or ""
        if known and envelope.sender_session != known:
            self.quarantined.add(envelope.sender)
            return self._reject(
                RejectionReason.REQUESTER_SESSION_STALE,
                f"boot {envelope.sender_session!r} is not the current {known!r}",
                message,
            )
        return None

    def ingest(self, message: PeerMessage) -> IngestOutcome:
        """Validate, then dispatch. The one entry point for inbound traffic."""
        envelope = message.envelope
        if envelope.sender == self.robot_id:
            return self._reject(
                RejectionReason.PROTOCOL_VIOLATION,
                "loopback: this robot's own voter runs in-process",
                message,
            )
        failure = self._envelope_checks(message)
        if failure is not None:
            return failure
        seq_verdict = self.replay.check(envelope.sender, envelope.seq)
        if seq_verdict is SeqVerdict.REPLAYED:
            self.quarantined.add(envelope.sender)
            return self._reject(
                RejectionReason.SEQUENCE_REPLAY,
                f"seq {envelope.seq} is below the replay window",
                message,
            )
        if seq_verdict is SeqVerdict.DUPLICATE:
            return IngestOutcome(
                True,
                None,
                "duplicate inside the replay window; idempotent no-op",
                envelope.kind,
            )
        if envelope.sender in self.quarantined:
            return self._reject(
                RejectionReason.REQUESTER_SESSION_STALE,
                f"{envelope.sender} is quarantined",
                message,
            )
        handler = self._handler(envelope.kind)
        if handler is None:
            return self._reject(
                RejectionReason.PROTOCOL_MISMATCH,
                f"unsupported kind {envelope.kind!r}",
                message,
            )
        return handler(message)

    def _handler(self, kind: str) -> Callable[[PeerMessage], IngestOutcome] | None:
        return {
            "zone_request": self._on_request,
            "zone_grant": self._on_grant,
            "zone_cancel": self._on_cancel,
            "zone_cancel_ack": self._on_cancel_ack,
            "zone_occupy": self._on_occupy,
            "zone_release": self._on_release,
            "zone_fence": self._on_fence,
            "peer_state": self._on_peer_state,
            "peer_intent": self._on_peer_intent,
            "heartbeat": self._on_heartbeat,
            "obstruction": self._on_obstruction,
        }.get(kind)

    # ------------------------------------------------------------- dispatch

    def _on_request(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneRequestBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_request body", message)
        if body.requester != message.envelope.sender or (
            body.requester_session != message.envelope.sender_session
        ):
            return self._reject(
                RejectionReason.PROTOCOL_MISMATCH,
                "envelope sender does not match the request body",
                message,
            )
        outcome = self.voter.solicit(body, self._now_ns)
        if outcome.grant is not None:
            self._send(body.requester, "zone_grant", self.voter.to_wire(body, outcome.grant), body.txn)
            return IngestOutcome(True, None, "granted", message.envelope.kind)
        refusal = outcome.refusal
        if refusal is None:  # pragma: no cover - VoterOutcome is grant XOR refusal
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "solicit produced no outcome", message)
        # Explicit negative acknowledgement: never a silent timeout. The specific
        # reason travels in ``correlation_id``; the authoritative refusal record
        # is this voter's own durable ``refusal`` entry (see ``encode_refusal``).
        self._send(
            body.requester,
            "zone_cancel_ack",
            ZoneCancelAckBody(
                zone_id=body.zone_id,
                requester=body.requester,
                requester_session=body.requester_session,
                request_version=body.request_version,
                cancel_seq=REFUSAL_SEQ,
                voter=self.robot_id,
                voter_session=self.session_id,
                no_record=True,
            ),
            encode_refusal(refusal.reason),
        )
        return IngestOutcome(False, refusal.reason, refusal.detail, message.envelope.kind, (body.requester,))

    def _on_grant(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneGrantBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_grant body", message)
        if body.requester != self.robot_id:
            return self._reject(
                RejectionReason.PROTOCOL_VIOLATION,
                "a grant addressed to this robot names a different requester",
                message,
            )
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "grant epoch", message)
        self.requester.on_grant(message.envelope.sender, body, self._now_ns)
        self._emit_actions(self.requester.tick(self._now_ns))
        return IngestOutcome(True, None, "grant recorded", message.envelope.kind)

    def _on_cancel(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneCancelBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_cancel body", message)
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "cancel epoch", message)
        outcome = self.voter.apply_cancel(body)
        if body.requester == self.robot_id:
            self.requester.on_cancel_ack(outcome.ack, self._now_ns)
        else:
            self._send(body.requester, "zone_cancel_ack", outcome.ack, body.grant_id)
        self._emit_actions(self.requester.tick(self._now_ns))
        if outcome.refusal is not None:
            return IngestOutcome(
                False,
                outcome.refusal.reason,
                outcome.refusal.detail,
                message.envelope.kind,
                (body.requester,),
            )
        return IngestOutcome(True, None, "cancel reconciled", message.envelope.kind, (outcome.ack.voter,))

    def _on_cancel_ack(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneCancelAckBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_cancel_ack body", message)
        if body.requester != self.robot_id:
            return self._reject(
                RejectionReason.PROTOCOL_VIOLATION,
                "a cancel acknowledgement addressed to this robot names another requester",
                message,
            )
        acq = self.requester.active
        slot = None if acq is None else acq.pending_slot()
        if not (self._is_refusal_nak(body) and slot is not None and slot.voter == body.voter):
            self.requester.on_cancel_ack(body, self._now_ns)
            self._emit_actions(self.requester.tick(self._now_ns))
            return IngestOutcome(True, None, "cancel acknowledged", message.envelope.kind)
        reason = decode_refusal(message.envelope.correlation_id) or (RejectionReason.PROTOCOL_VIOLATION)
        self.requester.on_refusal(
            Refusal(
                reason=reason,
                detail=f"negative acknowledgement from {body.voter}",
                zone_id=body.zone_id,
                requester=self.robot_id,
                request_version=body.request_version,
                blocking_voter=body.voter,
                blocking_zone=body.zone_id,
            ),
            self._now_ns,
        )
        self._emit_actions(self.requester.tick(self._now_ns))
        return IngestOutcome(False, reason, "refused", message.envelope.kind, (body.voter,))

    def _is_refusal_nak(self, body: ZoneCancelAckBody) -> bool:
        """A refusal is addressed to a slot we are still waiting on.

        Unambiguous: a genuine cancellation acknowledgement always carries the
        owner's own ``cancel_seq`` for a voter whose slot we already hold, and
        this one carries :data:`REFUSAL_SEQ` for the slot that is still pending.
        """
        if not body.no_record or body.cancel_seq != REFUSAL_SEQ:
            return False
        return self.requester.is_pending(body.voter)

    def _on_occupy(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneOccupyBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_occupy body", message)
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "occupy epoch", message)
        self.voter.apply_occupy(body)
        return IngestOutcome(True, None, "occupancy recorded", message.envelope.kind)

    def _on_release(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneReleaseBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_release body", message)
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "release epoch", message)
        outcome = self.voter.apply_release(body, message.envelope.sender)
        self._relay_release(body, outcome.relay_to)
        return IngestOutcome(True, None, outcome.detail, message.envelope.kind)

    def _relay_release(self, body: ZoneReleaseBody, targets: tuple[str, ...]) -> None:
        """Forward the owner's release so every voter sees full consensus."""
        for target in targets:
            if target == self.robot_id:
                self._apply_local_release(body, target)
            else:
                self._send(target, "zone_release", body)

    def _on_fence(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ZoneFenceBody):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "zone_fence body", message)
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "fence epoch", message)
        outcome = self.apply_fence(body)
        if not outcome.applied:
            return IngestOutcome(False, outcome.reason, outcome.detail, message.envelope.kind)
        return IngestOutcome(True, None, outcome.detail, message.envelope.kind)

    def _on_peer_state(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, PeerState):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "peer_state body", message)
        verdict = classify_peer_state(
            body,
            self._now_ns,
            self.time_domain,
            self.freshness.horizon_ns,
            self.freshness.estimator,
            self.freshness.guard,
        )
        self.freshness.record(
            body.robot_id,
            body.session_id,
            body.seq,
            body.sent_at_ns,
            body.time_domain,
            verdict,
            self._now_ns,
        )
        return IngestOutcome(True, None, verdict.reason, message.envelope.kind)

    def _on_peer_intent(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, PeerIntent):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "peer_intent body", message)
        if body.map_id != self.warehouse_map.map_id or body.map_digest != self._map_digest:
            return self._reject(
                RejectionReason.MAP_MISMATCH,
                f"intent is for map {body.map_id!r}",
                message,
            )
        verdict = classify_intent(
            body,
            self._now_ns,
            self.time_domain,
            self.freshness.estimator,
            self.freshness.guard,
        )
        self.freshness.record(
            body.robot_id,
            body.session_id,
            body.seq,
            body.sent_at_ns,
            body.time_domain,
            verdict,
            self._now_ns,
        )
        return IngestOutcome(True, None, verdict.reason, message.envelope.kind)

    def _on_heartbeat(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, Heartbeat):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "heartbeat body", message)
        if body.run_id != self.membership.run_id or body.epoch != self.membership.epoch:
            return self._reject(RejectionReason.EPOCH_MISMATCH, "heartbeat epoch", message)
        verdict = classify_heartbeat(
            body,
            self._now_ns,
            self.time_domain,
            self.freshness.horizon_ns,
            self.freshness.estimator,
            self.freshness.guard,
        )
        # Liveness only: recorded with ``from_heartbeat`` so it can never be
        # laundered into permission to assume anything.
        self.freshness.record(
            body.robot_id,
            body.session_id,
            body.seq,
            body.sent_at_ns,
            body.time_domain,
            verdict,
            self._now_ns,
            from_heartbeat=True,
        )
        return IngestOutcome(True, None, verdict.reason, message.envelope.kind)

    def _on_obstruction(self, message: PeerMessage) -> IngestOutcome:
        body = message.body
        if not isinstance(body, ObstructionReport):
            return self._reject(RejectionReason.PROTOCOL_VIOLATION, "obstruction body", message)
        acq = self.requester.active
        zone_id = body.zone_id or (acq.zone_id if acq is not None else None)
        if zone_id is None:
            return self._reject(RejectionReason.UNKNOWN_REQUEST, "obstruction names no zone", message)
        self.requester.set_obstruction(zone_id, True)
        return IngestOutcome(True, None, f"obstruction recorded in {zone_id}", message.envelope.kind)

    # ---------------------------------------------------------------- output

    def _emit_actions(self, actions: Sequence[ProtocolAction]) -> None:
        for action in actions:
            self._emit(action)

    def _emit(self, action: ProtocolAction) -> None:
        if action.request is not None:
            if action.target == self.robot_id:
                self._self_solicit(action.request)
            else:
                self._send(action.target, "zone_request", action.request, action.request.txn)
            return
        if action.cancel is not None:
            if action.target == self.robot_id:
                self.requester.on_cancel_ack(self.voter.apply_cancel(action.cancel).ack, self._now_ns)
            else:
                self._send(action.target, "zone_cancel", action.cancel, action.cancel.grant_id)
            return
        if action.occupy is not None:
            if action.target == self.robot_id:
                self.voter.apply_occupy(action.occupy)
            else:
                self._send(action.target, "zone_occupy", action.occupy)
            return
        if action.release is not None:
            if action.target == self.robot_id:
                self._apply_local_release(action.release, self.robot_id)
            else:
                self._send(action.target, "zone_release", action.release)
            return

    def _apply_local_release(self, body: ZoneReleaseBody, sender: str) -> None:
        outcome = self.voter.apply_release(body, sender)
        self._relay_release(body, outcome.relay_to)

    def _self_solicit(self, body: ZoneRequestBody) -> None:
        """The requester's own local voter runs in-process: no message, no delay.

        It is *not* pre-reserved. It is the first step of the same canonical walk
        everybody else takes, at its own position in the global order.
        """
        outcome = self.voter.solicit(body, self._now_ns)
        if outcome.grant is not None:
            self.requester.on_grant(self.robot_id, self.voter.to_wire(body, outcome.grant), self._now_ns)
            return
        refusal = outcome.refusal
        if refusal is not None:
            self.requester.on_refusal(refusal, self._now_ns)

    def _send(self, peer: str, kind: str, body: PeerMessageBodyT, correlation_id: str = "") -> None:
        envelope = PeerEnvelope(
            kind=kind,
            sender=self.robot_id,
            sender_session=self.session_id,
            run_id=self.membership.run_id,
            epoch=self.membership.epoch,
            seq=self._next_seq(),
            sent_at_ns=self._now_ns,
            time_domain=self.time_domain,
            correlation_id=correlation_id[:64],
        )
        self.outbox.append((peer, build_message(envelope, body)))

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _suspended_peers(self) -> tuple[str, ...]:
        required = set(self.voter.required_voters) - {self.robot_id}
        suspended = set(self.freshness.suspended_peers())
        return tuple(sorted(suspended.intersection(required)))

    def peer_permissions(self, peer_id: str) -> bool:
        entry = self.freshness.get(peer_id)
        return entry.usable if entry is not None else True


def _safety_unavailable(context: object) -> tuple[bool, str]:
    """Default safety hook: refuses rather than assuming a check happened."""
    del context
    return False, "no local safety gate was supplied to the coordinator"


def liveness_verdict(reason: str = "liveness_only_not_a_usable_claim") -> FreshnessVerdict:
    """The verdict shape used for heartbeats: liveness, never permission."""
    return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, reason)

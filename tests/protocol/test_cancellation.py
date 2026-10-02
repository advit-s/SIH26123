"""Cancellation, the late grant, duplicate/reordered delivery, and identity checks.

The required behaviour under test: **a grant that arrives after durable local
cancellation is ignored, creates no authority, and is answered so the peer's
record converges** (``AGENTS.md`` invariant 5).

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from niharamesh.coordination import BlockingClass, ZoneProtocol
from niharamesh.coordination.requester import LATE_GRANT_IGNORED, AdmissionContext
from niharamesh.coordination.voter import ZoneRecord
from niharamesh.domain.config import ProtocolTiming
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    PeerEnvelope,
    PeerMessage,
    ZoneGrantBody,
    ZoneOccupyBody,
    ZoneRequestBody,
    build_message,
)
from niharamesh.domain.identity import Membership
from niharamesh.domain.ids import digest_of
from niharamesh.domain.map import MapBoundary, Pose2, WarehouseMap, Zone, ZoneState
from niharamesh.domain.units import TimeDomain

RUN_ID = "run-1"
EPOCH = "e1"


class FakeJournal:
    """In-memory :class:`~niharamesh.ports.AuthorityJournal`."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.corrupt = False
        self.fail_append = False
        self._n = 0

    def append(self, record_type: str, payload: dict[str, object]) -> str:
        if self.corrupt or self.fail_append:
            return ""
        self._n += 1
        record_id = f"rec-{self._n:04d}"
        self.records.append({"record_id": record_id, "record_type": record_type, **payload})
        return record_id

    def read_all(self) -> list[dict[str, object]]:
        if self.corrupt:
            raise OSError("journal corrupt")
        return list(self.records)

    def latest(self, record_type: str) -> dict[str, object] | None:
        return next((r for r in reversed(self.records) if r["record_type"] == record_type), None)

    def mark_corrupt(self, reason: str) -> None:
        del reason
        self.corrupt = True

    @property
    def healthy(self) -> bool:
        return not self.corrupt

    def close(self) -> None:
        return None

    def of(self, record_type: str) -> list[dict[str, object]]:
        return [r for r in self.records if r["record_type"] == record_type]


def allow(_ctx: AdmissionContext) -> tuple[bool, str]:
    return True, "test_permits"


class Fleet:
    """A whole run in one process, with a controllable in-memory channel."""

    def __init__(
        self,
        robots: Sequence[str],
        zones: Sequence[str],
        *,
        timing: ProtocolTiming | None = None,
        safety_check: Callable[[AdmissionContext], tuple[bool, str]] | None = None,
        time_domain: TimeDomain = TimeDomain.LOGICAL,
    ) -> None:
        members = tuple(sorted(robots))
        self.membership = Membership(
            run_id=RUN_ID,
            epoch=EPOCH,
            members=members,
            digest=digest_of(RUN_ID, EPOCH, *members),
        )
        self.sessions = {r: f"{r}-s1" for r in members}
        self.zone_ids = tuple(zones)
        self.map = WarehouseMap(
            map_id="map-1",
            boundary=MapBoundary(min_x=0.0, min_y=-5.0, max_x=200.0, max_y=5.0),
            zones=tuple(
                Zone(
                    id=z,
                    protected_origin=(10.0 * i - 2.0, 0.0),
                    protected_extent=(4.0, 2.0),
                    entry_pose=Pose2(x=10.0 * i, y=-1.5, theta=0.0),
                    exit_pose=Pose2(x=10.0 * i, y=1.5, theta=0.0),
                )
                for i, z in enumerate(zones)
            ),
        )
        self.journals: dict[str, FakeJournal] = {}
        self.protocols: dict[str, ZoneProtocol] = {}
        self._seq: dict[str, int] = dict.fromkeys(members, 0)
        for robot_id in members:
            journal = FakeJournal()
            self.journals[robot_id] = journal
            protocol = ZoneProtocol(
                robot_id=robot_id,
                session_id=self.sessions[robot_id],
                membership=self.membership,
                journal=journal,
                warehouse_map=self.map,
                timing=timing,
                safety_check=safety_check if safety_check is not None else allow,
                time_domain=time_domain,
                session_registry=lambda rid: self.sessions.get(rid),
            )
            protocol.start()
            self.protocols[robot_id] = protocol
        self.inflight: list[tuple[str, PeerMessage]] = []
        self.now_ns = 0

    def __getitem__(self, robot_id: str) -> ZoneProtocol:
        return self.protocols[robot_id]

    def wire(
        self,
        sender: str,
        target: str,
        kind: str,
        body: object,
        *,
        seq: int | None = None,
        correlation_id: str = "",
        session: str | None = None,
        run_id: str = RUN_ID,
        epoch: str = EPOCH,
        protocol_version: str = "1.0.0",
        time_domain: TimeDomain = TimeDomain.LOGICAL,
    ) -> PeerMessage:
        """Build an arbitrary frame, for hostile and duplicated traffic."""
        if seq is None:
            self._seq[sender] = self._seq.get(sender, 0) + 1
            seq = self._seq[sender]
        envelope = PeerEnvelope(
            kind=kind,
            sender=sender,
            sender_session=session if session is not None else self.sessions[sender],
            run_id=run_id,
            epoch=epoch,
            seq=seq,
            sent_at_ns=self.now_ns,
            time_domain=time_domain,
            correlation_id=correlation_id,
        )
        return build_message(envelope, body)  # type: ignore[arg-type]

    def dispatch(self) -> None:
        for protocol in self.protocols.values():
            for target, message in protocol.outbox:
                self.inflight.append((target, message))
            protocol.outbox.clear()

    def deliver_next(self, drop: Callable[[PeerMessage], bool] | None = None) -> bool:
        if not self.inflight:
            return False
        target, message = self.inflight.pop(0)
        if drop is not None and drop(message):
            return True
        self.protocols[target].ingest(message)
        return True

    def deliver_all(self, drop: Callable[[PeerMessage], bool] | None = None) -> int:
        delivered = 0
        while self.deliver_next(drop=drop):
            delivered += 1
        return delivered

    def step(
        self,
        dt_ns: int = 5_000_000,
        *,
        ticking: Sequence[str] | None = None,
        drop: Callable[[PeerMessage], bool] | None = None,
    ) -> None:
        self.now_ns += dt_ns
        for robot_id, protocol in self.protocols.items():
            if ticking is not None and robot_id not in ticking:
                continue
            protocol.tick(self.now_ns)
        self.dispatch()
        self.deliver_all(drop=drop)

    def settle(
        self,
        rounds: int = 14,
        dt_ns: int = 5_000_000,
        *,
        ticking: Sequence[str] | None = None,
        drop: Callable[[PeerMessage], bool] | None = None,
    ) -> None:
        for _ in range(rounds):
            self.step(dt_ns, ticking=ticking, drop=drop)
            assert_invariants(self)

    def outstanding(self) -> list[tuple[str, ZoneRecord]]:
        return [
            (robot_id, record)
            for robot_id, protocol in self.protocols.items()
            for record in protocol.voter.outstanding_promises()
        ]

    def holders(self) -> dict[str, str]:
        by_zone: dict[str, set[str]] = {}
        for _voter, record in self.outstanding():
            by_zone.setdefault(record.zone_id, set()).add(record.requester)
        for zone_id, requesters in by_zone.items():
            if len(requesters) > 1:
                raise AssertionError(f"SPLIT GRANT: {zone_id} is promised to {sorted(requesters)}")
        return {zone: next(iter(rs)) for zone, rs in by_zone.items()}

    def executable_holder(self, zone_id: str) -> str | None:
        allowed = [r for r, p in self.protocols.items() if p.may_enter(zone_id)]
        assert len(allowed) <= 1, f"{zone_id} is executable by {sorted(allowed)}"
        return allowed[0] if allowed else None

    def may_enter(self, zone_id: str) -> bool:
        return self.executable_holder(zone_id) is not None


def assert_invariants(fleet: Fleet) -> None:
    per_zone: dict[str, set[str]] = {}
    per_requester: dict[str, set[str]] = {}
    for _voter, record in fleet.outstanding():
        per_zone.setdefault(record.zone_id, set()).add(record.requester)
        per_requester.setdefault(record.requester, set()).add(record.zone_id)
    for zone_id, requesters in per_zone.items():
        assert len(requesters) <= 1, f"{zone_id} promised to {sorted(requesters)}"
    for requester, zones in per_requester.items():
        assert len(zones) <= 1, f"{requester} holds grants for {sorted(zones)}"


def make_late_grant(fleet: Fleet, voter: str, request: ZoneRequestBody) -> PeerMessage:
    """Force a voter to issue a grant for a transaction that is already cancelled."""
    outcome = fleet[voter].voter.solicit(request, fleet.now_ns)
    assert outcome.grant is not None, "the late grant must actually be issued"
    assert outcome.grant is not None
    return fleet.wire(
        voter,
        request.requester,
        "zone_grant",
        fleet[voter].voter.to_wire(request, outcome.grant),
        correlation_id=request.txn,
    )


# --------------------------------------------------------------------- tests


def test_late_grant_after_durable_cancellation_is_ignored() -> None:
    """REQUIRED: a late grant is ignored, creates no authority, and is answered."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()
    assert fleet.holders() == {"z1": "r1"}

    # The owner cancels. Durability must land in the journal *before* anything
    # is emitted, which is why we inspect the journal before the next step.
    fleet["r1"].cancel("operator_abort")
    cancels = fleet.journals["r1"].of("cancel")
    assert cancels, "cancellation must be durable at the owner first"
    assert cancels[-1]["durably_non_executable"] is True
    assert cancels[-1]["reason"] == "operator_abort"

    acq = fleet["r1"].requester.active
    assert acq is not None and acq.phase in (
        AcquisitionPhase.CANCELLING,
        AcquisitionPhase.CANCELLED,
    )
    fleet.settle(rounds=4)
    assert fleet["r1"].requester.active is not None
    assert fleet["r1"].requester.active.phase is AcquisitionPhase.CANCELLED
    assert fleet.holders() == {}

    # Now the late grant arrives from r2, which had durably promised before the
    # cancel reached it.
    late = make_late_grant(fleet, "r2", acq.request)
    assert fleet["r2"].voter.state_of("z1") is ZoneState.PROMISED, (
        "the peer did issue the promise, so its record must exist"
    )
    fleet["r1"].ingest(late)

    events = [e.kind for e in fleet["r1"].events]
    assert LATE_GRANT_IGNORED in events, "the late grant must be recorded explicitly"

    acq = fleet["r1"].requester.active
    assert acq is not None
    assert acq.phase is not AcquisitionPhase.GRANTED
    assert acq.durably_non_executable is True
    assert "r2" in acq.late_granted
    assert "r2" not in acq.held(), "a late grant must never become authority"
    assert not fleet["r1"].may_enter("z1")
    assert fleet.executable_holder("z1") is None

    # The peer's record converges because the owner answers with a cancel.
    fleet.settle(rounds=6)
    assert fleet["r2"].voter.state_of("z1") is ZoneState.FREE
    assert fleet.holders() == {}
    assert not fleet["r1"].may_enter("z1")


def test_late_grant_never_revives_a_cancelled_transaction() -> None:
    """A second late grant is still ignored; the transaction stays dead."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()
    fleet["r1"].cancel("abort")
    fleet.settle(rounds=4)
    acq = fleet["r1"].requester.active
    assert acq is not None

    before = fleet.journals["r1"].of("cancel")
    for _ in range(3):
        late = make_late_grant(fleet, "r2", acq.request)
        fleet["r1"].ingest(late)
    fleet.settle(rounds=4)

    assert fleet["r1"].requester.active is acq
    assert acq.phase is not AcquisitionPhase.GRANTED
    assert not fleet.may_enter("z1")
    # No new durable cancellation was needed: the request was already dead.
    assert len(fleet.journals["r1"].of("cancel")) == len(before)
    assert fleet.holders() == {}


def test_cancellation_is_idempotent_in_cancel_seq() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    acq = fleet["r1"].requester.active
    assert acq is not None
    assert fleet["r2"].voter.state_of("z1") is ZoneState.PROMISED

    assert fleet["r1"].requester.cancel("abort", now_ns=fleet.now_ns) is True
    seq = acq.cancel_seq
    body = fleet["r1"].requester.cancel_body(acq)

    # The same cancel_seq, delivered repeatedly, converges on the same state.
    for _ in range(3):
        outcome = fleet["r2"].voter.apply_cancel(body)
        assert outcome.ack.cancel_seq == seq
        assert fleet["r2"].voter.state_of("z1") is ZoneState.FREE, (
            "a repeated cancel must not change the voter record again"
        )
    # A stale cancel_seq is answered, not treated as a new release.
    older = body.model_copy(update={"cancel_seq": max(1, seq - 1)})
    stale = fleet["r2"].voter.apply_cancel(older)
    assert stale.ack.cancel_seq == seq
    assert fleet["r2"].voter.state_of("z1") is ZoneState.FREE

    # A *new* attempt needs a new request_version: the old identity is dead.
    newer = acq.request.model_copy(update={"request_version": 2})
    assert fleet["r2"].voter.solicit(acq.request, fleet.now_ns).reason is not None
    assert fleet["r2"].voter.solicit(acq.request, fleet.now_ns).reason.value == ("request_version_replay")
    outcome = fleet["r2"].voter.solicit(newer, fleet.now_ns)
    assert outcome.grant is not None
    assert fleet["r2"].voter.state_of("z1") is ZoneState.PROMISED
    fresh_cancel = (
        fleet["r1"]
        .requester.cancel_body(acq)
        .model_copy(update={"cancel_seq": 50, "grant_id": newer.grant_id, "request_version": 2})
    )
    fleet["r2"].voter.apply_cancel(fresh_cancel)
    assert fleet["r2"].voter.state_of("z1") is ZoneState.FREE


def test_voter_refuses_to_release_an_occupied_zone_on_a_pre_entry_cancel() -> None:
    """Invariant 4: a pre-entry cancellation is not evidence of clearance."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert fleet["r1"].mark_entered("z1")
    fleet.settle(rounds=4)
    assert fleet["r1"].phase() is AcquisitionPhase.OCCUPIED

    # A forged pre-entry cancel from the owner must not free the aisle.
    acq = fleet["r1"].requester.active
    assert acq is not None
    forged = fleet["r1"].requester.cancel_body(acq).model_copy(update={"cancel_seq": 99})
    outcome = fleet["r2"].voter.apply_cancel(forged)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "protocol_violation"
    assert fleet["r2"].voter.state_of("z1") is ZoneState.OCCUPIED


def test_owner_refuses_cancellation_after_it_has_entered() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    assert fleet["r1"].mark_entered("z1")
    fleet.settle(rounds=2)
    assert fleet["r1"].phase() is AcquisitionPhase.OCCUPIED

    assert fleet["r1"].requester.cancel("too_late", now_ns=fleet.now_ns) is False
    kinds = [e.kind for e in fleet["r1"].events]
    assert "CANCEL_REFUSED_POST_ENTRY" in kinds
    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.OCCUPIED


def _prepare_traversal(fleet: Fleet) -> None:
    """Drive r1 all the way to ``OCCUPIED`` in a three-robot fleet."""
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert fleet["r1"].mark_entered("z1")
    fleet.settle(rounds=3)
    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.OCCUPIED


def test_duplicate_and_reordered_messages_are_idempotent() -> None:
    """Test 4: the final state is identical to one ordered delivery."""
    source = Fleet(["r1", "r2", "r3"], ["z1"])
    _prepare_traversal(source)
    source["r1"].release()
    source.dispatch()
    ordered = list(source.inflight)
    source.inflight.clear()
    assert ordered, "release traffic expected"
    assert {m.envelope.kind for _t, m in ordered} == {"zone_release"}

    # (a) every frame three times, in reverse order
    dup = Fleet(["r1", "r2", "r3"], ["z1"])
    _prepare_traversal(dup)
    for _ in range(3):
        for target, message in reversed(ordered):
            dup.protocols[target].ingest(message)
    dup.settle(rounds=6)
    duplicated = {r: p.voter.state_of("z1") for r, p in dup.protocols.items()}

    # (b) each frame once, in the order the owner emitted it
    single = Fleet(["r1", "r2", "r3"], ["z1"])
    _prepare_traversal(single)
    for target, message in ordered:
        single.protocols[target].ingest(message)
    single.settle(rounds=6)
    delivered_once = {r: p.voter.state_of("z1") for r, p in single.protocols.items()}

    assert duplicated == delivered_once
    assert duplicated == {"r1": ZoneState.FREE, "r2": ZoneState.FREE, "r3": ZoneState.FREE}
    assert dup.holders() == {}
    assert single.holders() == {}

    # An occupy frame replayed long after the release must not re-occupy it.
    stale_occupy = ZoneOccupyBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r1",
        requester_session="r1-s1",
        request_version=1,
        grant_id=ordered[0][1].body.grant_id,  # type: ignore[union-attr]
        occupancy_seq=1,
    )
    for robot_id in ("r1", "r2", "r3"):
        single.protocols[robot_id].ingest(single.wire("r1", robot_id, "zone_occupy", stale_occupy))
    single.settle(rounds=3)
    assert {r: p.voter.state_of("z1") for r, p in single.protocols.items()} == duplicated
    assert single.holders() == {}


def request_for(
    fleet: Fleet,
    requester: str,
    zone_id: str = "z1",
    version: int = 1,
    **overrides: object,
) -> ZoneRequestBody:
    """A well-formed request body owned by ``requester``."""
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "epoch": EPOCH,
        "zone_id": zone_id,
        "requester": requester,
        "requester_session": fleet.sessions[requester],
        "request_version": version,
        "movement": "forward",
        "entry_pose": (0.0, -1.5, 0.0),
        "exit_pose": (0.0, 1.5, 0.0),
        "expires_at_ns": 30_000_000_000,
        "time_domain": TimeDomain.LOGICAL,
        "membership_digest": fleet.membership.digest,
    }
    payload.update(overrides)
    return ZoneRequestBody(**payload)  # type: ignore[arg-type]


def test_wrong_identity_fields_are_refused_with_specific_reasons() -> None:
    """Test 5: each hostile field maps to its own RejectionReason."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    good = request_for(fleet, "r2")

    # 1. wrong protocol version on the envelope *and* the body
    bad = good.model_copy(update={"protocol_version": "9.9.9"})
    msg = fleet.wire("r2", "r1", "zone_request", bad, protocol_version="9.9.9")
    assert fleet["r1"].ingest(msg).reason.value == "protocol_mismatch"

    # 2. wrong schema version on the body
    msg = fleet.wire("r2", "r1", "zone_request", good.model_copy(update={"schema_version": "0.0.1"}))
    assert fleet["r1"].ingest(msg).reason.value == "schema_mismatch"

    # 3. wrong robot id: the sender is not an admitted member
    outsider = request_for(fleet, "r2").model_copy(update={"requester": "r9"})
    msg = fleet.wire("r9", "r1", "zone_request", outsider, session="r9-s1")
    assert fleet["r1"].ingest(msg).reason.value == "requester_not_admitted"

    # 4. wrong epoch
    msg = fleet.wire("r2", "r1", "zone_request", good, epoch="e2")
    assert fleet["r1"].ingest(msg).reason.value == "epoch_mismatch"

    # 5. wrong run
    msg = fleet.wire("r2", "r1", "zone_request", good, run_id="run-9")
    assert fleet["r1"].ingest(msg).reason.value == "protocol_mismatch"

    # 6. wrong shared-map / peer-set digest
    msg = fleet.wire("r2", "r1", "zone_request", good.model_copy(update={"membership_digest": "0" * 64}))
    assert fleet["r1"].ingest(msg).reason.value == "map_mismatch"

    # 7. wrong boot/session for the sender
    msg = fleet.wire("r2", "r1", "zone_request", good, session="r2-s0")
    assert fleet["r1"].ingest(msg).reason.value == "requester_session_stale"

    # 8. envelope sender does not match the body requester
    msg = fleet.wire("r3", "r1", "zone_request", good)
    assert fleet["r1"].ingest(msg).reason.value == "protocol_mismatch"

    # 9. request identity handling, judged by the voter itself
    fresh = Fleet(["r1", "r2", "r3"], ["z1"])
    v1 = request_for(fresh, "r2", version=1)
    assert fresh["r1"].ingest(fresh.wire("r2", "r1", "zone_request", v1, seq=10)).accepted
    assert fresh["r1"].voter.state_of("z1") is ZoneState.PROMISED

    # An identical re-solicitation is idempotent, never a second promise.
    outcome = fresh["r1"].ingest(fresh.wire("r2", "r1", "zone_request", v1, seq=11))
    assert outcome.accepted
    assert outcome.detail == "granted"
    assert fresh["r1"].voter.state_of("z1") is ZoneState.PROMISED

    # An older request version, after a newer one, is a request-version replay.
    replay_fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    newer = request_for(replay_fleet, "r2", version=2)
    assert replay_fleet["r1"].ingest(replay_fleet.wire("r2", "r1", "zone_request", newer, seq=20)).accepted
    older = request_for(replay_fleet, "r2", version=1)
    outcome = replay_fleet["r1"].ingest(replay_fleet.wire("r2", "r1", "zone_request", older, seq=21))
    assert outcome.reason is not None
    assert outcome.reason.value == "request_version_replay"

    # A brand new identity for the same zone is ordinary contention.
    v3 = request_for(fresh, "r3", version=1)
    outcome = fresh["r1"].ingest(fresh.wire("r3", "r1", "zone_request", v3, seq=13))
    assert outcome.reason is not None
    assert outcome.reason.value == "zone_promised"

    # 10. replayed envelope sequence, below the bounded replay window
    windowed = Fleet(["r1", "r2", "r3"], ["z1"])
    body = request_for(windowed, "r2", version=1)
    assert windowed["r1"].ingest(windowed.wire("r2", "r1", "zone_request", body, seq=1000)).accepted
    outcome = windowed["r1"].ingest(windowed.wire("r2", "r1", "zone_request", body, seq=1))
    assert outcome.reason is not None
    assert outcome.reason.value == "sequence_replay"
    # Replaying a bad sequence quarantines the sender for the rest of the run.
    assert "r2" in windowed["r1"].quarantined

    # A duplicate *inside* the window is an idempotent no-op, not a rejection.
    dup_fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    body = request_for(dup_fleet, "r2", version=1)
    assert dup_fleet["r1"].ingest(dup_fleet.wire("r2", "r1", "zone_request", body, seq=1000)).accepted
    outcome = dup_fleet["r1"].ingest(dup_fleet.wire("r2", "r1", "zone_request", body, seq=1000))
    assert outcome.accepted
    assert "duplicate" in outcome.detail
    assert dup_fleet["r1"].voter.state_of("z1") is ZoneState.PROMISED


def test_grant_addressed_to_the_wrong_requester_is_refused() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()
    acq = fleet["r1"].requester.active
    assert acq is not None

    forged = ZoneGrantBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r2",
        requester_session=fleet.sessions["r2"],
        request_version=1,
        grant_id=acq.request.grant_id,
        required_set_digest="0" * 64,
        persistence_record_id="rec-forged",
    )
    msg = fleet.wire("r2", "r1", "zone_grant", forged)
    outcome = fleet["r1"].ingest(msg)
    assert outcome.reason is not None
    assert outcome.reason.value == "protocol_violation"
    assert fleet.holders() == {"z1": "r1"}


def test_cancellation_reports_a_specific_blocking_class() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()
    fleet["r1"].cancel("abort")
    report = fleet["r1"].requester.blocking_report(fleet.now_ns)
    assert report.kind in (BlockingClass.PARTITION_STOP, BlockingClass.IDLE)
    assert not fleet["r1"].may_enter("z1")

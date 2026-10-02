"""Restart reconciliation, corrupt persistence and supervised fencing.

A promise a robot cannot re-derive from its own durable journal is not a promise
it may drop: a peer could still be moving on the strength of it. These tests pin
that down in both directions - a clean restart forgets nothing, and a corrupt
journal stops the robot instead of letting it resume voting.

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

from collections.abc import Sequence

from niharamesh.coordination import RecoveryState, ZoneProtocol
from niharamesh.coordination.requester import AdmissionContext
from niharamesh.coordination.voter import ZoneRecord
from niharamesh.domain.config import ProtocolTiming
from niharamesh.domain.coordination import (
    PeerEnvelope,
    PeerMessage,
    ZoneCancelBody,
    ZoneFenceBody,
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
    """In-memory :class:`~niharamesh.ports.AuthorityJournal`, backed by a list.

    ``restart()`` hands the *same record list* to a fresh object, which is what a
    real reboot does: the records are on disk, the process is not.
    """

    def __init__(self, records: list[dict[str, object]] | None = None) -> None:
        self.records: list[dict[str, object]] = records if records is not None else []
        self.corrupt = False
        self.fail_append = False
        self._n = len(self.records)

    def restart(self) -> FakeJournal:
        return FakeJournal(self.records)

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


def make_membership(robots: Sequence[str]) -> Membership:
    members = tuple(sorted(robots))
    return Membership(run_id=RUN_ID, epoch=EPOCH, members=members, digest=digest_of(RUN_ID, EPOCH, *members))


def make_map(zones: Sequence[str]) -> WarehouseMap:
    return WarehouseMap(
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


def make_protocol(
    robot_id: str,
    membership: Membership,
    sessions: dict[str, str],
    warehouse_map: WarehouseMap,
    journal: FakeJournal,
    *,
    timing: ProtocolTiming | None = None,
) -> ZoneProtocol:
    return ZoneProtocol(
        robot_id=robot_id,
        session_id=sessions[robot_id],
        membership=membership,
        journal=journal,
        warehouse_map=warehouse_map,
        timing=timing,
        safety_check=allow,
        session_registry=lambda rid: sessions.get(rid),
    )


def request_for(
    membership: Membership,
    sessions: dict[str, str],
    requester: str,
    zone_id: str = "z1",
    version: int = 1,
    epoch: str = EPOCH,
    **overrides: object,
) -> ZoneRequestBody:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "epoch": epoch,
        "zone_id": zone_id,
        "requester": requester,
        "requester_session": sessions[requester],
        "request_version": version,
        "movement": "forward",
        "entry_pose": (0.0, -1.5, 0.0),
        "exit_pose": (0.0, 1.5, 0.0),
        "expires_at_ns": 30_000_000_000,
        "time_domain": TimeDomain.LOGICAL,
        "membership_digest": membership.digest,
    }
    payload.update(overrides)
    return ZoneRequestBody(**payload)  # type: ignore[arg-type]


def frame(
    sender: str,
    sessions: dict[str, str],
    kind: str,
    body: object,
    seq: int,
    epoch: str = EPOCH,
) -> PeerMessage:
    envelope = PeerEnvelope(
        kind=kind,
        sender=sender,
        sender_session=sessions[sender],
        run_id=RUN_ID,
        epoch=epoch,
        seq=seq,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    return build_message(envelope, body)  # type: ignore[arg-type]


# --------------------------------------------------------------------- tests


def test_clean_restart_with_an_outstanding_promise_does_not_forget_it() -> None:
    """Test 6: the promise survives the reboot and is honoured again."""
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1", "z2"])
    journal = FakeJournal()

    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    assert r1.start() is RecoveryState.NORMAL
    body = request_for(membership, sessions, "r1")
    outcome = r1.voter.solicit(body, 0)
    assert outcome.grant is not None
    assert r1.voter.state_of("z1") is ZoneState.PROMISED
    original_record = outcome.grant.persistence_record_id

    # Reboot r1 with the same durable records.
    restarted = make_protocol("r1", membership, sessions, warehouse_map, journal.restart())
    assert restarted.start() is RecoveryState.RECONCILED
    assert restarted.recovery_state is RecoveryState.RECONCILED
    assert not restarted.degraded

    record = restarted.voter.record("z1")
    assert record is not None
    assert record.requester == "r1"
    assert record.grant_id == body.grant_id
    assert record.request_version == 1

    # (a) the original requester is honoured again, idempotently
    again = restarted.voter.solicit(body, 1_000)
    assert again.grant is not None
    assert again.grant.grant_id == body.grant_id
    assert again.grant.persistence_record_id == original_record
    assert again.duplicate is True

    # (b) a different requester is refused with ZONE_PROMISED, not forgotten
    other = restarted.voter.solicit(request_for(membership, sessions, "r2"), 2_000)
    assert other.refusal is not None
    assert other.refusal.reason.value == "zone_promised"
    assert other.refusal.blocking_requester == "r1"

    # (c) and the single-outstanding-grant rule is reported as GRANT_HELD
    second_zone = restarted.voter.solicit(request_for(membership, sessions, "r1", zone_id="z2"), 3_000)
    assert second_zone.refusal is not None
    assert second_zone.refusal.reason.value == "grant_held"
    assert second_zone.refusal.blocking_zone == "z1"


def test_restart_with_a_corrupt_journal_stops_and_grants_nothing() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1", "z2"])
    journal = FakeJournal()
    journal.mark_corrupt("simulated corruption")

    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    state = r1.start()
    assert state is RecoveryState.UNKNOWN_STOPPED
    assert r1.degraded is True
    assert r1.stopped is True

    for zone_id in ("z1", "z2"):
        outcome = r1.voter.solicit(request_for(membership, sessions, "r2", zone_id=zone_id), 0)
        assert outcome.refusal is not None
        assert outcome.refusal.reason.value == "not_ready"
        assert r1.voter.state_of(zone_id) is ZoneState.FREE

    assert "partition_stop" in r1.why_blocked("z1")
    assert r1.may_enter("z1") is False


def test_journal_failure_during_grant_produces_no_authority() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()

    journal.fail_append = True
    outcome = r1.voter.solicit(request_for(membership, sessions, "r2"), 0)
    assert outcome.grant is None
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "not_ready"
    assert r1.voter.state_of("z1") is ZoneState.FREE, "an unpersisted promise must not exist"
    assert r1.voter.outstanding_promises() == ()


def test_unattributable_journal_record_is_reported_corrupt_not_ignored() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    journal.records.append(
        {"record_id": "rec-x", "record_type": "promise", "requester": "r2", "grant_id": "g"}
    )
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    assert r1.start() is RecoveryState.UNKNOWN_STOPPED
    assert r1.degraded is True
    outcome = r1.voter.solicit(request_for(membership, sessions, "r2"), 0)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "not_ready"


def test_recovered_promise_survives_into_the_next_boot_too() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    r1.voter.solicit(request_for(membership, sessions, "r1"), 0)

    for _ in range(3):
        r1 = make_protocol("r1", membership, sessions, warehouse_map, journal.restart())
        assert r1.start() is RecoveryState.RECONCILED
        assert r1.voter.state_of("z1") is ZoneState.PROMISED

    # A newer request_version still cannot displace the outstanding promise.
    outcome = r1.voter.solicit(request_for(membership, sessions, "r2", version=5), 0)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "zone_promised"


def test_fencing_requires_operator_authorisation_and_blocks_the_zone() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    r1.voter.solicit(request_for(membership, sessions, "r1"), 0)
    assert r1.voter.state_of("z1") is ZoneState.PROMISED

    unauthorised = ZoneFenceBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        fenced_by="r2",
        reason="holder heartbeat lost",
        previous_holder="r1",
        operator_authorised=False,
    )
    outcome = r1.apply_fence(unauthorised)
    assert outcome.applied is False
    assert outcome.reason is not None
    assert outcome.reason.value == "protocol_violation"
    assert r1.voter.state_of("z1") is ZoneState.PROMISED, "an unauthorised fence changes nothing"

    authorised = unauthorised.model_copy(update={"operator_authorised": True})
    outcome = r1.apply_fence(authorised)
    assert outcome.applied is True
    assert r1.voter.state_of("z1") is ZoneState.FENCED

    details = r1.voter.fence_details("z1")
    assert details is not None
    assert details.fenced_by == "r2"
    assert details.previous_holder == "r1"
    assert details.operator_authorised is True
    assert details.fence_reason == "holder heartbeat lost"

    fenced = r1.fenced_zones()
    assert [z.zone_id for z in fenced] == ["z1"]

    # Every later solicitation is refused, and there is no force release.
    outcome = r1.voter.solicit(request_for(membership, sessions, "r3"), 1_000)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "zone_fenced"
    assert r1.voter.state_of("z1") is ZoneState.FENCED
    assert not hasattr(r1.voter, "force_release")
    assert not hasattr(r1, "force_release")

    # Fencing is idempotent, and it is journaled.
    again = r1.apply_fence(authorised)
    assert again.applied is True
    assert again.already_fenced is True
    assert journal.of("fence")


def test_fence_for_an_unknown_zone_is_refused() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    body = ZoneFenceBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="not-on-this-map",
        fenced_by="r2",
        reason="typo",
        operator_authorised=True,
    )
    outcome = r1.apply_fence(body)
    assert outcome.applied is False
    assert outcome.reason is not None
    assert outcome.reason.value == "protocol_mismatch"
    assert "unknown zone" in outcome.detail


def test_fenced_zone_is_reported_to_the_operator() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1", "z2"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    r1.voter.solicit(request_for(membership, sessions, "r1", zone_id="z1"), 0)
    r1.apply_fence(
        ZoneFenceBody(
            run_id=RUN_ID,
            epoch=EPOCH,
            zone_id="z1",
            fenced_by="r3",
            reason="holder process died inside the aisle",
            previous_holder="r1",
            previous_requester_session="r1-s1",
            operator_authorised=True,
        )
    )
    report = r1.why_blocked("z1")
    assert "blocked=zone_fenced" in report
    assert "holder process died inside the aisle" in report
    assert r1.voter.state_of("z2") is ZoneState.FREE


def test_restart_during_a_completed_transaction_is_clean() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    body = request_for(membership, sessions, "r1")
    r1.voter.solicit(body, 0)
    r1.voter.apply_cancel(
        ZoneCancelBody(
            run_id=RUN_ID,
            epoch=EPOCH,
            zone_id="z1",
            requester="r1",
            requester_session="r1-s1",
            request_version=1,
            grant_id=body.grant_id,
            cancel_seq=1,
            durably_non_executable=True,
            reason="operator_abort",
            time_domain=TimeDomain.LOGICAL,
        )
    )
    assert r1.voter.state_of("z1") is ZoneState.FREE

    rebooted = make_protocol("r1", membership, sessions, warehouse_map, journal.restart())
    assert rebooted.start() is RecoveryState.NORMAL, "nothing outstanding, nothing to reconcile"
    assert rebooted.voter.outstanding_promises() == ()
    records: list[ZoneRecord] = list(rebooted.voter.records())
    assert all(rec.state is not ZoneState.PROMISED for rec in records)


def test_a_stopped_robot_refuses_to_start_a_transaction() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    journal.mark_corrupt("simulated corruption")
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    assert r1.start() is RecoveryState.UNKNOWN_STOPPED

    r1.begin_acquire("z1")
    assert r1.requester.active is None, "a stopped robot must not start a walk"
    kinds = [event.kind for event in r1.events]
    assert "ACQUIRE_REFUSED_STOPPED" in kinds
    assert r1.voter.state_of("z1") is ZoneState.FREE
    assert r1.may_enter("z1") is False


def test_wrong_epoch_is_refused_on_every_zone_message() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    r1 = make_protocol("r1", membership, sessions, warehouse_map, journal)
    r1.start()
    stale = request_for(membership, sessions, "r2", epoch="e0")
    outcome = r1.ingest(frame("r2", sessions, "zone_request", stale, seq=1, epoch="e0"))
    assert outcome.reason is not None
    assert outcome.reason.value == "epoch_mismatch"
    assert r1.voter.state_of("z1") is ZoneState.FREE


def test_recovery_state_is_reported_not_silently_normal() -> None:
    membership = make_membership(["r1", "r2", "r3"])
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(["z1"])
    journal = FakeJournal()
    protocol = make_protocol("r1", membership, sessions, warehouse_map, journal)
    # Before boot the voter refuses to grant: an unreconciled robot is stopped.
    outcome = protocol.voter.solicit(request_for(membership, sessions, "r2"), 0)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "not_ready"
    assert protocol.stopped is True
    assert protocol.start() is RecoveryState.NORMAL
    assert protocol.stopped is False

"""Property-based state-machine test for the exclusive-zone protocol.

Complements ``tests/protocol/test_interleavings.py``: that file enumerates every
ordering of one fixed pool, this one generates arbitrary *sequences* of arbitrary
messages and asserts the same two invariants after every single delivery.

**This is a bounded search too.** Hypothesis finds counterexamples; it does not
prove the absence of one. The unbounded argument is in
``docs/protocol/ZONE_PROTOCOL.md`` section 6.

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from niharamesh.coordination import ZoneProtocol, detect_wait_for_cycle
from niharamesh.coordination.requester import AdmissionContext
from niharamesh.domain.coordination import (
    PeerEnvelope,
    PeerMessage,
    RejectionReason,
    ZoneCancelBody,
    ZoneFenceBody,
    ZoneGrantBody,
    ZoneOccupyBody,
    ZoneReleaseBody,
    ZoneRequestBody,
    build_message,
)
from niharamesh.domain.identity import Membership
from niharamesh.domain.ids import digest_of
from niharamesh.domain.map import MapBoundary, Pose2, WarehouseMap, Zone, ZoneState
from niharamesh.domain.units import TimeDomain

RUN_ID = "run-1"
EPOCH = "e1"
ROBOTS: tuple[str, ...] = ("r1", "r2", "r3")
ZONES: tuple[str, ...] = ("z1", "z2")
SESSIONS = {r: f"{r}-s1" for r in ROBOTS}
MEMBERSHIP = Membership(run_id=RUN_ID, epoch=EPOCH, members=ROBOTS, digest=digest_of(RUN_ID, EPOCH, *ROBOTS))
WAREHOUSE = WarehouseMap(
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
        for i, z in enumerate(ZONES)
    ),
)


class FakeJournal:
    """In-memory :class:`~niharamesh.ports.AuthorityJournal`."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self._n = 0

    def append(self, record_type: str, payload: dict[str, object]) -> str:
        self._n += 1
        record_id = f"rec-{self._n:04d}"
        self.records.append({"record_id": record_id, "record_type": record_type, **payload})
        return record_id

    def read_all(self) -> list[dict[str, object]]:
        return list(self.records)

    def latest(self, record_type: str) -> dict[str, object] | None:
        return next((r for r in reversed(self.records) if r["record_type"] == record_type), None)

    def mark_corrupt(self, reason: str) -> None:
        del reason

    @property
    def healthy(self) -> bool:
        return True

    def close(self) -> None:
        return None


def allow(_ctx: AdmissionContext) -> tuple[bool, str]:
    return True, "test_permits"


def fresh_fleet() -> dict[str, ZoneProtocol]:
    fleet: dict[str, ZoneProtocol] = {}
    for robot_id in ROBOTS:
        protocol = ZoneProtocol(
            robot_id=robot_id,
            session_id=SESSIONS[robot_id],
            membership=MEMBERSHIP,
            journal=FakeJournal(),
            warehouse_map=WAREHOUSE,
            safety_check=allow,
            session_registry=lambda rid: SESSIONS.get(rid),
        )
        protocol.start()
        fleet[robot_id] = protocol
    return fleet


def check_safety_invariants(fleet: dict[str, ZoneProtocol], context: str) -> None:
    """The invariants that must hold against *arbitrary*, including forged, traffic.

    S1. never two robots may enter the same zone.
    S2. a voter never owes the same requester promises for two zones.
    S3. the published wait-for graph is acyclic.

    S1 is the safety property. Note what is deliberately *absent*: that no zone is
    ever promised to two different robots somewhere in the fleet. A forged
    request - one that skips canonical index zero - can create exactly that split,
    because a voter cannot see what another voter promised and must not be told.
    The consequence is fail-stop: neither robot holds a complete grant set, so
    neither may enter. See ``docs/protocol/ZONE_PROTOCOL.md`` section 6.3.
    """
    executable: dict[str, set[str]] = {}
    for robot_id, protocol in fleet.items():
        for zone_id in ZONES:
            if protocol.may_enter(zone_id):
                executable.setdefault(zone_id, set()).add(robot_id)
    for zone_id, robots in executable.items():
        assert len(robots) <= 1, f"{context}: {zone_id} executable by {sorted(robots)}"

    per_voter_requester: dict[tuple[str, str], set[str]] = {}
    for robot_id, protocol in fleet.items():
        for record in protocol.voter.outstanding_promises():
            key = (robot_id, record.requester)
            per_voter_requester.setdefault(key, set()).add(record.zone_id)
    for (voter, requester), zones in per_voter_requester.items():
        assert len(zones) <= 1, f"{context}: {voter} owes {requester} promises for {sorted(zones)}"

    graph: dict[str, str] = {}
    for protocol in fleet.values():
        graph.update(protocol.wait_for_graph())
    assert detect_wait_for_cycle(graph) is None, f"{context}: wait-for cycle {graph}"


def check_conformance_invariants(fleet: dict[str, ZoneProtocol], context: str) -> None:
    """Adds the exclusivity that *conforming* traffic can never break.

    Every walk begins at canonical index zero, and that voter issues at most one
    promise per zone, so two conforming requesters can never both hold part of the
    same zone.
    """
    check_safety_invariants(fleet, context)
    per_zone: dict[str, set[str]] = {}
    for protocol in fleet.values():
        for record in protocol.voter.outstanding_promises():
            per_zone.setdefault(record.zone_id, set()).add(record.requester)
    for zone_id, requesters in per_zone.items():
        assert len(requesters) <= 1, f"{context}: {zone_id} promised to {sorted(requesters)}"


@settings(max_examples=50, deadline=None)
@given(
    first=st.sampled_from(ROBOTS),
    second=st.sampled_from(ZONES),
    third=st.sampled_from(ZONES),
)
def test_an_owner_never_starts_two_walks(first: str, second: str, third: str) -> None:
    """Invariant 6, owner side: one outstanding grant globally, per robot."""
    fleet = fresh_fleet()
    fleet[first].begin_acquire(second)
    with pytest.raises(RuntimeError, match="invariant 6"):
        fleet[first].begin_acquire(third)


def _request(requester: str, zone_id: str, version: int) -> ZoneRequestBody:
    return ZoneRequestBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=version,
        movement="forward",
        entry_pose=(0.0, -1.5, 0.0),
        exit_pose=(0.0, 1.5, 0.0),
        expires_at_ns=30_000_000_000,
        time_domain=TimeDomain.LOGICAL,
        membership_digest=MEMBERSHIP.digest,
    )


def _grant(requester: str, zone_id: str, version: int) -> ZoneGrantBody:
    body = _request(requester, zone_id, version)
    return ZoneGrantBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=version,
        grant_id=body.grant_id,
        required_set_digest="0" * 64,
        is_self_voter=False,
        persistence_record_id="rec-gen",
    )


def _cancel(requester: str, zone_id: str, version: int, seq: int) -> ZoneCancelBody:
    body = _request(requester, zone_id, version)
    return ZoneCancelBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=version,
        grant_id=body.grant_id,
        cancel_seq=seq,
        durably_non_executable=True,
        reason="generated",
        time_domain=TimeDomain.LOGICAL,
    )


def _occupy(requester: str, zone_id: str, version: int, seq: int) -> ZoneOccupyBody:
    body = _request(requester, zone_id, version)
    return ZoneOccupyBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=version,
        grant_id=body.grant_id,
        occupancy_seq=seq,
    )


def _release(requester: str, zone_id: str, version: int, seq: int) -> ZoneReleaseBody:
    body = _request(requester, zone_id, version)
    return ZoneReleaseBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=version,
        grant_id=body.grant_id,
        occupancy_seq=seq,
        release_seq=seq,
        asserts_full_clearance=True,
        time_domain=TimeDomain.LOGICAL,
    )


def _fence(zone_id: str, authorised: bool) -> ZoneFenceBody:
    return ZoneFenceBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        fenced_by="r2",
        reason="generated",
        previous_holder="r1",
        operator_authorised=authorised,
    )


def frame(sender: str, target: str, kind: str, body: object, seq: int) -> PeerMessage:
    envelope = PeerEnvelope(
        kind=kind,
        sender=sender,
        sender_session=SESSIONS[sender],
        run_id=RUN_ID,
        epoch=EPOCH,
        seq=seq,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
        correlation_id="nack:zone_promised" if kind == "zone_cancel_ack" else "",
    )
    return build_message(envelope, body)  # type: ignore[arg-type]


MESSAGE_KINDS = (
    "zone_request",
    "zone_grant",
    "zone_cancel",
    "zone_occupy",
    "zone_release",
    "zone_fence",
)


@st.composite
def op_strategy(draw: st.DrawFn) -> tuple[str, PeerMessage, str]:
    sender = draw(st.sampled_from(ROBOTS))
    target = draw(st.sampled_from(ROBOTS).filter(lambda r: r != sender))
    kind = draw(st.sampled_from(MESSAGE_KINDS))
    zone = draw(st.sampled_from(ZONES))
    version = draw(st.integers(min_value=1, max_value=3))
    seq = draw(st.integers(min_value=1, max_value=6))
    if kind == "zone_request":
        body: object = _request(sender, zone, version)
    elif kind == "zone_grant":
        body = _grant(sender, zone, version)
    elif kind == "zone_cancel":
        body = _cancel(sender, zone, version, draw(st.integers(min_value=1, max_value=3)))
    elif kind == "zone_occupy":
        body = _occupy(sender, zone, version, draw(st.integers(min_value=1, max_value=3)))
    elif kind == "zone_release":
        body = _release(sender, zone, version, draw(st.integers(min_value=1, max_value=3)))
    else:
        body = _fence(zone, draw(st.booleans()))
    return target, frame(sender, target, kind, body, seq), kind


@settings(
    max_examples=250,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(ops=st.lists(op_strategy(), min_size=1, max_size=24))
def test_arbitrary_message_sequences_preserve_both_invariants(
    ops: Sequence[tuple[str, str, PeerMessage]],
) -> None:
    fleet = fresh_fleet()
    for robot_id in ROBOTS:
        fleet[robot_id].begin_acquire("z1" if robot_id == "r1" else "z2")
    for protocol in fleet.values():
        protocol.tick(1_000_000)
    for protocol in fleet.values():
        protocol.outbox.clear()

    for index, (target, message, kind) in enumerate(ops):
        outcome = fleet[target].ingest(message)
        assert isinstance(outcome.accepted, bool)
        assert outcome.reason is None or isinstance(outcome.reason, RejectionReason)
        check_safety_invariants(fleet, f"op {index} kind {kind}")


@settings(max_examples=100, deadline=None)
@given(
    starts=st.lists(st.sampled_from(ROBOTS), min_size=1, max_size=3, unique=True),
    rounds=st.integers(min_value=1, max_value=6),
)
def test_concurrent_requests_never_produce_two_authorities(starts: Sequence[str], rounds: int) -> None:
    fleet = fresh_fleet()
    for robot_id in starts:
        fleet[robot_id].begin_acquire("z1")
    now = 0
    for _ in range(rounds):
        now += 5_000_000
        for protocol in fleet.values():
            protocol.tick(now)
        for protocol in fleet.values():
            for target, message in list(protocol.outbox):
                fleet[target].ingest(message)
            protocol.outbox.clear()
        check_conformance_invariants(fleet, f"round with {list(starts)}")
    holders: dict[str, set[str]] = {}
    for protocol in fleet.values():
        for record in protocol.voter.outstanding_promises():
            holders.setdefault(record.zone_id, set()).add(record.requester)
    for zone_id, requesters in holders.items():
        assert len(requesters) == 1, f"{zone_id} promised to {sorted(requesters)}"


@settings(max_examples=100, deadline=None)
@given(
    cancel_after_grants=st.booleans(),
    keep_soliciting=st.booleans(),
)
def test_cancellation_never_leaves_a_second_authority(
    cancel_after_grants: bool, keep_soliciting: bool
) -> None:
    fleet = fresh_fleet()
    fleet["r2"].begin_acquire("z1")
    now = 0
    for _ in range(6):
        now += 5_000_000
        for protocol in fleet.values():
            protocol.tick(now)
        for protocol in fleet.values():
            for target, message in list(protocol.outbox):
                fleet[target].ingest(message)
            protocol.outbox.clear()
    check_conformance_invariants(fleet, "before cancel")
    if cancel_after_grants:
        fleet["r2"].cancel("generated_cancel")
    if keep_soliciting:
        fleet["r3"].begin_acquire("z1")
    for _ in range(6):
        now += 5_000_000
        for protocol in fleet.values():
            protocol.tick(now)
        for protocol in fleet.values():
            for target, message in list(protocol.outbox):
                fleet[target].ingest(message)
            protocol.outbox.clear()
        check_conformance_invariants(fleet, "after cancel")
    assert fleet["r2"].requester.held_grants <= len(ROBOTS)
    records = [record for protocol in fleet.values() for record in protocol.voter.records()]
    for record in records:
        assert record.state is not ZoneState.FENCED or record.fenced_by is not None


def test_a_forged_request_can_split_a_zone_and_the_result_is_fail_stop() -> None:
    """Documented consequence, asserted rather than hidden.

    A request that skips canonical index zero lets a second robot hold part of a
    zone another robot already holds elsewhere. The split is *liveness*, not
    safety: neither robot can assemble the complete grant set, so neither may
    enter, and the zone stays blocked until the forged records are fenced.
    """
    fleet = fresh_fleet()
    fleet["r1"].begin_acquire("z1")
    for protocol in fleet.values():
        protocol.tick(1_000_000)
    for protocol in fleet.values():
        protocol.outbox.clear()
    assert fleet["r1"].voter.state_of("z1") is ZoneState.PROMISED

    # r3 forges r2's request for the same zone and delivers it straight to r3.
    forged = _request("r2", "z1", 1)
    fleet["r3"].ingest(frame("r2", "r3", "zone_request", forged, 700))
    assert fleet["r3"].voter.state_of("z1") is ZoneState.PROMISED

    # The split exists ...
    promised_to = {
        protocol.robot_id: sorted({rec.requester for rec in protocol.voter.records()})
        for protocol in fleet.values()
        if protocol.voter.records()
    }
    assert promised_to.get("r1") == ["r1"], promised_to
    assert promised_to.get("r3") == ["r2"], promised_to
    # ... and is fail-stop: nobody may enter.
    for robot_id, protocol in fleet.items():
        assert protocol.may_enter("z1") is False, robot_id
    check_safety_invariants(fleet, "after forged split")

    # The only documented escape is an operator-authorised fence.
    fleet["r3"].apply_fence(_fence("z1", authorised=True))
    assert fleet["r3"].voter.state_of("z1") is ZoneState.FENCED
    outcome = fleet["r3"].voter.solicit(_request("r2", "z1", 2), 2_000_000)
    assert outcome.refusal is not None
    assert outcome.refusal.reason.value == "zone_fenced"
    check_safety_invariants(fleet, "after fence")


def test_a_zone_record_is_never_freed_by_a_timer() -> None:
    """Sanity anchor: occupancy survives an unbounded amount of logical time."""
    fleet = fresh_fleet()
    fleet["r1"].begin_acquire("z1")
    now = 0
    for _ in range(14):
        now += 5_000_000
        for protocol in fleet.values():
            protocol.tick(now)
        for protocol in fleet.values():
            for target, message in list(protocol.outbox):
                fleet[target].ingest(message)
            protocol.outbox.clear()
    assert fleet["r1"].mark_entered("z1")
    now += 5_000_000
    for protocol in fleet.values():
        protocol.tick(now)
    # The release is never sent and the robots are never ticked again: no record
    # may become FREE, whatever the elapsed logical time.
    for record in (protocol.voter.record("z1") for protocol in fleet.values()):
        assert record is None or record.state in (ZoneState.PROMISED, ZoneState.OCCUPIED)
    assert fleet["r1"].requester.held_grants == len(ROBOTS)

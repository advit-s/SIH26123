"""Bounded exhaustive interleavings of the zone protocol.

**Bound.** Two requesters, two voters (``r1``, ``r2``), two zones (``z1``,
``z2``). A pool of exactly **six** distinct frames is permuted exhaustively: all
``6! = 720`` orderings are enumerated, and the invariants are re-checked after
every prefix of every ordering. Checking all prefixes of all permutations is the
same thing as enumerating *every* ordering of *every* subset of the pool.

**This is not an unbounded proof.** It is evidence over one fixed message pool in
one small topology. It shows the two safety invariants survive arbitrary
reordering and premature delivery of those frames; it does not show they hold
for all possible messages, all schedules, all faults or all topologies. The
unbounded argument lives in ``docs/protocol/ZONE_PROTOCOL.md`` section 6 and
``docs/adr/0003-single-outstanding-grant.md``.

The invariants:

A. never two robots simultaneously hold authority over the same zone;
B. never a robot holds two outstanding grants, globally, across all zones.

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from niharamesh.coordination import ZoneProtocol, detect_wait_for_cycle
from niharamesh.coordination.requester import AdmissionContext
from niharamesh.coordination.voter import ZoneRecord, required_set_digest
from niharamesh.domain.coordination import (
    PeerEnvelope,
    PeerMessage,
    ZoneCancelBody,
    ZoneFenceBody,
    ZoneGrantBody,
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
POOL_SIZE = 6
PERMUTATIONS = 720
ROBOTS: tuple[str, ...] = ("r1", "r2")
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
ZONE_KINDS = {
    "zone_request",
    "zone_grant",
    "zone_cancel",
    "zone_cancel_ack",
    "zone_occupy",
    "zone_release",
    "zone_fence",
}


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
    """Two requesters / two voters, both mid-acquisition, outboxes cleared."""
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
    fleet["r1"].begin_acquire("z1")
    fleet["r2"].begin_acquire("z2")
    for protocol in fleet.values():
        protocol.tick(1_000_000)
    for protocol in fleet.values():
        protocol.outbox.clear()
    return fleet


def request_body(requester: str, zone_id: str) -> ZoneRequestBody:
    return ZoneRequestBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id=zone_id,
        requester=requester,
        requester_session=SESSIONS[requester],
        request_version=1,
        movement="forward",
        entry_pose=(0.0, -1.5, 0.0),
        exit_pose=(0.0, 1.5, 0.0),
        expires_at_ns=30_000_000_000,
        time_domain=TimeDomain.LOGICAL,
        membership_digest=MEMBERSHIP.digest,
    )


def correct_digest(requester: str, zone_id: str) -> str:
    return required_set_digest(
        RUN_ID,
        EPOCH,
        zone_id,
        requester,
        SESSIONS[requester],
        1,
        ROBOTS,
        SESSIONS,
    )


def frame(sender: str, target: str, kind: str, body: object, seq: int) -> tuple[str, PeerMessage]:
    envelope = PeerEnvelope(
        kind=kind,
        sender=sender,
        sender_session=SESSIONS[sender],
        run_id=RUN_ID,
        epoch=EPOCH,
        seq=seq,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    return (target, build_message(envelope, body))  # type: ignore[arg-type]


def build_pool() -> list[tuple[str, PeerMessage]]:
    """Six distinct frames: the ones whose order can change what is reachable.

    Two competing requests, the grant that completes the first walk, a pre-entry
    cancel, a release and an authorised fence. Occupancy declarations are covered
    by the other protocol tests; the pool stays at six so ``6! = 720`` orderings
    remain exhaustive and affordable.
    """
    r1_z1 = request_body("r1", "z1")
    r2_z2 = request_body("r2", "z2")

    grant = ZoneGrantBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r1",
        requester_session=SESSIONS["r1"],
        request_version=1,
        grant_id=r1_z1.grant_id,
        required_set_digest=correct_digest("r1", "z1"),
        is_self_voter=False,
        persistence_record_id="rec-pool-grant",
    )
    cancel = ZoneCancelBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r1",
        requester_session=SESSIONS["r1"],
        request_version=1,
        grant_id=r1_z1.grant_id,
        cancel_seq=1,
        durably_non_executable=True,
        reason="pool_cancel",
        time_domain=TimeDomain.LOGICAL,
    )
    release = ZoneReleaseBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r1",
        requester_session=SESSIONS["r1"],
        request_version=1,
        grant_id=r1_z1.grant_id,
        occupancy_seq=1,
        release_seq=1,
        asserts_full_clearance=True,
        time_domain=TimeDomain.LOGICAL,
    )
    fence = ZoneFenceBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        fenced_by="r2",
        reason="pool_fence",
        previous_holder="r1",
        operator_authorised=True,
    )
    pool = [
        frame("r1", "r2", "zone_request", r1_z1, 1),
        frame("r2", "r1", "zone_request", r2_z2, 1),
        frame("r2", "r1", "zone_grant", grant, 2),
        frame("r1", "r2", "zone_cancel", cancel, 2),
        frame("r1", "r2", "zone_release", release, 3),
        frame("r2", "r1", "zone_fence", fence, 3),
    ]
    assert len(pool) == POOL_SIZE, f"pool must hold exactly {POOL_SIZE} frames, got {len(pool)}"
    return pool


POOL = build_pool()
ORDERINGS: tuple[tuple[int, ...], ...] = tuple(itertools.permutations(range(POOL_SIZE)))


def check_invariants(fleet: dict[str, ZoneProtocol], context: str) -> None:
    """A: one authority per zone. B: one outstanding grant per robot."""
    per_zone: dict[str, set[str]] = {}
    per_requester: dict[str, set[str]] = {}
    for protocol in fleet.values():
        for record in protocol.voter.outstanding_promises():
            per_zone.setdefault(record.zone_id, set()).add(record.requester)
            per_requester.setdefault(record.requester, set()).add(record.zone_id)
    for zone_id, requesters in per_zone.items():
        assert len(requesters) <= 1, f"{context}: {zone_id} promised to {sorted(requesters)}"
    for requester, zones in per_requester.items():
        assert len(zones) <= 1, f"{context}: {requester} holds grants for {sorted(zones)}"

    graph: dict[str, str] = {}
    for protocol in fleet.values():
        graph.update(protocol.wait_for_graph())
    assert detect_wait_for_cycle(graph) is None, f"{context}: wait-for cycle {graph}"


def deliver(permutation: Sequence[int]) -> dict[str, ZoneProtocol]:
    fleet = fresh_fleet()
    for index in permutation:
        target, message = POOL[index]
        fleet[target].ingest(message)
    return fleet


def test_bound_is_stated_and_is_not_an_unbounded_proof() -> None:
    assert POOL_SIZE == 6
    assert len(ORDERINGS) == PERMUTATIONS == 720
    assert len(set(ORDERINGS)) == PERMUTATIONS
    # Checking every prefix of every ordering covers every ordering of every subset.
    total_prefixes = sum(len(o) for o in ORDERINGS)
    assert total_prefixes == PERMUTATIONS * POOL_SIZE == 4320


def test_pool_covers_the_six_most_reachable_frames() -> None:
    kinds = {m.envelope.kind for _t, m in POOL}
    assert kinds == {
        "zone_request",
        "zone_grant",
        "zone_cancel",
        "zone_release",
        "zone_fence",
    }
    assert kinds < ZONE_KINDS, "occupancy and ack frames are covered elsewhere"
    assert {m.envelope.sender for _t, m in POOL} == {"r1", "r2"}


def test_all_permutations_preserve_both_invariants_at_every_prefix() -> None:
    checked = 0
    for permutation in ORDERINGS:
        fleet = fresh_fleet()
        label = "|".join(POOL[i][1].envelope.kind for i in permutation)
        check_invariants(fleet, f"start {label}")
        for step, index in enumerate(permutation):
            target, message = POOL[index]
            fleet[target].ingest(message)
            checked += 1
            check_invariants(fleet, f"{label} step {step}")
            for protocol in fleet.values():
                for _peer, out in protocol.outbox:
                    assert out.envelope.kind in ZONE_KINDS, out.envelope.kind
    assert checked == 4320


def test_no_permutation_leaves_two_authorities_for_one_zone() -> None:
    """A, asserted directly over every complete ordering."""
    for permutation in ORDERINGS:
        fleet = deliver(permutation)
        holders: dict[str, set[str]] = {}
        for protocol in fleet.values():
            for record in protocol.voter.outstanding_promises():
                holders.setdefault(record.zone_id, set()).add(record.requester)
        for zone_id, requesters in holders.items():
            assert len(requesters) == 1, (
                f"{zone_id} has {sorted(requesters)} after {[POOL[i][1].envelope.kind for i in permutation]}"
            )


def test_no_permutation_gives_one_robot_two_zones() -> None:
    """B, asserted directly over every complete ordering."""
    for permutation in ORDERINGS:
        fleet = deliver(permutation)
        by_requester: dict[str, set[str]] = {}
        for protocol in fleet.values():
            for record in protocol.voter.outstanding_promises():
                by_requester.setdefault(record.requester, set()).add(record.zone_id)
        for requester, zones in by_requester.items():
            assert len(zones) == 1, f"{requester} holds {sorted(zones)}"


def test_ordered_delivery_reaches_a_clean_terminal_state() -> None:
    """The pool, delivered in build order, exercises grant -> cancel -> fence."""
    fleet = fresh_fleet()
    for target, message in POOL:
        fleet[target].ingest(message)
        check_invariants(fleet, f"ordered {message.envelope.kind}")
    # The authorised fence is terminal for the epoch at every voter that saw it.
    assert fleet["r1"].voter.state_of("z1") is ZoneState.FENCED
    details = fleet["r1"].voter.fence_details("z1")
    assert details is not None
    assert details.previous_holder == "r1"
    # r2's voter released the cancelled promise and holds nothing for z1.
    assert fleet["r2"].voter.state_of("z1") is ZoneState.FREE
    assert fleet["r2"].voter.promised_zones_for("r1") == ()
    assert "zone_fenced" in fleet["r1"].why_blocked("z1")


def test_a_forged_digest_is_refused_and_cancelled_not_granted() -> None:
    """A wrong required-set digest never becomes entry permission."""
    fleet = fresh_fleet()
    forged = ZoneGrantBody(
        run_id=RUN_ID,
        epoch=EPOCH,
        zone_id="z1",
        requester="r1",
        requester_session=SESSIONS["r1"],
        request_version=1,
        grant_id=request_body("r1", "z1").grant_id,
        required_set_digest="0" * 64,
        is_self_voter=False,
        persistence_record_id="rec-forged",
    )
    target, message = frame("r2", "r1", "zone_grant", forged, 900)
    fleet[target].ingest(message)
    kinds = [event.kind for event in fleet["r1"].events]
    assert "GRANT_SET_DIGEST_MISMATCH" in kinds
    assert fleet["r1"].may_enter("z1") is False
    assert fleet["r1"].requester.active is not None
    assert fleet["r1"].requester.active.durably_non_executable is True


def records(fleet: dict[str, ZoneProtocol]) -> list[ZoneRecord]:
    out: list[ZoneRecord] = []
    for protocol in fleet.values():
        out.extend(protocol.voter.records())
    return out

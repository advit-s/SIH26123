"""Happy-path acquisition, owner crash points and progress.

The harness at the top of this file is local and in-memory on purpose: the
protocol tests must not depend on the transport or persistence workstreams, so
there is no socket, no event loop and no file anywhere in this suite.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import pytest

from niharamesh.coordination import BlockingClass, ZoneProtocol
from niharamesh.coordination.requester import LATE_GRANT_IGNORED, AdmissionContext
from niharamesh.coordination.voter import ZoneRecord
from niharamesh.domain.config import ProtocolTiming
from niharamesh.domain.coordination import AcquisitionPhase, PeerMessage
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


def veto(_ctx: AdmissionContext) -> tuple[bool, str]:
    return False, "test_vetoes"


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
            # Boot: re-derive outstanding promises before granting anything.
            protocol.start()
            self.protocols[robot_id] = protocol
        self.inflight: list[tuple[str, PeerMessage]] = []
        self.now_ns = 0

    def __getitem__(self, robot_id: str) -> ZoneProtocol:
        return self.protocols[robot_id]

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
        """``zone_id -> requester``. Raises if one zone has two distinct holders."""
        by_zone: dict[str, set[str]] = {}
        for _voter, record in self.outstanding():
            by_zone.setdefault(record.zone_id, set()).add(record.requester)
        for zone_id, requesters in by_zone.items():
            if len(requesters) > 1:
                raise AssertionError(f"SPLIT GRANT: {zone_id} is promised to {sorted(requesters)}")
        return {zone: next(iter(rs)) for zone, rs in by_zone.items()}

    def executable_holder(self, zone_id: str) -> str | None:
        """The single robot permitted to enter ``zone_id``, if any."""
        allowed = [robot_id for robot_id, p in self.protocols.items() if p.may_enter(zone_id)]
        assert len(allowed) <= 1, f"{zone_id} is executable by {sorted(allowed)}"
        return allowed[0] if allowed else None

    def may_enter(self, zone_id: str) -> bool:
        return self.executable_holder(zone_id) is not None


def assert_invariants(fleet: Fleet) -> None:
    """A. one authority per zone. B. one outstanding grant per robot, globally."""
    per_zone: dict[str, set[str]] = {}
    for _voter, record in fleet.outstanding():
        per_zone.setdefault(record.zone_id, set()).add(record.requester)
    for zone_id, requesters in per_zone.items():
        assert len(requesters) <= 1, f"{zone_id} promised to {sorted(requesters)}"

    per_requester: dict[str, set[str]] = {}
    for _voter, record in fleet.outstanding():
        per_requester.setdefault(record.requester, set()).add(record.zone_id)
    for requester, zones in per_requester.items():
        assert len(zones) <= 1, f"{requester} holds grants for {sorted(zones)}"


def acquire_and_enter(fleet: Fleet, robot_id: str, zone_id: str, *, rounds: int = 14) -> None:
    fleet[robot_id].begin_acquire(zone_id)
    fleet.settle(rounds=rounds)
    assert fleet[robot_id].phase() is AcquisitionPhase.GRANTED
    assert fleet.may_enter(zone_id)
    assert fleet[robot_id].mark_entered(zone_id)
    fleet.settle(rounds=4)


# --------------------------------------------------------------------- tests


def test_three_requesters_one_zone_exactly_one_wins() -> None:
    """Test 1: one winner, the others explicitly refused, never a timeout."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    for robot_id in ("r1", "r2", "r3"):
        fleet[robot_id].begin_acquire("z1")
    fleet.settle(rounds=8)

    assert fleet.holders() == {"z1": "r1"}
    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert fleet.may_enter("z1")
    for loser in ("r2", "r3"):
        assert fleet[loser].phase() is AcquisitionPhase.REJECTED, (
            "the losing attempt must end, not wait for a timeout"
        )
        assert fleet[loser].requester.last_rejection is not None
        assert fleet[loser].requester.retry_at_ns > 0

    # The losers were refused with a specific reason, before any timer expired.
    for loser in ("r2", "r3"):
        rejection = fleet[loser].requester.last_rejection
        assert rejection is not None, f"{loser} was not given a reason"
        assert rejection.reason.value == "zone_promised"
        assert rejection.detail  # never a bare timeout

    # The refusal is durable at the refusing voter: that is the authoritative record.
    refusal = fleet["r1"].last_refusal("z1")
    assert refusal is not None
    assert refusal.reason.value == "zone_promised"
    assert fleet.journals["r1"].of("refusal"), "the refusal must be journaled"

    assert not fleet["r2"].may_enter("z1")
    assert not fleet["r3"].may_enter("z1")


def test_winner_traverses_and_releases_zone() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    acquire_and_enter(fleet, "r1", "z1")

    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.OCCUPIED, (
            "occupancy must be retained at every voter"
        )
    assert fleet.holders() == {"z1": "r1"}

    fleet["r1"].release()
    fleet.settle(rounds=6)

    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.FREE
    assert fleet.holders() == {}


def test_admission_requires_the_complete_exact_grant_set_and_digest() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=2)

    acq = fleet["r1"].requester.active
    assert acq is not None
    assert len(acq.held()) < len(fleet["r1"].required_voters("r1"))
    assert not fleet.may_enter("z1")
    assert fleet["r1"].requester.blocking_report(fleet.now_ns).kind is (BlockingClass.PARTIAL_ACQUISITION)

    fleet.settle(rounds=10)
    assert fleet.may_enter("z1")

    # The advertised digest is exactly the locally computed one.
    computed = fleet["r1"].requester.compute_digest(acq)
    assert set(acq.digests()) == {computed}
    assert fleet["r1"].required_set_digest("r1", "z1") != ""


def test_local_safety_gate_can_veto_entry() -> None:
    fleet = Fleet(["r1", "r2"], ["z1"], safety_check=veto)
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)

    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert not fleet.may_enter("z1")
    assert fleet["r1"].requester.blocking_report(fleet.now_ns).kind is BlockingClass.SAFETY_GATE
    assert "test_vetoes" in fleet["r1"].why_blocked("z1")
    # A grant set that exists is not a licence to move.
    assert not fleet["r1"].mark_entered("z1")


def test_owner_crash_before_all_responses_is_safe_and_explainable() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1", "z2"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()  # one solicitation only
    fleet.dispatch()
    fleet.deliver_all()

    acq = fleet["r1"].requester.active
    assert acq is not None and acq.held(), "r1 should hold a partial set"
    assert fleet["r1"].phase() is AcquisitionPhase.ACQUIRING

    # r1 dies here. Nothing moves.
    fleet.settle(rounds=40, ticking=["r2", "r3"])

    for robot_id in ("r1", "r2", "r3"):
        assert not fleet[robot_id].may_enter("z1")
    assert fleet.holders() == {"z1": "r1"}
    assert fleet["r1"].why_blocked("z1")
    # Recovery is the operator's explicit fence, never a timer.
    assert fleet["r1"].voter.state_of("z1") is ZoneState.PROMISED
    assert LATE_GRANT_IGNORED not in [e.kind for e in fleet["r1"].events]


def test_owner_crash_after_admission_before_entry() -> None:
    fleet = Fleet(["r1", "r2"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert fleet.may_enter("z1")

    # r1 dies before declaring occupancy. r2 must not be able to enter.
    fleet["r2"].begin_acquire("z1")
    fleet.settle(rounds=8, ticking=["r2"])

    assert fleet.holders() == {"z1": "r1"}
    assert fleet["r2"].requester.last_rejection is not None
    assert fleet["r2"].requester.last_rejection.reason.value == "zone_promised"
    assert not fleet["r2"].may_enter("z1")
    assert fleet.executable_holder("z1") == "r1"
    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.PROMISED


def test_owner_crash_inside_a_zone_retains_occupancy() -> None:
    fleet = Fleet(["r1", "r2"], ["z1"])
    acquire_and_enter(fleet, "r1", "z1")

    fleet.settle(rounds=60, ticking=["r2"])

    for protocol in fleet.protocols.values():
        assert protocol.voter.state_of("z1") is ZoneState.OCCUPIED, (
            "a silent robot is still physically in the aisle"
        )
    assert fleet.holders() == {"z1": "r1"}
    assert fleet["r1"].phase() is AcquisitionPhase.OCCUPIED


def test_owner_crash_after_exit_before_release() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    acquire_and_enter(fleet, "r1", "z1")

    # r1 exits, but its release to r2 is lost for good.
    def drop_release_to_r2(message: PeerMessage) -> bool:
        return message.envelope.kind == "zone_release" and message.envelope.sender == "r1"

    fleet["r1"].release()
    for _ in range(6):
        fleet.step(drop=drop_release_to_r2)

    # No timer, no majority vote: r2 never reconciled, so nobody is free.
    for robot_id, protocol in fleet.protocols.items():
        assert protocol.voter.state_of("z1") is ZoneState.OCCUPIED, (
            f"{robot_id} freed the zone without a fully reconciled release"
        )
    assert fleet.holders() == {"z1": "r1"}

    # A later requester is blocked with an explicit reason, not a timeout.
    fleet["r3"].begin_acquire("z1")
    fleet.settle(rounds=6, drop=drop_release_to_r2)
    refusal = fleet["r3"].requester.last_rejection
    assert refusal is not None
    assert refusal.reason.value == "zone_promised"
    assert not fleet["r3"].may_enter("z1")

    # The documented recovery is an operator-authorised fence, never a force release.
    assert not hasattr(fleet.protocols["r2"], "force_release")
    assert fleet["r2"].voter.state_of("z1") is not ZoneState.FENCED


def test_progress_a_queued_requester_eventually_acquires_and_traverses() -> None:
    """Test 11: bounded progress under healthy, reliable conditions."""
    timing = ProtocolTiming(solicit_timeout_s=0.02, cancel_timeout_s=0.05, release_timeout_s=0.05)
    fleet = Fleet(["r1", "r2", "r3"], ["z1"], timing=timing)
    traversals: list[str] = []

    bound = 600
    for _ in range(bound):
        for robot_id in ("r1", "r2", "r3"):
            protocol = fleet[robot_id]
            acq = protocol.requester.active
            if acq is None:
                if protocol.requester.last_rejection is None or protocol.requester.retry_due(fleet.now_ns):
                    protocol.begin_acquire("z1")
            elif acq.phase is AcquisitionPhase.GRANTED and protocol.may_enter("z1"):
                assert protocol.mark_entered("z1")
                traversals.append(robot_id)
            elif acq.phase is AcquisitionPhase.OCCUPIED:
                protocol.release()
        fleet.step(dt_ns=1_000_000)
        assert_invariants(fleet)
        if len(traversals) >= 6:
            break

    assert traversals, "no robot traversed within the step bound"
    assert len(set(traversals)) == 3, f"only {sorted(set(traversals))} traversed within {bound} steps"


def test_why_blocked_names_the_class_request_and_resource() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=2)
    fleet["r2"].begin_acquire("z1")
    fleet.settle(rounds=4)

    report = fleet["r2"].requester.blocking_report(fleet.now_ns)
    assert report.kind is BlockingClass.HEALTHY_CONTENTION
    text = fleet["r2"].why_blocked("z1")
    assert "blocked=healthy_contention" in text
    assert "blocking_peer=r1" in text, "the refusing voter must be named"
    assert "blocking_resource=z1" in text
    # The blocking *transaction* id is known only to the refusing voter, and is
    # readable there from its own durable record - never from another robot.
    refusal = fleet["r1"].last_refusal("z1")
    assert refusal is not None and refusal.blocking_grant_id


def test_missing_safety_gate_is_reported_not_assumed() -> None:
    fleet = Fleet(["r1", "r2"], ["z1"], safety_check=veto)
    fleet["r1"].begin_acquire("z1")
    fleet.settle(rounds=12)
    # Even a fully granted robot reports the veto instead of silently entering.
    assert "safety_gate" in fleet["r1"].why_blocked("z1")


def test_second_concurrent_acquisition_is_refused_locally() -> None:
    """Invariant 6, requester side: one outstanding grant globally."""
    fleet = Fleet(["r1", "r2"], ["z1", "z2"])
    fleet["r1"].begin_acquire("z1")
    fleet.step()
    with pytest.raises(RuntimeError, match="invariant 6"):
        fleet["r1"].begin_acquire("z2")

"""Split-grant impossibility, and the one-outstanding-grant invariant.

The brief warns that concurrent requests can "split durable grants across peers
so no robot can enter". These tests pin down why canonical sequential
acquisition makes that state unreachable here, and they try hard to reach it.

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from niharamesh.coordination import BlockingClass, ZoneProtocol, detect_wait_for_cycle
from niharamesh.coordination.requester import AdmissionContext
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
            self.assert_invariants()

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

    def wait_for_graph(self) -> dict[str, str]:
        graph: dict[str, str] = {}
        for protocol in self.protocols.values():
            graph.update(protocol.wait_for_graph())
        return graph

    def executable_holder(self, zone_id: str) -> str | None:
        allowed = [r for r, p in self.protocols.items() if p.may_enter(zone_id)]
        assert len(allowed) <= 1, f"{zone_id} is executable by {sorted(allowed)}"
        return allowed[0] if allowed else None

    def may_enter(self, zone_id: str) -> bool:
        return self.executable_holder(zone_id) is not None

    def run_until(self, robot_id: str, phase: AcquisitionPhase, rounds: int = 120) -> None:
        """Step until ``robot_id`` reaches ``phase``, then fail loudly if it does not."""
        for _ in range(rounds):
            if self[robot_id].phase() is phase:
                return
            self.step()
            self.assert_invariants()
        raise AssertionError(
            f"{robot_id} did not reach {phase.value} within {rounds} rounds; "
            f"it is {self[robot_id].phase().value}"
        )

    def assert_invariants(self) -> None:
        """A. one authority per zone. B. one outstanding grant per robot."""
        per_zone: dict[str, set[str]] = {}
        per_requester: dict[str, set[str]] = {}
        for _voter, record in self.outstanding():
            per_zone.setdefault(record.zone_id, set()).add(record.requester)
            per_requester.setdefault(record.requester, set()).add(record.zone_id)
        for zone_id, requesters in per_zone.items():
            assert len(requesters) <= 1, f"{zone_id} promised to {sorted(requesters)}"
        for requester, zones in per_requester.items():
            assert len(zones) <= 1, f"{requester} holds grants for {sorted(zones)}"
        executable: dict[str, set[str]] = {}
        for robot_id, protocol in self.protocols.items():
            for zone_id in self.zone_ids:
                if protocol.may_enter(zone_id):
                    executable.setdefault(zone_id, set()).add(robot_id)
        for zone_id, robots in executable.items():
            assert len(robots) <= 1, f"{zone_id} is executable by {sorted(robots)}"
        assert detect_wait_for_cycle(self.wait_for_graph()) is None, "wait-for graph must be acyclic"


# --------------------------------------------------------------------- tests


def test_every_walk_starts_at_canonical_index_zero_including_the_self_voter() -> None:
    """Never pre-reserve your own grant: it is step zero of the same order."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    order = fleet["r1"].required_voters("r1")
    assert order == ("r1", "r2", "r3")

    for robot_id in ("r1", "r2", "r3"):
        fleet[robot_id].begin_acquire("z1")
    fleet.settle(rounds=1)

    acq = fleet["r2"].requester.active
    assert acq is not None
    assert [s.voter for s in acq.slots] == list(order), "the walk must be the global order"
    assert acq.slots[0].voter == "r1"
    assert acq.slots[0].is_self is False

    # r1's own voter is at its *own* canonical index, not at index 0 by privilege.
    acq1 = fleet["r1"].requester.active
    assert acq1 is not None
    assert acq1.slots[0].voter == "r1"
    assert acq1.slots[0].is_self is True
    assert acq1.held() == ("r1",), "r1's self grant was step zero of the shared order"


def test_partial_acquirer_blocks_the_whole_fleet_and_never_splits() -> None:
    """Test 2: A holds [r1]; B must be blocked; no split state is reachable."""
    timing = ProtocolTiming(solicit_timeout_s=0.05)
    fleet = Fleet(["r1", "r2", "r3"], ["z1"], timing=timing)
    # r1 does not request, so r2 can win canonical index zero.
    fleet["r2"].begin_acquire("z1")
    fleet.settle(rounds=2)
    assert fleet.holders() == {"z1": "r2"}, "A must hold the grant from the first voter"
    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.held()[0] == "r1", "the walk starts at canonical index zero"
    assert len(acq.held()) < len(fleet["r2"].required_voters("r2")), "A is only partial"
    assert fleet["r3"].voter.state_of("z1") is ZoneState.FREE, "A has not reached r3 yet"

    # B starts while A holds a partial set.
    fleet["r3"].begin_acquire("z1")
    fleet.settle(rounds=6)

    rejection = fleet["r3"].requester.last_rejection
    assert rejection is not None
    assert rejection.reason.value == "zone_promised"
    assert fleet["r3"].requester.held_grants == 0, "a blocked requester must hold nothing at all"
    assert fleet.holders() == {"z1": "r2"}
    assert not fleet["r3"].may_enter("z1")

    # The refusal names the blocking resource.
    text = fleet["r3"].why_blocked("z1")
    assert "blocked=" in text
    assert "blocking_resource=z1" in text

    # A completes; B then proceeds, in its own queue position.
    fleet.run_until("r2", AcquisitionPhase.GRANTED)
    assert fleet.executable_holder("z1") == "r2"
    assert fleet["r2"].mark_entered("z1")
    fleet.settle(rounds=3)
    fleet["r2"].release()
    fleet.settle(rounds=10)

    fleet.run_until("r3", AcquisitionPhase.GRANTED)
    assert fleet.executable_holder("z1") == "r3"
    fleet.assert_invariants()


def test_a_cancelling_partial_acquirer_frees_the_zone_for_the_next_in_line() -> None:
    timing = ProtocolTiming(solicit_timeout_s=0.05)
    fleet = Fleet(["r1", "r2", "r3"], ["z1"], timing=timing)
    fleet["r2"].begin_acquire("z1")
    fleet.settle(rounds=2)
    assert fleet.holders() == {"z1": "r2"}

    fleet["r3"].begin_acquire("z1")
    fleet.settle(rounds=3)
    assert fleet["r3"].requester.last_rejection is not None

    # A cancels: durable first, then reconciliation.
    fleet["r2"].cancel("abort")
    fleet.settle(rounds=8)
    assert fleet.holders() == {}

    fleet.run_until("r3", AcquisitionPhase.GRANTED)
    assert fleet.executable_holder("z1") == "r3"
    assert fleet["r3"].requester.blocking_report(fleet.now_ns).kind is not (BlockingClass.LIVELOCK_SUSPECTED)


def test_two_robots_can_never_hold_the_same_zone_concurrently() -> None:
    """Adversarial: everyone requests everything at once, round after round."""
    fleet = Fleet(["r1", "r2", "r3"], ["z1", "z2"])
    for robot_id in ("r1", "r2", "r3"):
        fleet[robot_id].begin_acquire("z1")
    for _ in range(40):
        for robot_id in ("r1", "r2", "r3"):
            protocol = fleet[robot_id]
            acq = protocol.requester.active
            if acq is not None and acq.phase is AcquisitionPhase.GRANTED:
                protocol.mark_entered("z1")
            elif acq is not None and acq.phase is AcquisitionPhase.OCCUPIED:
                protocol.release()
            elif acq is None:
                protocol.begin_acquire("z1")
        fleet.step()
        fleet.assert_invariants()
    assert fleet.holders().keys() <= {"z1"}


def test_disjoint_zones_proceed_in_parallel_for_different_robots() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1", "z2"])
    fleet["r1"].begin_acquire("z1")
    fleet["r2"].begin_acquire("z2")
    fleet.settle(rounds=12)

    assert fleet["r1"].phase() is AcquisitionPhase.GRANTED
    assert fleet["r2"].phase() is AcquisitionPhase.GRANTED
    assert fleet.holders() == {"z1": "r1", "z2": "r2"}
    assert fleet.executable_holder("z1") == "r1"
    assert fleet.executable_holder("z2") == "r2"

    # A second concurrent acquisition is refused locally: invariant 6.
    import pytest

    fleet["r3"].begin_acquire("z1")
    fleet.step()
    with pytest.raises(RuntimeError, match="invariant 6"):
        fleet["r3"].begin_acquire("z2")


def test_wait_for_graph_is_acyclic_under_contention() -> None:
    fleet = Fleet(["r1", "r2", "r3"], ["z1"])
    for robot_id in ("r1", "r2", "r3"):
        fleet[robot_id].begin_acquire("z1")
    for _ in range(20):
        fleet.step()
        fleet.assert_invariants()
        assert fleet["r1"].detect_deadlock(fleet.wait_for_graph()) is None
    assert detect_wait_for_cycle({"r1": "r2"}) is None
    assert detect_wait_for_cycle({"r1": "r2", "r2": "r1"}) == ("r1", "r2", "r1")

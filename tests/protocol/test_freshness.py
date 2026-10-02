"""Freshness: FRESH / STALE / UNKNOWN, and what each is allowed to do.

The two rules this file exists to pin down:

* **A negative raw age is never FRESH.** A message that looks like it was sent in
  the future means the clock relationship or the sender is wrong; the honest
  answer is UNKNOWN.
* **Freshness expiry removes permission, never occupancy.** A peer whose
  telemetry went quiet may still be physically inside the aisle.

The harness is local and in-memory: no transport, no persistence workstream.
"""

from __future__ import annotations

from collections.abc import Sequence

from niharamesh.clocks import SharedClockEstimator
from niharamesh.coordination import BlockingClass, ZoneProtocol
from niharamesh.coordination.freshness import (
    ClockJumpGuard,
    classify,
    classify_intent,
    classify_logical,
    classify_peer_state,
    freshness_of,
)
from niharamesh.coordination.requester import AdmissionContext
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    FreshnessClass,
    Heartbeat,
    PeerEnvelope,
    PeerIntent,
    PeerMessage,
    PeerState,
    build_message,
)
from niharamesh.domain.identity import Membership
from niharamesh.domain.ids import digest_of
from niharamesh.domain.map import MapBoundary, Pose2, WarehouseMap, Zone, ZoneState
from niharamesh.domain.units import TimeDomain

RUN_ID = "run-1"
EPOCH = "e1"
NS = 1_000_000_000
HORIZON = NS


class FakeJournal:
    """In-memory :class:`~niharamesh.ports.AuthorityJournal`."""

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.corrupt = False
        self._n = 0

    def append(self, record_type: str, payload: dict[str, object]) -> str:
        if self.corrupt:
            return ""
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
        self.corrupt = True

    @property
    def healthy(self) -> bool:
        return not self.corrupt

    def close(self) -> None:
        return None


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


def peer_state(
    robot_id: str,
    session_id: str,
    seq: int,
    sent_at_ns: int,
    *,
    domain: TimeDomain = TimeDomain.LOGICAL,
) -> PeerState:
    return PeerState(
        robot_id=robot_id,
        session_id=session_id,
        seq=seq,
        pose=(0.0, 0.0, 0.0),
        velocity=(0.0, 0.0),
        uncertainty_m=0.02,
        uncertainty_rad=0.01,
        sent_at_ns=sent_at_ns,
        time_domain=domain,
    )


def frame(
    sender: str,
    session: str,
    kind: str,
    body: object,
    seq: int,
    *,
    domain: TimeDomain = TimeDomain.LOGICAL,
) -> PeerMessage:
    envelope = PeerEnvelope(
        kind=kind,
        sender=sender,
        sender_session=session,
        run_id=RUN_ID,
        epoch=EPOCH,
        seq=seq,
        sent_at_ns=0,
        time_domain=domain,
    )
    return build_message(envelope, body)  # type: ignore[arg-type]


def observed_estimator(peer_id: str, *, rtt_ns: int = 2_000_000, offset_ns: int = 0) -> SharedClockEstimator:
    """An estimator with ``samples`` samples and a known RTT."""
    estimator = SharedClockEstimator()
    for _ in range(4):
        estimator.observe(peer_id, 0, offset_ns, rtt_ns)
    return estimator


def build(
    robots: Sequence[str] = ("r1", "r2", "r3"),
    zones: Sequence[str] = ("z1",),
    **kwargs: object,
) -> tuple[ZoneProtocol, dict[str, str], WarehouseMap]:
    membership = make_membership(robots)
    sessions = {r: f"{r}-s1" for r in membership.members}
    warehouse_map = make_map(zones)
    protocol = ZoneProtocol(
        robot_id=membership.members[0],
        session_id=sessions[membership.members[0]],
        membership=membership,
        journal=FakeJournal(),
        warehouse_map=warehouse_map,
        safety_check=allow,
        session_registry=lambda rid: sessions.get(rid),
        **kwargs,  # type: ignore[arg-type]
    )
    protocol.start()
    return protocol, sessions, warehouse_map


# ------------------------------------------------------------------ unit rules


def test_no_clock_estimate_is_unknown_not_fresh() -> None:
    verdict = classify("r2", sent_at_ns=0, now_ns=0, estimator=SharedClockEstimator(), horizon_ns=HORIZON)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "no_clock_estimate"
    assert verdict.age_ns is None
    assert verdict.usable is False


def test_uncertainty_at_or_above_half_the_horizon_is_unknown() -> None:
    # Conservative uncertainty is rtt/2 + 1ms, so rtt=2ms gives 2ms.
    tight = observed_estimator("r2", rtt_ns=2_000_000)
    assert classify("r2", 0, 0, tight, horizon_ns=NS).freshness is FreshnessClass.FRESH

    loose = observed_estimator("r2", rtt_ns=2_000_000_000)
    verdict = classify("r2", 0, 0, loose, horizon_ns=NS)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "uncertainty_exceeds_half_horizon"
    assert verdict.uncertainty_ns >= NS // 2
    assert verdict.usable is False


def test_negative_raw_age_is_unknown_not_fresh() -> None:
    estimator = observed_estimator("r2")
    # Sent "in the future": now - (sent + offset) + uncertainty < 0.
    verdict = classify("r2", sent_at_ns=10 * NS, now_ns=0, estimator=estimator, horizon_ns=HORIZON)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "negative_raw_age_is_not_fresh"
    assert verdict.age_ns is not None and verdict.age_ns < 0
    assert verdict.usable is False, "a negative age must never grant permission"


def test_age_beyond_the_horizon_is_stale() -> None:
    estimator = observed_estimator("r2")
    verdict = classify("r2", sent_at_ns=0, now_ns=10 * NS, estimator=estimator, horizon_ns=HORIZON)
    assert verdict.freshness is FreshnessClass.STALE
    assert verdict.reason == "age_exceeds_horizon"
    assert verdict.usable is False


def test_age_within_the_horizon_is_fresh() -> None:
    estimator = observed_estimator("r2")
    verdict = classify("r2", sent_at_ns=0, now_ns=NS // 10, estimator=estimator, horizon_ns=HORIZON)
    assert verdict.freshness is FreshnessClass.FRESH
    assert verdict.usable is True


def test_logical_clock_rules() -> None:
    assert classify_logical(0, 0, HORIZON).freshness is FreshnessClass.FRESH
    assert classify_logical(0, HORIZON + 1, HORIZON).freshness is FreshnessClass.STALE
    verdict = classify_logical(10, 0, HORIZON)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "negative_raw_age_is_not_fresh"
    assert classify_logical(0, 0, 0).reason == "horizon_must_be_positive"


def test_clock_domains_are_never_mixed() -> None:
    estimator = observed_estimator("r2")
    state = peer_state("r2", "r2-s1", 1, 0, domain=TimeDomain.MONOTONIC)
    verdict = classify_peer_state(state, 0, TimeDomain.LOGICAL, HORIZON, estimator, None)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "domain_mismatch:monotonic!=logical"
    assert verdict.age_ns is None

    display = peer_state("r2", "r2-s1", 1, 0, domain=TimeDomain.DISPLAY_UTC)
    verdict = classify_peer_state(display, 0, TimeDomain.DISPLAY_UTC, HORIZON)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "display_time_is_not_a_clock_domain"


def test_clock_jump_guard_forces_unknown_until_stable() -> None:
    guard = ClockJumpGuard(stable_after=3)
    assert guard.stable is False
    for value in (10, 20, 30):
        guard.observe(value)
    assert guard.stable is True

    guard.observe(5)  # backwards jump
    assert guard.jumps == 1
    assert guard.stable is False
    state = peer_state("r2", "r2-s1", 1, 5)
    verdict = classify_peer_state(state, 5, TimeDomain.LOGICAL, HORIZON, None, guard)
    assert verdict.freshness is FreshnessClass.UNKNOWN
    assert verdict.reason == "local_clock_jump_suspected"

    guard.observe(6)
    guard.observe(7)
    assert guard.stable is False, "two forward readings is not yet a clean run"
    guard.observe(8)
    assert guard.stable is True


def test_intent_validity_uses_the_senders_own_horizon() -> None:
    intent = PeerIntent(
        run_id=RUN_ID,
        epoch=EPOCH,
        map_id="map-1",
        map_digest="0" * 32,
        robot_id="r2",
        session_id="r2-s1",
        seq=1,
        plan_version=1,
        projected_path=((0.0, 0.0, 0.0),),
        expected_zones=("z1",),
        validity_horizon_ns=NS // 10,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    assert classify_intent(intent, 0, TimeDomain.LOGICAL).freshness is FreshnessClass.FRESH
    stale = classify_intent(intent, NS // 10 + 1, TimeDomain.LOGICAL)
    assert stale.freshness is FreshnessClass.STALE
    no_validity = intent.model_copy(update={"validity_horizon_ns": 0})
    assert classify_intent(no_validity, 0, TimeDomain.LOGICAL).reason == ("intent_declares_no_validity")


def test_heartbeat_is_liveness_only_and_never_usable() -> None:
    beat = Heartbeat(
        run_id=RUN_ID,
        epoch=EPOCH,
        robot_id="r2",
        session_id="r2-s1",
        seq=1,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    verdict = freshness_of(beat, 0, TimeDomain.LOGICAL, HORIZON)
    assert verdict.reason == "liveness_only_not_a_usable_claim"


# -------------------------------------------------- withdrawal vs occupancy


def test_stale_peer_state_withdraws_permission_but_retains_occupancy() -> None:
    """Test 9: expiry removes permission to assume, never physical occupancy."""
    owner, sessions, warehouse_map = build()
    peers = {"r1": owner}
    for robot_id in ("r2", "r3"):
        peers[robot_id] = ZoneProtocol(
            robot_id=robot_id,
            session_id=sessions[robot_id],
            membership=owner.membership,
            journal=FakeJournal(),
            warehouse_map=warehouse_map,
            safety_check=allow,
            session_registry=lambda rid: sessions.get(rid),
        )
        peers[robot_id].start()

    def pump(now_ns: int) -> None:
        for p in peers.values():
            p.tick(now_ns)
        for p in peers.values():
            for target, message in list(p.outbox):
                peers[target].ingest(message)
            p.outbox.clear()

    owner.begin_acquire("z1")
    now = 0
    for _ in range(14):
        now += 5_000_000
        pump(now)
    assert owner.phase() is AcquisitionPhase.GRANTED
    assert owner.mark_entered("z1")
    now += 5_000_000
    pump(now)
    for p in peers.values():
        assert p.voter.state_of("z1") is ZoneState.OCCUPIED

    # A fresh peer state from r2 is usable.
    outcome = owner.ingest(frame("r2", sessions["r2"], "peer_state", peer_state("r2", "r2-s1", 1, now), 9001))
    assert outcome.accepted
    assert owner.peer_permissions("r2") is True
    assert "r2" not in owner.freshness.suspended_peers()

    # Let it go stale, then check both halves of the invariant.
    for _ in range(400):
        now += 5_000_000
        owner.tick(now)
    assert owner.peer_permissions("r2") is False
    assert "r2" in owner.freshness.suspended_peers()
    for p in peers.values():
        assert p.voter.state_of("z1") is ZoneState.OCCUPIED, (
            "freshness expiry must never clear a physically occupied zone"
        )
    assert "peer_state_stale" in owner.why_blocked("z1")
    assert owner.may_enter("z1") is False

    # A heartbeat cannot launder a suspended peer back to usable.
    beat = Heartbeat(
        run_id=RUN_ID,
        epoch=EPOCH,
        robot_id="r2",
        session_id=sessions["r2"],
        seq=2,
        sent_at_ns=now,
        time_domain=TimeDomain.LOGICAL,
    )
    owner.ingest(frame("r2", sessions["r2"], "heartbeat", beat, 9002))
    entry = owner.freshness.get("r2")
    assert entry is not None
    assert entry.from_heartbeat is True
    assert entry.usable is False

    # Once r2 publishes again, permission returns.
    owner.ingest(frame("r2", sessions["r2"], "peer_state", peer_state("r2", "r2-s1", 3, now), 9003))
    assert owner.peer_permissions("r2") is True


def test_a_never_seen_peer_is_not_treated_as_suspended() -> None:
    protocol, _sessions, _map = build()
    assert protocol.freshness.suspended_peers() == ()
    assert protocol.peer_permissions("r2") is True
    assert protocol.may_enter("z1") is False, "no grant, no entry"
    report = protocol.requester.blocking_report(0)
    assert report.kind is BlockingClass.IDLE


def test_intent_for_another_map_is_refused() -> None:
    protocol, sessions, warehouse_map = build()
    intent = PeerIntent(
        run_id=RUN_ID,
        epoch=EPOCH,
        map_id="other-map",
        map_digest="0" * 32,
        robot_id="r2",
        session_id=sessions["r2"],
        seq=1,
        plan_version=1,
        validity_horizon_ns=NS,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    outcome = protocol.ingest(frame("r2", sessions["r2"], "peer_intent", intent, 1))
    assert outcome.reason is not None
    assert outcome.reason.value == "map_mismatch"
    assert warehouse_map.map_id == "map-1"


def test_claim_from_a_superseded_boot_is_not_stored() -> None:
    protocol, sessions, _map = build()
    protocol.ingest(frame("r2", sessions["r2"], "peer_state", peer_state("r2", "r2-s9", 1, 0), 1))
    before = protocol.freshness.get("r2")
    assert before is not None and before.session_id == "r2-s9"
    protocol.ingest(frame("r2", "r2-s1", "peer_state", peer_state("r2", "r2-s1", 1, 0), 2))
    after = protocol.freshness.get("r2")
    assert after is not None
    assert after.session_id == "r2-s9", "an older boot must not overwrite current knowledge"

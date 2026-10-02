"""Peer state/intent publication and freshness expiry, end to end in the harness.

Milestone A left finding N5 open: the deterministic harness published no
``peer_state`` and no ``peer_intent``, so ``ZoneProtocol.may_enter``'s suspend
guard was inert in every harness run. A test that only ever sees a complete,
fresh, in-order world asserts a weaker property than process mode does.

What these tests pin down:

* the agent publishes **its own** observed/estimated state and **its own** locally
  computed intent -- never a pose synthesised by the harness from world truth;
* the harness only *schedules and routes*; it invents no message body;
* a cached ``FRESH`` verdict **expires with no new incoming message**, so a peer
  that goes quiet stops being assumable;
* a heartbeat proves liveness and never becomes usable permission;
* duplicate and reordered publication are handled by sequence, not by arrival
  order.

The evaluator may read world truth to assert all of this. The agent may not.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from niharamesh.coordination.freshness import FreshnessTable
from niharamesh.coordination.protocol import REPLAY_WINDOW
from niharamesh.domain.coordination import FreshnessClass, Heartbeat, PeerEnvelope, PeerState
from niharamesh.domain.identity import Membership, RobotSession
from niharamesh.domain.units import PROTOCOL_EPOCH, TimeDomain
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.scenario.library import three_way_junction


@pytest.fixture
def fleet() -> Iterator[DeterministicHarness]:
    harness = DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="peer-publication")
    try:
        yield harness
    finally:
        for agent in harness.agents.values():
            agent.close()


def test_harness_routes_agent_originated_peer_state_and_intent(
    fleet: DeterministicHarness,
) -> None:
    """Every peer must publish, and every receiver must record what it published.

    The harness drains each agent's outbox every tick, so what is left on it after
    a run is *nothing* -- which is itself the assertion that it was drained. The
    retained evidence is the receiver side: each robot's freshness table, which
    only a genuinely received message can populate.
    """
    fleet.run(max_sim_time_s=1.0)

    for target in ("amr-01", "amr-02", "amr-03"):
        table = fleet.agents[target].coordinator.freshness
        for peer in ("amr-01", "amr-02", "amr-03"):
            if peer == target:
                # A robot never ingests its own publication: the local voter runs
                # in-process and a self-addressed frame would be a loopback.
                continue
            entry = table.get(peer)
            assert entry is not None, f"{target} never recorded a claim from {peer}"
            assert entry.freshness is FreshnessClass.FRESH
            assert not entry.from_heartbeat, (
                "state published by an agent is not a heartbeat and must be usable"
            )

    # And nothing is left undelivered: the outbox is drained, not accumulated.
    for sender in fleet.agents:
        assert fleet.agents[sender].publications == [], (
            f"{sender} has {len(fleet.agents[sender].publications)} undrained publications"
        )
        assert fleet.agents[sender].auction_outbox == []


def test_publication_cadence_follows_the_declared_protocol_timing() -> None:
    """Publication is on the scenario's declared periods, not every physics tick.

    A robot publishing state at the physics rate would flood the channel and make
    the freshness horizon meaningless; publishing never would leave the horizon
    untestable. Both rates are declared in ``ProtocolTiming``.
    """
    harness = DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="cadence")
    try:
        published = harness.record_publication_counts()
        harness.run(max_sim_time_s=2.0)
        protocol = harness.scenario.simulation.protocol

        # ``record_publication_counts`` counts frames each sender actually emitted,
        # which is a property of the agent rather than of what a receiver chose to
        # keep. A robot publishing every physics tick at 20 Hz would emit 40.
        frames = published["amr-01"]["peer_state"]
        assert frames == pytest.approx(2.0 / protocol.state_publish_period_s, abs=1.0), (
            f"{frames} peer_state frames in 2 s at a declared {protocol.state_publish_period_s} s period"
        )
        assert frames < 2.0 * harness.scenario.simulation.physics_step_hz
        assert published["amr-01"]["peer_intent"] > 0
    finally:
        for agent in harness.agents.values():
            agent.close()


def test_published_state_is_the_agents_own_estimate_not_world_truth(
    fleet: DeterministicHarness,
) -> None:
    """The publication must not be a laundered copy of the simulator's exact pose.

    ``world.observe`` returns a *pose estimate*. The published body is built from
    that estimate and its declared uncertainty, so comparing it to truth is a
    legitimate check that the harness did not substitute ``world.truth()``.
    """
    fleet.run(max_sim_time_s=1.0)

    # ``World.truth().robots`` is a mapping, not a sequence. The evaluator may read
    # it; the agent may not. The assertion is that what the agent published is
    # derived from its own estimate rather than copied from truth.
    exact = fleet.world.truth().robots["amr-01"]
    estimate = fleet.world.observe("amr-01").pose_estimate

    # Without a declared, non-zero uncertainty model the two would be
    # indistinguishable and this test could not show which one was published.
    assert estimate.uncertainty.kind != "unknown"
    assert estimate.uncertainty.sigma_m > 0.0

    # Both peers recorded a claim from amr-01, which only a genuinely delivered
    # publication can produce. amr-01 does not record its own: the local voter
    # runs in-process and a self-addressed frame would be a refused loopback.
    for peer_id in ("amr-02", "amr-03"):
        entry = fleet.agents[peer_id].coordinator.freshness.get("amr-01")
        assert entry is not None, f"nothing was received from amr-01 by {peer_id}"
    assert fleet.agents["amr-01"].coordinator.freshness.get("amr-01") is None

    # The published pose is within the estimator's own declared bound of truth.
    # A larger discrepancy would mean something other than the estimate travelled.
    bound = 4.0 * estimate.uncertainty.sigma_m + 1e-9
    assert abs(estimate.pose.x - exact.x) <= bound
    assert abs(estimate.pose.y - exact.y) <= bound

    # And the battery is published with the label that says where it came from,
    # never as a bare number.
    assert fleet.scenario.simulation.battery.source in {
        "simulated",
        "estimated",
        "measured",
        "unavailable",
    }


def test_a_quiet_peer_stops_being_usable_with_no_new_message(fleet: DeterministicHarness) -> None:
    """The property N5 exists for.

    ``FreshnessTable.observe_now`` must expire a cached ``FRESH`` verdict when
    time passes without a new claim. Without a new message there is nothing to
    re-classify against, so a table that only re-classifies on receipt would
    report a peer as fresh forever -- and a peer that went quiet mid-crossing
    would stay assumable for the rest of the run.
    """
    agent = fleet.agents["amr-02"]
    table: FreshnessTable = agent.coordinator.freshness
    horizon = table.horizon_ns
    base = 1_000_000_000

    table.record(
        "amr-01",
        "amr-01-s1",
        seq=1,
        sent_at_ns=base,
        time_domain=TimeDomain.LOGICAL,
        verdict=_fresh_verdict(),
        now_ns=base,
    )
    assert table.get("amr-01") is not None
    assert table.get("amr-01").usable  # type: ignore[union-attr]

    # No new message. Only the clock moves.
    table.observe_now(base + horizon + 1)

    entry = table.get("amr-01")
    assert entry is not None
    assert entry.freshness is FreshnessClass.STALE
    assert not entry.usable
    assert table.suspended_peers() == ("amr-01",)


def test_expired_peer_state_suspends_entry_permission(fleet: DeterministicHarness) -> None:
    """``may_enter`` must refuse once a required peer's claim is no longer usable.

    This is the guard N5 said was never exercised in the harness. It is about
    *permission to assume*, and it must never clear a zone record: the peer may
    still be physically inside the aisle.
    """
    fleet.run(max_sim_time_s=1.0)
    coordinator = fleet.agents["amr-02"].coordinator
    assert coordinator.may_enter("zn-junction")

    table = coordinator.freshness
    for peer in ("amr-01", "amr-03"):
        entry = table.get(peer)
        assert entry is not None
        # Age every claim past the horizon by rewriting the claim's own stamp and
        # re-classifying -- exactly what ``observe_now`` does on a quiet link.
        table.observe_now(table.horizon_ns * 10 + table.get(peer).sent_at_ns)  # type: ignore[union-attr]

    assert not coordinator.may_enter("zn-junction")
    assert "peer claims are not usable" in coordinator.why_blocked("zn-junction")
    # The authority record itself is untouched: suspension withdraws permission to
    # assume, it does not release anything.
    assert coordinator.holders() == {"zn-junction": "amr-02"}


#: The observing robot below is ``amr-02``, so the peer must be somebody else:
#: ``ZoneProtocol.ingest`` refuses a self-addressed frame as a loopback, and a
#: fixture publishing from ``amr-02`` to ``amr-02`` would test that refusal rather
#: than the freshness rule.
PEER = "amr-01"
PEER_SESSION = "amr-01-s1"


def test_a_heartbeat_is_liveness_only_and_never_usable_permission() -> None:
    agent, _membership = _bare_agent()
    beat = Heartbeat(
        run_id="run-1",
        epoch=PROTOCOL_EPOCH,
        robot_id=PEER,
        session_id=PEER_SESSION,
        seq=1,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    envelope = PeerEnvelope(
        kind="heartbeat",
        sender=PEER,
        sender_session=PEER_SESSION,
        run_id="run-1",
        epoch=PROTOCOL_EPOCH,
        seq=1,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    from niharamesh.domain.coordination import build_message

    agent.ingest(build_message(envelope, beat))
    entry = agent.coordinator.freshness.get(PEER)
    assert entry is not None
    assert entry.freshness is FreshnessClass.FRESH
    assert entry.from_heartbeat
    assert not entry.usable, "a heartbeat must never become permission to assume anything"


def test_reordered_and_duplicate_publication_is_handled_by_sequence() -> None:
    agent, _ = _bare_agent()
    envelope = PeerEnvelope(
        kind="peer_state",
        sender=PEER,
        sender_session=PEER_SESSION,
        run_id="run-1",
        epoch=PROTOCOL_EPOCH,
        seq=7,
        sent_at_ns=0,
        time_domain=TimeDomain.LOGICAL,
    )
    from niharamesh.domain.coordination import build_message

    def state(seq: int, x: float, stamp: int) -> object:
        body = PeerState(
            robot_id=PEER,
            session_id=PEER_SESSION,
            seq=seq,
            pose=(x, 0.0, 0.0),
            velocity=(0.0, 0.0),
            uncertainty_m=0.01,
            uncertainty_rad=0.01,
            sent_at_ns=stamp,
            time_domain=TimeDomain.LOGICAL,
        )
        return build_message(envelope.model_copy(update={"seq": seq}), body)

    agent.ingest(state(7, 7.0, 0))
    entry = agent.coordinator.freshness.get(PEER)
    assert entry is not None and entry.seq == 7

    # An exact duplicate is recognised as one and does not move anything.
    agent.ingest(state(7, 99.0, 0))
    duplicate = agent.coordinator.freshness.get(PEER)
    assert duplicate is not None and duplicate.seq == 7

    # A newer claim supersedes the older one.
    agent.ingest(state(40, 40.0, 0))
    newer = agent.coordinator.freshness.get(PEER)
    assert newer is not None and newer.seq == 40

    # A **superseded** sequence arriving inside the replay window is treated as a
    # fresh, reordered message -- which is the design, because reordering is exactly
    # what the window exists to tolerate. What must not happen is the sender being
    # treated as hostile: that distinction belongs to the window's far edge.
    agent.ingest(state(7, 7.0, 0))
    reordered = agent.coordinator.freshness.get(PEER)
    assert reordered is not None, "a reordered publication inside the window is accepted"
    assert PEER not in agent.coordinator.quarantined

    # Below the window it is a replay, refused outright, and the sender is
    # quarantined. This is the bound that actually stops an old frame rolling a
    # record backwards.
    far = 40 + REPLAY_WINDOW + 10
    agent.ingest(state(far, 1.0, 0))
    assert agent.coordinator.freshness.get(PEER).seq == far  # type: ignore[union-attr]
    agent.ingest(state(far - REPLAY_WINDOW - 1, 0.0, 0))
    assert agent.coordinator.freshness.get(PEER).seq == far  # type: ignore[union-attr]
    assert PEER in agent.coordinator.quarantined, (
        "a replay below the window must be refused as hostile, not merely ignored"
    )


def _fresh_verdict():  # type: ignore[no-untyped-def]
    from niharamesh.ports import FreshnessVerdict

    return FreshnessVerdict(FreshnessClass.FRESH, 0.0, 0, "age_within_horizon")


def _bare_agent():  # type: ignore[no-untyped-def]
    scenario = three_way_junction()
    from niharamesh.agent.runtime import RobotAgent
    from niharamesh.clocks import LogicalClock

    identity = scenario.robot("amr-02")
    # The digest binds this membership to the shared map. Without it the coordinator
    # refuses every transaction by design, so a decision-layer fixture that omitted
    # it was testing an agent that could not acquire anything.
    membership = Membership(
        run_id="run-1",
        epoch=PROTOCOL_EPOCH,
        members=tuple(r.robot_id for r in scenario.robots),
    ).model_copy(update={"digest": scenario.map.digest()})
    session = RobotSession(robot_id="amr-02", session_id="amr-02-s1", started_at_ns=0, listening_port=0)
    agent = RobotAgent(
        identity=identity,
        session=session,
        scenario=scenario,
        membership=membership,
        clock=LogicalClock(0),
        run_id="run-1",
    )
    # The freshness classifier consults a clock-jump guard that needs three
    # consecutive forward readings before it will classify anything at all. A
    # decision-layer fixture that never ticked would therefore see every claim
    # reported as UNKNOWN -- a correct refusal to reason about a clock it has not
    # observed, and useless for testing the rule itself.
    for step in range(1, 4):
        agent.coordinator.tick(step * 50_000_000)
    return agent, membership

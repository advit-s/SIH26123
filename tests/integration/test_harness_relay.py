"""Exercise the harness channel with real agents, protocol and journals."""

from collections.abc import Iterator

import pytest

from niharamesh.coordination.protocol import ZoneProtocol
from niharamesh.domain.coordination import AcquisitionPhase
from niharamesh.runs.harness import DeterministicHarness
from niharamesh.runs.orchestrator import freeze_snapshot
from niharamesh.scenario.library import three_way_junction


@pytest.fixture
def harness() -> Iterator[DeterministicHarness]:
    fleet = DeterministicHarness(freeze_snapshot(three_way_junction()), run_id="relay-regression")
    try:
        yield fleet
    finally:
        for agent in fleet.agents.values():
            agent.close()


def test_harness_delivers_requests_and_replies_to_complete_canonical_acquisition(
    harness: DeterministicHarness,
) -> None:
    harness.run(max_sim_time_s=1)

    requester = harness.agents["amr-02"].coordinator
    acquisition = requester.requester.active
    assert acquisition is not None
    assert acquisition.phase is AcquisitionPhase.GRANTED
    assert acquisition.held() == ("amr-01", "amr-02", "amr-03")
    for agent in harness.agents.values():
        assert agent.coordinator.holders() == {"zn-junction": "amr-02"}

    # A grant set belongs to exactly one robot. Collecting it says nothing about the
    # other contender, which was refused and must stay refused.
    assert not harness.agents["amr-03"].coordinator.may_enter("zn-junction")
    assert harness.agents["amr-03"].coordinator.requester.active is not None
    assert harness.agents["amr-03"].coordinator.requester.active.held() == ()


def test_delivery_is_not_admission_without_a_local_safety_callback(
    harness: DeterministicHarness,
) -> None:
    """The invariant this test used to assert, moved to where it now lives.

    ``may_enter`` is true for ``amr-02`` above because :class:`RobotAgent` supplies a
    real local safety callback (contract A5). Without one -- the coordinator's own
    default -- a complete grant set still must not become entry permission, because
    delivery answers "did everybody agree" and not "can this robot get in safely".

    The harness relay is reused rather than re-implemented here: this swaps only the
    coordinator under ``amr-02`` and lets the same drain/deliver path run, so the
    canonical walk being exercised is the real one.
    """
    agent = harness.agents["amr-02"]
    bare = ZoneProtocol(
        robot_id="amr-02",
        session_id=agent.session.session_id,
        membership=harness.membership,
        journal=agent.journal,
        warehouse_map=harness.snapshot.scenario.map,
        timing=harness.scenario.simulation.protocol,
        time_domain=agent.coordinator.time_domain,
        session_registry=lambda peer: f"{peer}-s1",
    )
    bare.start()
    agent.coordinator = bare

    harness.run(max_sim_time_s=2)

    acquisition = bare.requester.active
    assert acquisition is not None
    assert acquisition.phase is AcquisitionPhase.GRANTED
    assert acquisition.held() == ("amr-01", "amr-02", "amr-03")
    assert not bare.may_enter("zn-junction"), (
        "a complete grant set with no local safety evidence must still not be entry permission"
    )
    assert "blocked=safety_gate" in bare.why_blocked("zn-junction")
    assert "no local safety gate was supplied" in bare.why_blocked("zn-junction")
    for peer in harness.agents.values():
        assert peer.coordinator.holders() == {"zn-junction": "amr-02"}


def test_harness_delivers_durable_cancellation_and_peer_acknowledgements(
    harness: DeterministicHarness,
) -> None:
    harness.run(max_sim_time_s=1)
    requester = harness.agents["amr-02"].coordinator
    acquisition = requester.requester.active
    assert acquisition is not None
    assert acquisition.phase is AcquisitionPhase.GRANTED

    requester.cancel("integration test: owner cancels before entry")
    assert acquisition.durably_non_executable
    harness.run(max_sim_time_s=2)

    assert acquisition.phase is AcquisitionPhase.CANCELLED
    assert acquisition.cancel_acked == {"amr-01", "amr-02", "amr-03"}
    assert not requester.may_enter("zn-junction")
    for agent in harness.agents.values():
        assert "amr-02" not in agent.coordinator.holders().values()

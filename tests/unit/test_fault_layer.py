"""Fault-layer tests.

Two things are asserted here beyond "the message went somewhere":

* **Directedness.** A fault declared between A and B cannot touch B<->C.
* **Removability restores communication, not permission.** Removing a network
  fault makes messages flow again and changes no authority state whatsoever. The
  assertion is made against the fault layer's *own* state, not against agent
  behaviour, because a fault layer that could influence permission would be a
  different (much worse) component.
"""

from __future__ import annotations

import pytest

from niharamesh.domain.coordination import (
    Heartbeat,
    PeerEnvelope,
    PeerMessage,
    PeerState,
    build_message,
)
from niharamesh.domain.faults import (
    FaultChannel,
    FaultKind,
    FaultSpec,
    FaultTarget,
)
from niharamesh.domain.units import TimeDomain
from niharamesh.transport.faults import (
    ACTIVE_FAULT_NOTE,
    DecisionKind,
    FaultLayer,
)

_S = TimeDomain.MONOTONIC


def _message(sender: str, seq: int = 1) -> PeerMessage:
    envelope = PeerEnvelope(
        kind="heartbeat",
        sender=sender,
        sender_session=f"sess-{sender}",
        run_id="run-a",
        epoch="e1",
        seq=seq,
        sent_at_ns=1_000,
        time_domain=_S,
    )
    body = Heartbeat(
        run_id="run-a",
        epoch="e1",
        robot_id=sender,
        session_id=f"sess-{sender}",
        seq=seq,
        sent_at_ns=1_000,
        time_domain=_S,
    )
    return build_message(envelope, body)


def _state(robot_id: str, seq: int) -> PeerMessage:
    envelope = PeerEnvelope(
        kind="peer_state",
        sender=robot_id,
        sender_session=f"sess-{robot_id}",
        run_id="run-a",
        epoch="e1",
        seq=seq,
        sent_at_ns=1_000,
        time_domain=_S,
    )
    body = PeerState(
        robot_id=robot_id,
        session_id=f"sess-{robot_id}",
        seq=seq,
        pose=(0.0, 0.0, 0.0),
        velocity=(0.0, 0.0),
        uncertainty_m=0.01,
        uncertainty_rad=0.01,
        sent_at_ns=1_000,
        time_domain=_S,
    )
    return build_message(envelope, body)


def _spec(
    fault_id: str,
    kind: FaultKind,
    *,
    sender: str | None = None,
    receiver: str | None = None,
    seed: int = 7,
    start_at_s: float = 0.0,
    duration_s: float = 10.0,
    params: dict[str, float] | None = None,
) -> FaultSpec:
    return FaultSpec(
        fault_id=fault_id,
        target=FaultTarget(
            channel=FaultChannel.COORDINATION,
            kind=kind,
            sender=sender,
            receiver=receiver,
        ),
        start_at_s=start_at_s,
        duration_s=duration_s,
        seed=seed,
        params=params or {},
        expected_invariant="coordination still conserves exclusive zone authority",
    )


# --------------------------------------------------------------------- delay


def test_delay_honours_the_scheduled_offset() -> None:
    layer = FaultLayer(
        (
            _spec(
                "d",
                FaultKind.DELAY,
                sender="ra",
                params={"min_delay_ns": 50_000_000.0, "max_delay_ns": 50_000_000.0},
            ),
        ),
        local_robot_id="rc",
    )
    decision = layer.apply_outbound("rb", _message("ra"), now_ns=1_000)
    assert decision.kind is DecisionKind.DELIVER_AT
    assert decision.deliver_at_ns == 50_001_000
    assert decision.fault_id == "d"


def test_delay_does_not_touch_other_directions() -> None:
    layer = FaultLayer(
        (_spec("d", FaultKind.DELAY, sender="ra", params={"min_delay_ns": 10.0, "max_delay_ns": 10.0}),),
        local_robot_id="rc",
    )
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).deliver_at_ns == 10
    assert layer.apply_outbound("rb", _message("rz"), now_ns=0).deliver_at_ns == 0


def test_fault_outside_its_window_does_not_apply() -> None:
    layer = FaultLayer((_spec("late", FaultKind.LOSS, sender="ra", start_at_s=5.0),), local_robot_id="rc")
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DELIVER_AT


# ---------------------------------------------------------------------- loss


def test_loss_drops_exactly_the_targeted_direction() -> None:
    layer = FaultLayer((_spec("l", FaultKind.LOSS, sender="ra"),), local_robot_id="rc")
    # Sender-only targeting means every direction *out of* ra.
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    assert layer.apply_outbound("rz", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    # Any direction not originating at ra is untouched.
    assert layer.apply_outbound("rb", _message("rz"), now_ns=0).kind is DecisionKind.DELIVER_AT
    assert layer.apply_inbound(_message("rz"), now_ns=0).kind is DecisionKind.DELIVER_AT


def test_loss_can_target_a_receiver_instead() -> None:
    layer = FaultLayer((_spec("l", FaultKind.LOSS, receiver="rb"),), local_robot_id="rc")
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    assert layer.apply_outbound("rc", _message("ra"), now_ns=0).kind is DecisionKind.DELIVER_AT


def test_partial_loss_probability_is_deterministic_for_a_seed() -> None:
    spec = _spec("l", FaultKind.LOSS, sender="ra", params={"probability": 0.5})
    runs = []
    for _ in range(2):
        layer = FaultLayer((spec,), local_robot_id="rc")
        runs.append([layer.apply_outbound("rb", _message("ra"), now_ns=0).kind for _ in range(20)])
    assert runs[0] == runs[1]
    assert DecisionKind.DROP in runs[0]
    assert DecisionKind.DELIVER_AT in runs[0]


# ----------------------------------------------------------------- duplicate


def test_duplication_yields_exactly_two_copies() -> None:
    layer = FaultLayer((_spec("u", FaultKind.DUPLICATE, sender="ra"),), local_robot_id="rc")
    decision = layer.apply_outbound("rb", _message("ra"), now_ns=0)
    assert decision.kind is DecisionKind.DUPLICATE
    assert decision.copies == 2


def test_duplication_and_delay_compose_without_inventing_content() -> None:
    layer = FaultLayer(
        (
            _spec(
                "u",
                FaultKind.DUPLICATE,
                sender="ra",
                params={"min_delay_ns": 1_000.0, "max_delay_ns": 1_000.0},
            ),
        ),
        local_robot_id="rc",
    )
    decision = layer.apply_outbound("rb", _message("ra"), now_ns=0)
    assert decision.copies == 2
    assert decision.deliver_at_ns == 0
    # The layer returns decisions only; it never returns a rewritten message.
    assert not hasattr(decision, "message")


# ------------------------------------------------------------------- reorder


def test_reorder_holds_then_releases_after_the_hold() -> None:
    layer = FaultLayer(
        (_spec("r", FaultKind.REORDER, sender="ra", params={"hold_ns": 5_000.0}),),
        local_robot_id="rc",
    )
    held = layer.apply_outbound("rb", _message("ra", seq=1), now_ns=0)
    assert held.kind is DecisionKind.HOLD
    assert layer.drain(now_ns=4_999) == ()
    released = layer.drain(now_ns=5_000)
    assert len(released) == 1
    assert released[0].peer_id == "rb"
    assert released[0].direction == "outbound"
    # Identical content, merely later.
    assert released[0].message == _message("ra", seq=1)


def test_reorder_actually_reorders_delivery_order() -> None:
    """A held heartbeat is overtaken by the peer_state that follows it."""
    spec = FaultSpec(
        fault_id="r",
        target=FaultTarget(
            channel=FaultChannel.COORDINATION,
            kind=FaultKind.REORDER,
            sender="ra",
            message_kind="heartbeat",
        ),
        duration_s=10.0,
        params={"hold_ns": 5_000.0},
        expected_invariant="ordering may change; grant cycles still cannot form",
    )
    layer = FaultLayer((spec,), local_robot_id="rc")

    # seq 1 (heartbeat) is held by the reorder fault.
    assert layer.apply_outbound("rb", _message("ra", seq=1), now_ns=0).kind is DecisionKind.HOLD
    # seq 2 (peer_state) is not targeted, so it goes straight out...
    assert layer.apply_outbound("rb", _state("ra", seq=2), now_ns=1).kind is (DecisionKind.DELIVER_AT)
    # ... and only then does seq 1 catch up. Delivery order became 2, 1.
    released = layer.drain(now_ns=5_000)
    assert [p.message.envelope.seq for p in released] == [1]
    delivered_order = [2, *[p.message.envelope.seq for p in released]]
    assert delivered_order == [2, 1]
    assert delivered_order != sorted(delivered_order)


def test_inbound_reorder_records_the_sender_as_peer() -> None:
    layer = FaultLayer(
        (_spec("r", FaultKind.REORDER, sender="ra", params={"hold_ns": 1_000.0}),),
        local_robot_id="rc",
    )
    assert layer.apply_inbound(_message("ra"), now_ns=0).kind is DecisionKind.HOLD
    released = layer.drain(now_ns=1_000)
    assert released[0].direction == "inbound"
    assert released[0].peer_id == "ra"


# ----------------------------------------------------------------- partition


def test_partition_between_a_and_b_leaves_b_to_c_intact() -> None:
    # Local robot is rb, so inbound is the rb-receiving side of every direction.
    layer = FaultLayer(
        (_spec("p", FaultKind.PARTITION, sender="ra", receiver="rb"),),
        local_robot_id="rb",
    )
    # A -> B is cut in both directions.
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    assert layer.apply_inbound(_message("ra"), now_ns=0).kind is DecisionKind.DROP
    # B <-> C keeps working in both directions, and A -> C is not collateral.
    assert layer.apply_outbound("rc", _message("rb"), now_ns=0).kind is DecisionKind.DELIVER_AT
    assert layer.apply_inbound(_message("rc"), now_ns=0).kind is DecisionKind.DELIVER_AT
    assert layer.apply_outbound("rc", _message("ra"), now_ns=0).kind is DecisionKind.DELIVER_AT


def test_partition_can_be_declared_for_both_directions() -> None:
    layer = FaultLayer(
        (
            _spec("p1", FaultKind.PARTITION, sender="ra", receiver="rb"),
            _spec("p2", FaultKind.PARTITION, sender="rb", receiver="ra"),
        ),
        local_robot_id="ra",
    )
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    assert layer.apply_inbound(_message("rb"), now_ns=0).kind is DecisionKind.DROP


def test_partition_is_reported_as_silenced_and_unavailable() -> None:
    layer = FaultLayer((_spec("p", FaultKind.PARTITION, sender="ra", receiver="rb"),), local_robot_id="rc")
    health = layer.health(0)
    assert health["availability"] == "unavailable"
    silenced = health["silenced_directions"]
    assert isinstance(silenced, list)
    assert silenced == [{"sender": "ra", "receiver": "rb", "fault_id": "p", "kind": "partition"}]


# ------------------------------------------------------------- clock skew


def test_clock_skew_perturbs_the_estimate_only_within_its_direction() -> None:
    layer = FaultLayer(
        (_spec("k", FaultKind.CLOCK_SKEW, sender="ra", params={"skew_ns": 1_000_000.0}),),
        local_robot_id="rc",
    )
    skewed = layer.clock_skew_ns("ra", "rc", now_ns=0)
    assert abs(skewed) <= 1_000_000
    assert layer.clock_skew_ns("rz", "rc", now_ns=0) == 0


# --------------------------------------------------------------- determinism


def test_same_seed_produces_identical_decisions() -> None:
    specs = (
        _spec("d", FaultKind.DELAY, sender="ra", params={"min_delay_ns": 0.0, "max_delay_ns": 5_000.0}),
        _spec("l", FaultKind.LOSS, sender="rb", params={"probability": 0.4}),
        _spec("u", FaultKind.DUPLICATE, receiver="ra", params={"probability": 0.3}),
    )

    def run() -> list[tuple[str, int, int, int]]:
        layer = FaultLayer(specs, local_robot_id="rc")
        out = []
        for step in range(40):
            sender = ("ra", "rb", "rz")[step % 3]
            decision = layer.apply_outbound("rc", _message(sender, seq=step), now_ns=step * 100)
            out.append((decision.kind.value, decision.deliver_at_ns, decision.copies, step))
        return out

    assert run() == run()


def test_different_seeds_diverge() -> None:
    def run(seed: int) -> list[str]:
        spec = _spec("l", FaultKind.LOSS, sender="ra", params={"probability": 0.5}, seed=seed)
        layer = FaultLayer((spec,), local_robot_id="rc")
        return [layer.apply_outbound("rb", _message("ra", seq=i), now_ns=0).kind.value for i in range(30)]

    assert run(1) != run(999)


# ------------------------------------------------- removability and authority


def test_removing_a_partition_restores_communication_and_grants_nothing() -> None:
    spec = _spec("p", FaultKind.PARTITION, sender="ra", receiver="rb")
    layer = FaultLayer((spec,), local_robot_id="rc")

    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    before = layer.health(0)
    assert before["availability"] == "unavailable"

    assert layer.remove("p") is True

    after_decision = layer.apply_outbound("rb", _message("ra"), now_ns=0)
    assert after_decision.kind is DecisionKind.DELIVER_AT  # communication restored
    after = layer.health(0)
    assert after["availability"] == "available"
    assert after["declared"] == 0
    # Communication is back. Permission is not: the layer has no such state, and
    # its decision vocabulary contains nothing that could express one.
    assert layer.authority_decisions == 0
    assert set(DecisionKind) == {
        DecisionKind.DELIVER_AT,
        DecisionKind.DROP,
        DecisionKind.DUPLICATE,
        DecisionKind.HOLD,
    }
    assert not hasattr(layer, "grants")
    assert not hasattr(layer, "zones")
    assert ACTIVE_FAULT_NOTE in str(after["note"])


def test_removing_a_delay_restores_immediate_delivery() -> None:
    layer = FaultLayer(
        (
            _spec(
                "d", FaultKind.DELAY, sender="ra", params={"min_delay_ns": 9_000.0, "max_delay_ns": 9_000.0}
            ),
        ),
        local_robot_id="rc",
    )
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).deliver_at_ns == 9_000
    layer.remove("d")
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).deliver_at_ns == 0


def test_removing_an_unknown_fault_reports_false() -> None:
    layer = FaultLayer(local_robot_id="rc")
    assert layer.remove("nope") is False


def test_a_dropped_grant_stays_dropped_after_the_network_recovers() -> None:
    """Removing the fault restores bytes; it does not resurrect the promise."""
    spec = _spec("p", FaultKind.PARTITION, sender="ra", receiver="rb")
    layer = FaultLayer((spec,), local_robot_id="rc")
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DROP
    layer.remove("p")
    # What travels now is the *new* message handed to the layer afterwards.
    # Nothing in the layer retained, re-queued or will re-send the dropped one.
    assert layer.parked_count() == 0
    assert layer.health(0)["decisions"]["drop"] == 1


def test_active_faults_expose_their_window_and_invariant() -> None:
    layer = FaultLayer(
        (_spec("p", FaultKind.PARTITION, sender="ra", receiver="rb", duration_s=2.0),),
        local_robot_id="rc",
    )
    active = layer.active_faults(0)
    assert len(active) == 1
    assert active[0].silences_traffic is True
    assert active[0].from_ns == 0
    assert active[0].until_ns == 2_000_000_000
    assert "conserves exclusive zone authority" in active[0].expected_invariant
    assert layer.active_faults(2_000_000_000) == ()


def test_telemetry_channel_faults_do_not_touch_coordination_traffic() -> None:
    telemetry_fault = FaultSpec(
        fault_id="t",
        target=FaultTarget(channel=FaultChannel.TELEMETRY, kind=FaultKind.LOSS, sender="ra", receiver="rb"),
        duration_s=10.0,
        expected_invariant="observer loss creates a data gap, not a behaviour change",
    )
    layer = FaultLayer((telemetry_fault,), local_robot_id="rc")
    assert layer.apply_outbound("rb", _message("ra"), now_ns=0).kind is DecisionKind.DELIVER_AT
    assert layer.apply_inbound(_message("ra"), now_ns=0).kind is DecisionKind.DELIVER_AT


def test_park_overflow_is_a_counted_drop_not_unbounded_memory() -> None:
    layer = FaultLayer(
        (_spec("r", FaultKind.REORDER, sender="ra", params={"hold_ns": 1e9}),),
        local_robot_id="rc",
    )
    for seq in range(600):
        layer.apply_outbound("rb", _message("ra", seq=seq), now_ns=0)
    assert layer.parked_count() <= 512
    health = layer.health(0)
    assert health["park_overflow"] == 600 - 512
    assert health["decisions"]["drop"] == 600 - 512


def test_zero_or_negative_conversion_factor_is_rejected() -> None:
    with pytest.raises(ValueError, match="ns_per_sim_second must be positive"):
        FaultLayer(local_robot_id="rc", ns_per_sim_second=0.0)

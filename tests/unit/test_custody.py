"""Payload custody: idempotency, supervised recovery, and one credit per task.

The reviewer-facing claims in this file are:

* a duplicated pickup or delivery creates no second payload, no second reward and
  no second completion credit;
* a crashed owner's task becomes ``RECOVERY_REQUIRED`` and is **never** re-issued
  as a fresh job to another robot;
* recovery resumes the same payload under the same task id, with the original
  holder recorded.
"""

from __future__ import annotations

import pytest

from niharamesh.allocation.custody import (
    CustodyLedger,
    CustodyViolation,
    RecoveryPath,
)
from niharamesh.domain.task import CustodyState, TaskState


def claimed_ledger() -> CustodyLedger:
    ledger = CustodyLedger(run_id="run-1", epoch="e1")
    assert ledger.record_claim("T1", "r1", "r1-s1").accepted is True
    return ledger


def picked_up_ledger() -> CustodyLedger:
    ledger = claimed_ledger()
    effect = ledger.record_pickup("T1", "r1", "r1-s1", at_ns=1_000_000_000)
    assert effect.accepted is True
    assert effect.custody.state is CustodyState.ATTACHED
    return ledger


def in_transit_ledger() -> CustodyLedger:
    """Claimed, picked up and departed: the state a delivery must start from.

    ``TASK_TRANSITIONS`` has no ``PICKUP_CONFIRMED -> DELIVERED`` edge, so the
    departure step is real and the tests have to go through it.
    """
    ledger = picked_up_ledger()
    departed = ledger.record_departure("T1", robot="r1")
    assert departed.accepted is True
    assert departed.task_state is TaskState.IN_TRANSIT
    return ledger


# ----------------------------------------------------------------------
# duplicate pickup / delivery
# ----------------------------------------------------------------------


def test_duplicate_pickup_creates_no_second_payload() -> None:
    ledger = picked_up_ledger()
    assert ledger.payloads("T1") == ("T1#p1",)

    replay = ledger.record_pickup("T1", "r1", "r1-s1", at_ns=1_000_000_000)
    assert replay.applied is False
    assert replay.duplicate is True
    assert replay.violation is CustodyViolation.DUPLICATE_PICKUP
    assert replay.new_job_created is False
    assert "no second payload" in replay.detail
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.custody("T1").custody_version == 2
    assert ledger.audit() == ()

    # A *different* sequence number is a second-claim attempt, not a replay.
    second_claim = ledger.record_pickup("T1", "r1", "r1-s1", at_ns=1_000_000_000, transition_seq=2)
    assert second_claim.applied is False
    assert second_claim.violation is CustodyViolation.SECOND_PICKUP_ATTEMPT
    assert ledger.payloads("T1") == ("T1#p1",)


def test_a_second_robot_cannot_take_an_attached_payload() -> None:
    ledger = picked_up_ledger()
    thief = ledger.record_pickup("T1", "r2", "r2-s1", at_ns=2_000_000_000, transition_seq=5)
    assert thief.applied is False
    assert thief.violation is CustodyViolation.SECOND_HOLDER_REJECTED
    assert "recover(supervised=True)" in thief.detail
    assert ledger.custody("T1").holder == "r1"
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ("T1", CustodyViolation.SECOND_HOLDER_REJECTED.value) in ledger.violations()


def test_duplicate_delivery_grants_exactly_one_completion_credit() -> None:
    ledger = in_transit_ledger()
    assert ledger.credit_count() == 0
    assert ledger.has_credit("T1") is False

    first = ledger.record_delivery("T1", "r1", "r1-s1", at_ns=3_000_000_000)
    assert first.accepted is True
    assert first.completion_credit_granted is True
    assert first.new_job_created is False
    assert ledger.custody("T1").state is CustodyState.DELIVERED
    assert ledger.task_state("T1") is TaskState.DELIVERED
    assert ledger.payloads("T1") == ("T1#p1",)

    # The exact same message replayed.
    replay = ledger.record_delivery("T1", "r1", "r1-s1", at_ns=3_000_000_000)
    assert replay.applied is False
    assert replay.duplicate is True
    assert replay.violation is CustodyViolation.DUPLICATE_DELIVERY
    assert replay.completion_credit_granted is False
    assert ledger.credit_count() == 1

    # A different sequence number is still a duplicate delivery.
    resend = ledger.record_delivery("T1", "r1", "r1-s1", at_ns=3_000_000_000, transition_seq=9)
    assert resend.applied is False
    assert resend.violation is CustodyViolation.DUPLICATE_DELIVERY
    assert resend.completion_credit_granted is False
    assert ledger.credit_count() == 1

    # The credit can be claimed exactly once, ever.
    assert ledger.completion_credit("T1") is True
    assert ledger.completion_credit("T1") is False
    assert ledger.completion_credit("T1") is False
    assert ledger.credited_tasks() == ("T1",)
    assert ledger.credit_count() == 1
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.audit() == ()


def test_delivery_without_custody_is_refused_and_creates_no_credit() -> None:
    ledger = claimed_ledger()
    refused = ledger.record_delivery("T1", "r1", "r1-s1", at_ns=1)
    assert refused.applied is False
    assert refused.violation is CustodyViolation.DELIVERY_WITHOUT_CUSTODY
    assert refused.completion_credit_granted is False
    assert ledger.credit_count() == 0
    assert ledger.completion_credit("T1") is False

    someone_else = ledger.record_pickup("T1", "r2", "r2-s1", at_ns=1)
    assert someone_else.applied is True
    assert ledger.record_departure("T1", robot="r2").accepted is True
    assert ledger.record_delivery("T1", "r2", "r2-s1", at_ns=1).accepted is True
    assert ledger.credit_count() == 1
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.audit() == ()


# ----------------------------------------------------------------------
# crash and recovery
# ----------------------------------------------------------------------


def test_owner_crash_after_pickup_requires_recovery_and_issues_no_new_task() -> None:
    ledger = picked_up_ledger()
    failure = ledger.require_recovery("T1", "actuator fault during transit", at_ns=4_000_000_000)
    assert failure.applied is True
    assert failure.new_job_created is False
    assert failure.task_state is TaskState.RECOVERY_REQUIRED
    assert ledger.task_state("T1") is TaskState.RECOVERY_REQUIRED
    assert ledger.custody("T1").state is CustodyState.AWAITING_RECOVERY
    assert ledger.custody("T1").holder == "r1"
    assert ledger.custody("T1").holder_session == "r1-s1"
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.credited_tasks() == ()

    # A recovery-required task is not AVAILABLE and not CLAIMED: it cannot be
    # re-auctioned as if it were fresh work.
    assert ledger.task_state("T1") is not TaskState.AVAILABLE
    assert ledger.task_state("T1") is not TaskState.CLAIMED
    assert ledger.task_state("T1") is not TaskState.ABANDONED

    # Only one task id exists, and it is the original one.
    assert ledger.credit_count() == 0
    assert ledger.payloads("T1") == ("T1#p1",)


def test_another_robot_cannot_recover_without_supervision_and_no_new_task_appears() -> None:
    ledger = picked_up_ledger()
    ledger.require_recovery("T1", "link loss", at_ns=4_000_000_000)
    payload_before = ledger.payloads("T1")

    refused = ledger.recover("T1", "r2", "r2-s1")
    assert refused.resumed is False
    assert refused.path is RecoveryPath.REFUSED
    assert refused.previous_holder == "r1"
    assert refused.previous_holder_session == "r1-s1"
    assert refused.holder == "r1"
    assert refused.new_job_created is False
    assert "supervised recovery is required" in refused.detail
    assert "not re-issued" in refused.detail
    assert ("T1", CustodyViolation.RECOVERY_REQUIRES_SUPERVISION.value) in ledger.violations()
    # Nothing about the task changed: same payload, same task id, no credit.
    assert ledger.payloads("T1") == payload_before
    assert ledger.task_state("T1") is TaskState.RECOVERY_REQUIRED
    assert ledger.credit_count() == 0
    # And r2 cannot simply pick the payload up either.
    assert ledger.record_pickup("T1", "r2", "r2-s1", at_ns=5).violation is (
        CustodyViolation.SECOND_HOLDER_REJECTED
    )
    assert ledger.payloads("T1") == payload_before


def test_the_original_holder_resumes_custody_with_its_identity_recorded() -> None:
    ledger = in_transit_ledger()
    ledger.require_recovery("T1", "watchdog trip", at_ns=4_000_000_000)

    resumed = ledger.recover("T1", "r1", "r1-s1", transition_seq=2)
    assert resumed.resumed is True
    assert resumed.path is RecoveryPath.ORIGINAL_HOLDER
    assert resumed.previous_holder == "r1"
    assert resumed.previous_holder_session == "r1-s1"
    assert resumed.holder == "r1"
    assert resumed.holder_session == "r1-s1"
    assert resumed.custody.state is CustodyState.ATTACHED
    assert resumed.custody.picked_up_at_ns == 1_000_000_000
    assert resumed.task_state is TaskState.IN_TRANSIT
    assert resumed.custody_version == 4
    assert resumed.new_job_created is False
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.credit_count() == 0

    delivered = ledger.record_delivery("T1", "r1", "r1-s1", at_ns=6_000_000_000)
    assert delivered.accepted is True
    assert delivered.completion_credit_granted is True
    assert ledger.credit_count() == 1
    assert ledger.audit() == ()


def test_a_supervised_transfer_keeps_the_same_task_and_payload() -> None:
    ledger = in_transit_ledger()
    ledger.require_recovery("T1", "hardware failure", at_ns=4_000_000_000)

    supervised = ledger.recover("T1", "r3", "r3-s7", supervised=True, transition_seq=3)
    assert supervised.resumed is True
    assert supervised.path is RecoveryPath.SUPERVISED_TRANSFER
    assert supervised.previous_holder == "r1"
    assert supervised.previous_holder_session == "r1-s1"
    assert supervised.holder == "r3"
    assert supervised.holder_session == "r3-s7"
    assert supervised.new_job_created is False
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.custody("T1").picked_up_at_ns == 1_000_000_000
    assert ledger.task_state("T1") is TaskState.IN_TRANSIT
    # Still one task, one payload, one future credit.
    assert ledger.credit_count() == 0
    delivered = ledger.record_delivery("T1", "r3", "r3-s7", at_ns=7_000_000_000)
    assert delivered.completion_credit_granted is True
    assert ledger.credit_count() == 1


def test_recovering_without_a_recovery_requirement_is_refused() -> None:
    ledger = picked_up_ledger()
    refused = ledger.recover("T1", "r1", "r1-s1")
    assert refused.resumed is False
    assert refused.path is RecoveryPath.REFUSED
    assert "nothing to recover" in refused.detail
    assert ("T1", CustodyViolation.RECOVERY_WITHOUT_CUSTODY.value) in ledger.violations()
    assert ledger.custody("T1").state is CustodyState.ATTACHED


def test_recovery_without_an_attached_payload_is_refused() -> None:
    ledger = claimed_ledger()
    refused = ledger.require_recovery("T1", "crashed before pickup", at_ns=1)
    assert refused.applied is False
    assert refused.violation is CustodyViolation.RECOVERY_WITHOUT_CUSTODY
    assert "reason recorded: crashed before pickup" in refused.detail
    assert ledger.task_state("T1") is TaskState.CLAIMED


# ----------------------------------------------------------------------
# ordering and validation
# ----------------------------------------------------------------------


def test_pickup_before_claim_is_refused_by_the_task_state_machine() -> None:
    ledger = CustodyLedger(run_id="run-1", epoch="e1")
    refused = ledger.record_pickup("T1", "r1", "r1-s1", at_ns=1)
    assert refused.applied is False
    assert refused.violation is CustodyViolation.ILLEGAL_TASK_TRANSITION
    assert "pickup refused from task state available" in refused.detail
    assert ledger.payloads("T1") == ()
    assert ledger.credit_count() == 0


def test_delivery_after_delivery_never_double_counts_across_tasks() -> None:
    ledger = in_transit_ledger()
    ledger.record_delivery("T1", "r1", "r1-s1", at_ns=2)
    assert ledger.record_claim("T2", "r2", "r2-s1").accepted is True
    assert ledger.record_pickup("T2", "r2", "r2-s1", at_ns=3).accepted is True
    assert ledger.record_departure("T2", robot="r2").accepted is True
    ledger.record_delivery("T2", "r2", "r2-s1", at_ns=4)
    assert ledger.credit_count() == 2
    assert ledger.credited_tasks() == ("T1", "T2")
    assert ledger.payloads("T1") == ("T1#p1",)
    assert ledger.payloads("T2") == ("T2#p1",)
    assert ledger.completion_credit("T2") is True
    assert ledger.completion_credit("T2") is False
    assert ledger.audit() == ()


def test_invalid_identifiers_and_sequences_are_refused_loudly() -> None:
    with pytest.raises(ValueError, match="run_id"):
        CustodyLedger(run_id="", epoch="e1")
    ledger = claimed_ledger()
    with pytest.raises(ValueError, match="transition_seq"):
        ledger.record_pickup("T1", "r1", "r1-s1", at_ns=1, transition_seq=0)
    with pytest.raises(ValueError, match="transition_seq"):
        ledger.record_delivery("T1", "r1", "r1-s1", at_ns=1, transition_seq=0)


def test_unknown_tasks_read_as_unavailable_not_as_success() -> None:
    ledger = CustodyLedger(run_id="run-1", epoch="e1")
    assert ledger.task_state("never-seen") is TaskState.AVAILABLE
    assert ledger.custody("never-seen").state is CustodyState.AT_STATION
    assert ledger.custody("never-seen").holder is None
    assert ledger.payloads("never-seen") == ()
    assert ledger.has_credit("never-seen") is False
    assert ledger.completion_credit("never-seen") is False

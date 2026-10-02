"""Payload custody: possession, idempotency, and supervised recovery.

Three distinctions the types in :mod:`niharamesh.domain.task` already draw, kept
mechanical here:

* **logical ownership** belongs to the auction (:mod:`niharamesh.allocation.auction`);
* **physical custody** belongs to this ledger. A crashed owner's task keeps its
  custody and becomes ``RECOVERY_REQUIRED``. It is **never** re-awarded to a
  second robot as if it were a fresh job - :meth:`CustodyLedger.recover` always
  reports ``new_job_created=False`` and a test asserts it.
* **completion credit** is granted exactly once per task, ever.

Idempotency
-----------
Every mutation is keyed on ``(task_id, to_state, transition_seq)``, exactly as
:class:`~niharamesh.domain.task.TaskTransition` defines. Replaying the same key is
a no-op that reports ``duplicate=True`` and changes nothing: no second payload, no
second pickup, no second delivery reward, no second completion credit.

A *different* ``transition_seq`` attempting a second pickup is not a duplicate
message, it is a second-claim attempt. That is refused too - refused with an
explicit :class:`CustodyViolation` record rather than swallowed, because two
payloads for one task id would make every downstream number a lie.

Honesty
-------
``available``, ``awaiting_recovery`` and ``refused`` are distinct states and none
of them is reported as success. A refused recovery says why. A missing measurement
is never reported as zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from niharamesh.domain.task import (
    CustodyState,
    PayloadCustody,
    TaskState,
    is_legal_task_transition,
)

__all__ = [
    "CustodyEffect",
    "CustodyLedger",
    "CustodyViolation",
    "RecoveryOutcome",
    "RecoveryPath",
]


class CustodyViolation(StrEnum):
    """A refused attempt, recorded rather than swallowed."""

    SECOND_PICKUP_ATTEMPT = "second_pickup_attempt"
    DUPLICATE_PICKUP = "duplicate_pickup"
    DUPLICATE_DELIVERY = "duplicate_delivery"
    SECOND_HOLDER_REJECTED = "second_holder_rejected"
    DELIVERY_WITHOUT_CUSTODY = "delivery_without_custody"
    RECOVERY_WITHOUT_CUSTODY = "recovery_without_custody"
    RECOVERY_REQUIRES_SUPERVISION = "recovery_requires_supervision"
    ILLEGAL_TASK_TRANSITION = "illegal_task_transition"


class RecoveryPath(StrEnum):
    ORIGINAL_HOLDER = "original_holder"
    SUPERVISED_TRANSFER = "supervised_transfer"
    REFUSED = "refused"


#: Fast membership test so an ordinary event note is never recorded as a violation.
_VIOLATION_VALUES: frozenset[str] = frozenset(v.value for v in CustodyViolation)


@dataclass(frozen=True, slots=True)
class CustodyEffect:
    """The result of one attempted custody mutation."""

    task_id: str
    custody: PayloadCustody
    task_state: TaskState
    applied: bool
    duplicate: bool
    violation: CustodyViolation | None = None
    detail: str = ""
    payload_instance: str = ""
    completion_credit_granted: bool = False
    new_job_created: bool = False
    """Always False. Present so a caller can assert it rather than assume it."""

    @property
    def accepted(self) -> bool:
        return self.applied and not self.duplicate and self.violation is None


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """Result of resuming custody after an owner failure."""

    task_id: str
    resumed: bool
    path: RecoveryPath
    previous_holder: str | None
    previous_holder_session: str | None
    holder: str | None
    holder_session: str | None
    custody: PayloadCustody
    task_state: TaskState
    custody_version: int
    detail: str
    new_job_created: bool = False


class CustodyLedger:
    """Append-only custody record for one run epoch. Pure logic, no I/O."""

    def __init__(self, run_id: str, epoch: str) -> None:
        if not run_id or not epoch:
            raise ValueError("run_id and epoch are required")
        self.run_id = run_id
        self.epoch = epoch
        self._custody: dict[str, PayloadCustody] = {}
        self._task_state: dict[str, TaskState] = {}
        self._applied: set[tuple[str, str, int]] = set()
        self._payloads: dict[str, tuple[str, ...]] = {}
        self._credits: set[str] = set()
        self._claimed_credits: set[str] = set()
        self._violations: list[tuple[str, str]] = []
        self._events: list[str] = []

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def custody(self, task_id: str) -> PayloadCustody:
        return self._custody.get(task_id, PayloadCustody(task_id=task_id, state=CustodyState.AT_STATION))

    def task_state(self, task_id: str) -> TaskState:
        return self._task_state.get(task_id, TaskState.AVAILABLE)

    def payloads(self, task_id: str) -> tuple[str, ...]:
        """Payload instances ever created for *task_id*. Never longer than one."""
        return self._payloads.get(task_id, ())

    def credited_tasks(self) -> tuple[str, ...]:
        return tuple(sorted(self._credits))

    def credit_count(self) -> int:
        """Number of tasks holding a completion credit. One per delivered task."""
        return len(self._credits)

    def has_credit(self, task_id: str) -> bool:
        """Pure query. Does not consume the credit."""
        return task_id in self._credits

    def violations(self) -> tuple[tuple[str, str], ...]:
        return tuple(self._violations)

    def events(self) -> tuple[str, ...]:
        return tuple(self._events)

    def completion_credit(self, task_id: str) -> bool:
        """**Consume** the completion credit for *task_id*.

        Returns ``True`` exactly once per task, for the life of the ledger - the
        first claim of a credit that exists is granted, and every later claim is
        refused. A task with no credit returns ``False`` forever and never becomes
        creditable later: the credit is created only by the first accepted
        delivery, and a refused delivery creates none. Use :meth:`has_credit` for a
        non-consuming query.
        """
        if task_id in self._claimed_credits or task_id not in self._credits:
            return False
        self._claimed_credits.add(task_id)
        self._note(task_id, "completion credit claimed")
        return True

    # ------------------------------------------------------------------
    # mutations
    # ------------------------------------------------------------------

    def record_claim(
        self, task_id: str, robot: str, session: str, *, transition_seq: int = 1
    ) -> CustodyEffect:
        """Record the auction's award as a task-state claim.

        ``TASK_TRANSITIONS`` forbids ``AVAILABLE -> PICKUP_CONFIRMED`` directly, so
        the claim is a separate, explicit step. The auction owns *who* won; this
        method only records the resulting state so the pickup and delivery
        transitions stay legal. Custody stays ``AT_STATION``: the payload has not
        moved.
        """
        if transition_seq < 1:
            raise ValueError("transition_seq must be >= 1")
        current_state = self.task_state(task_id)
        current = self.custody(task_id)
        if not is_legal_task_transition(current_state, TaskState.CLAIMED):
            self._note(task_id, CustodyViolation.ILLEGAL_TASK_TRANSITION.value)
            return CustodyEffect(
                task_id=task_id,
                custody=current,
                task_state=current_state,
                applied=False,
                duplicate=False,
                violation=CustodyViolation.ILLEGAL_TASK_TRANSITION,
                detail=f"claim refused from task state {current_state.value}",
            )
        self._task_state[task_id] = TaskState.CLAIMED
        self._applied.add((task_id, TaskState.CLAIMED.value, transition_seq))
        self._note(task_id, f"claim {robot}@{session}")
        return CustodyEffect(
            task_id=task_id,
            custody=current,
            task_state=TaskState.CLAIMED,
            applied=True,
            duplicate=False,
        )

    def record_pickup(
        self,
        task_id: str,
        robot: str,
        session: str,
        at_ns: int,
        *,
        transition_seq: int = 1,
    ) -> CustodyEffect:
        """Attach the payload to *robot*. Idempotent on the transition key."""
        if transition_seq < 1:
            raise ValueError("transition_seq must be >= 1")
        key = (task_id, TaskState.PICKUP_CONFIRMED.value, transition_seq)
        current = self.custody(task_id)
        state = self.task_state(task_id)
        instance = self.payloads(task_id)[0] if self.payloads(task_id) else ""

        if (
            current.state in (CustodyState.ATTACHED, CustodyState.AWAITING_RECOVERY)
            and current.holder != robot
        ):
            self._note(task_id, CustodyViolation.SECOND_HOLDER_REJECTED.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.SECOND_HOLDER_REJECTED,
                (
                    f"{robot} may not take a payload held by {current.holder}; "
                    f"recover(supervised=True) is the only sanctioned path"
                ),
                payload_instance=instance,
            )

        if key in self._applied:
            self._note(task_id, CustodyViolation.DUPLICATE_PICKUP.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.DUPLICATE_PICKUP,
                f"pickup transition_seq {transition_seq} already applied for this task; "
                f"no second payload is created",
                duplicate=True,
                payload_instance=instance,
            )

        if current.state is CustodyState.ATTACHED:
            self._note(task_id, CustodyViolation.SECOND_PICKUP_ATTEMPT.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.SECOND_PICKUP_ATTEMPT,
                (
                    f"payload already attached to {current.holder}@{current.holder_session}; "
                    f"a second pickup creates no second payload"
                ),
                duplicate=True,
                payload_instance=instance,
            )

        if not is_legal_task_transition(state, TaskState.PICKUP_CONFIRMED):
            self._note(task_id, CustodyViolation.ILLEGAL_TASK_TRANSITION.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.ILLEGAL_TASK_TRANSITION,
                f"pickup refused from task state {state.value}",
                payload_instance=instance,
            )

        custody = PayloadCustody(
            task_id=task_id,
            holder=robot,
            holder_session=session,
            state=CustodyState.ATTACHED,
            custody_version=current.custody_version + 1,
            picked_up_at_ns=at_ns,
            delivered_at_ns=None,
        )
        self._custody[task_id] = custody
        self._task_state[task_id] = TaskState.PICKUP_CONFIRMED
        self._applied.add(key)
        new_instance = f"{task_id}#p1"
        self._payloads[task_id] = (new_instance,)
        self._note(task_id, f"pickup {robot}@{session}")
        return CustodyEffect(
            task_id=task_id,
            custody=custody,
            task_state=TaskState.PICKUP_CONFIRMED,
            applied=True,
            duplicate=False,
            payload_instance=new_instance,
            new_job_created=False,
        )

    def record_departure(self, task_id: str, *, robot: str = "", transition_seq: int = 1) -> CustodyEffect:
        """Leave the pickup station: ``PICKUP_CONFIRMED -> IN_TRANSIT``.

        A separate step because :data:`~niharamesh.domain.task.TASK_TRANSITIONS`
        does not allow ``PICKUP_CONFIRMED -> DELIVERED`` directly, and inventing
        that edge here would quietly disagree with the declared state machine.
        """
        current = self.custody(task_id)
        state = self.task_state(task_id)
        instance = self.payloads(task_id)[0] if self.payloads(task_id) else ""
        if current.state is not CustodyState.ATTACHED:
            self._note(task_id, CustodyViolation.RECOVERY_WITHOUT_CUSTODY.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.RECOVERY_WITHOUT_CUSTODY,
                f"no attached payload to move (custody {current.state.value})",
                payload_instance=instance,
            )
        if robot and current.holder != robot:
            self._note(task_id, CustodyViolation.SECOND_HOLDER_REJECTED.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.SECOND_HOLDER_REJECTED,
                f"{robot} does not hold the payload (holder {current.holder})",
                payload_instance=instance,
            )
        if not is_legal_task_transition(state, TaskState.IN_TRANSIT):
            self._note(task_id, CustodyViolation.ILLEGAL_TASK_TRANSITION.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.ILLEGAL_TASK_TRANSITION,
                f"departure refused from task state {state.value}",
                payload_instance=instance,
            )
        self._task_state[task_id] = TaskState.IN_TRANSIT
        self._applied.add((task_id, TaskState.IN_TRANSIT.value, transition_seq))
        self._note(task_id, f"departed by {current.holder}")
        return CustodyEffect(
            task_id=task_id,
            custody=current,
            task_state=TaskState.IN_TRANSIT,
            applied=True,
            duplicate=False,
            payload_instance=instance,
            new_job_created=False,
        )

    def record_delivery(
        self,
        task_id: str,
        robot: str,
        session: str,
        at_ns: int,
        *,
        transition_seq: int = 1,
    ) -> CustodyEffect:
        """Complete the task. Idempotent on the transition key *and* on credit."""
        if transition_seq < 1:
            raise ValueError("transition_seq must be >= 1")
        key = (task_id, TaskState.DELIVERED.value, transition_seq)
        current = self.custody(task_id)
        state = self.task_state(task_id)
        instance = self.payloads(task_id)[0] if self.payloads(task_id) else ""

        if key in self._applied or current.state is CustodyState.DELIVERED:
            self._note(task_id, CustodyViolation.DUPLICATE_DELIVERY.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.DUPLICATE_DELIVERY,
                (
                    f"task already delivered at version {current.custody_version}; "
                    f"no second delivery reward and no second completion credit"
                ),
                duplicate=True,
                payload_instance=instance,
            )

        if current.state is not CustodyState.ATTACHED or current.holder != robot:
            self._note(task_id, CustodyViolation.DELIVERY_WITHOUT_CUSTODY.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.DELIVERY_WITHOUT_CUSTODY,
                (
                    f"{robot} does not hold the payload for {task_id} "
                    f"(holder {current.holder}, custody {current.state.value})"
                ),
                payload_instance=instance,
            )

        if not is_legal_task_transition(state, TaskState.DELIVERED):
            self._note(task_id, CustodyViolation.ILLEGAL_TASK_TRANSITION.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.ILLEGAL_TASK_TRANSITION,
                f"delivery refused from task state {state.value}",
                payload_instance=instance,
            )

        custody = PayloadCustody(
            task_id=task_id,
            holder=robot,
            holder_session=session,
            state=CustodyState.DELIVERED,
            custody_version=current.custody_version + 1,
            picked_up_at_ns=current.picked_up_at_ns,
            delivered_at_ns=at_ns,
        )
        self._custody[task_id] = custody
        self._task_state[task_id] = TaskState.DELIVERED
        self._applied.add(key)
        credited = self._grant_credit(task_id)
        self._note(task_id, f"delivery {robot}@{session}")
        return CustodyEffect(
            task_id=task_id,
            custody=custody,
            task_state=TaskState.DELIVERED,
            applied=True,
            duplicate=False,
            payload_instance=instance,
            completion_credit_granted=credited,
            new_job_created=False,
        )

    def require_recovery(
        self, task_id: str, reason: str, *, at_ns: int = 0, transition_seq: int = 1
    ) -> CustodyEffect:
        """Owner failed while holding the payload. Custody is retained.

        The task becomes ``RECOVERY_REQUIRED`` - not ``AVAILABLE``, not ``ABANDONED``
        and certainly not a new task id. A robot that dies mid-delivery does not
        create work; it creates a recovery obligation.
        """
        current = self.custody(task_id)
        state = self.task_state(task_id)
        instance = self.payloads(task_id)[0] if self.payloads(task_id) else ""

        if current.state is not CustodyState.ATTACHED:
            self._note(task_id, CustodyViolation.RECOVERY_WITHOUT_CUSTODY.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.RECOVERY_WITHOUT_CUSTODY,
                (
                    f"no attached payload to recover (custody {current.state.value}); "
                    f"reason recorded: {reason}"
                ),
                payload_instance=instance,
            )

        if not is_legal_task_transition(state, TaskState.RECOVERY_REQUIRED):
            self._note(task_id, CustodyViolation.ILLEGAL_TASK_TRANSITION.value)
            return self._refused(
                task_id,
                current,
                state,
                CustodyViolation.ILLEGAL_TASK_TRANSITION,
                f"recovery refused from task state {state.value}",
                payload_instance=instance,
            )

        custody = PayloadCustody(
            task_id=task_id,
            holder=current.holder,
            holder_session=current.holder_session,
            state=CustodyState.AWAITING_RECOVERY,
            custody_version=current.custody_version + 1,
            picked_up_at_ns=current.picked_up_at_ns,
            delivered_at_ns=None,
        )
        self._custody[task_id] = custody
        self._task_state[task_id] = TaskState.RECOVERY_REQUIRED
        self._applied.add((task_id, TaskState.RECOVERY_REQUIRED.value, transition_seq))
        self._note(task_id, f"recovery required at {at_ns}: {reason}")
        return CustodyEffect(
            task_id=task_id,
            custody=custody,
            task_state=TaskState.RECOVERY_REQUIRED,
            applied=True,
            duplicate=False,
            detail=reason,
            payload_instance=instance,
            new_job_created=False,
        )

    def recover(
        self,
        task_id: str,
        robot: str,
        session: str,
        *,
        supervised: bool = False,
        transition_seq: int = 2,
    ) -> RecoveryOutcome:
        """Resume custody. The original holder may resume unaided.

        A different robot needs ``supervised=True``; otherwise the attempt is
        refused with :class:`CustodyViolation.RECOVERY_REQUIRES_SUPERVISION`.
        Either path resumes the *same* payload under the *same* task id. A fresh
        duplicate job is never created and ``new_job_created`` is always False.
        """
        current = self.custody(task_id)
        state = self.task_state(task_id)
        previous_holder = current.holder
        previous_session = current.holder_session

        if current.state is not CustodyState.AWAITING_RECOVERY:
            self._note(task_id, CustodyViolation.RECOVERY_WITHOUT_CUSTODY.value)
            return RecoveryOutcome(
                task_id=task_id,
                resumed=False,
                path=RecoveryPath.REFUSED,
                previous_holder=previous_holder,
                previous_holder_session=previous_session,
                holder=current.holder,
                holder_session=current.holder_session,
                custody=current,
                task_state=state,
                custody_version=current.custody_version,
                detail=(f"nothing to recover: custody state is {current.state.value}, not awaiting_recovery"),
            )

        same_holder = previous_holder == robot
        if not same_holder and not supervised:
            self._note(task_id, CustodyViolation.RECOVERY_REQUIRES_SUPERVISION.value)
            return RecoveryOutcome(
                task_id=task_id,
                resumed=False,
                path=RecoveryPath.REFUSED,
                previous_holder=previous_holder,
                previous_holder_session=previous_session,
                holder=previous_holder,
                holder_session=previous_session,
                custody=current,
                task_state=state,
                custody_version=current.custody_version,
                detail=(
                    f"{robot} is not the original holder {previous_holder}; an explicit "
                    f"supervised recovery is required. The task is not re-issued."
                ),
            )

        path = RecoveryPath.ORIGINAL_HOLDER if same_holder else RecoveryPath.SUPERVISED_TRANSFER
        custody = PayloadCustody(
            task_id=task_id,
            holder=robot,
            holder_session=session,
            state=CustodyState.ATTACHED,
            custody_version=current.custody_version + 1,
            picked_up_at_ns=current.picked_up_at_ns,
            delivered_at_ns=None,
        )
        self._custody[task_id] = custody
        self._task_state[task_id] = TaskState.IN_TRANSIT
        self._applied.add((task_id, TaskState.IN_TRANSIT.value, transition_seq))
        self._note(task_id, f"recovered by {robot}@{session} via {path.value}")
        return RecoveryOutcome(
            task_id=task_id,
            resumed=True,
            path=path,
            previous_holder=previous_holder,
            previous_holder_session=previous_session,
            holder=robot,
            holder_session=session,
            custody=custody,
            task_state=TaskState.IN_TRANSIT,
            custody_version=custody.custody_version,
            detail=f"{path.value}: custody resumed at version {custody.custody_version}",
            new_job_created=False,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _refused(
        self,
        task_id: str,
        custody: PayloadCustody,
        task_state: TaskState,
        violation: CustodyViolation,
        detail: str,
        *,
        duplicate: bool = False,
        payload_instance: str = "",
    ) -> CustodyEffect:
        return CustodyEffect(
            task_id=task_id,
            custody=custody,
            task_state=task_state,
            applied=False,
            duplicate=duplicate,
            violation=violation,
            detail=detail,
            payload_instance=payload_instance,
            completion_credit_granted=False,
            new_job_created=False,
        )

    def _grant_credit(self, task_id: str) -> bool:
        if task_id in self._credits:
            return False
        self._credits.add(task_id)
        return True

    def _note(self, task_id: str, event: str) -> None:
        self._events.append(f"{task_id}: {event}")
        if event in _VIOLATION_VALUES:
            self._violations.append((task_id, event))

    def audit(self) -> tuple[str, ...]:
        """Self-checks over the ledger. Empty means every invariant holds."""
        problems = [
            f"{task_id}: {len(instances)} payloads created for one task"
            for task_id, instances in sorted(self._payloads.items())
            if len(instances) > 1
        ]
        delivered = sorted(
            task_id for task_id, record in self._custody.items() if record.state is CustodyState.DELIVERED
        )
        for task_id in delivered:
            if task_id not in self._credits:
                problems.append(f"{task_id}: delivered without a completion credit")
        return tuple(problems)

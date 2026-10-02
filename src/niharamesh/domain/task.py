"""Task, ownership, custody and auction types.

Three distinctions are encoded in the types rather than in comments:

* **logical ownership** (:class:`TaskOwnership`) - which robot's plan includes
  the task. Purely informational to peers.
* **physical custody** (:class:`PayloadCustody`) - which robot actually holds the
  load. A crashed owner's task keeps custody and becomes ``RECOVERY_REQUIRED``;
  it is never re-awarded to a second robot as if it were a fresh job.
* **completion credit** - recorded once, idempotently, keyed by task id.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import IdStr, RobotId, TaskId
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "TASK_TRANSITIONS",
    "AllocationRound",
    "BidComponent",
    "CustodyState",
    "PayloadCustody",
    "Task",
    "TaskAward",
    "TaskBid",
    "TaskOwnership",
    "TaskOwnershipState",
    "TaskState",
    "TaskTransition",
    "is_legal_task_transition",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class TaskState(StrEnum):
    AVAILABLE = "available"
    CLAIMED = "claimed"
    PICKUP_CONFIRMED = "pickup_confirmed"
    IN_TRANSIT = "in_transit"
    DELIVERED = "delivered"
    RECOVERY_REQUIRED = "recovery_required"
    """Custody is held but the owning robot cannot continue. Not re-assignable
    as a fresh job; needs explicit recovery."""
    ABANDONED = "abandoned"
    """Structurally infeasible or cancelled. Never counts as a completion."""


#: The single source of truth for task lifecycle transitions.
TASK_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.AVAILABLE: frozenset({TaskState.CLAIMED, TaskState.ABANDONED}),
    TaskState.CLAIMED: frozenset(
        {TaskState.PICKUP_CONFIRMED, TaskState.AVAILABLE, TaskState.ABANDONED}
    ),
    TaskState.PICKUP_CONFIRMED: frozenset({TaskState.IN_TRANSIT, TaskState.RECOVERY_REQUIRED}),
    TaskState.IN_TRANSIT: frozenset(
        {TaskState.DELIVERED, TaskState.RECOVERY_REQUIRED, TaskState.ABANDONED}
    ),
    TaskState.DELIVERED: frozenset(),
    TaskState.RECOVERY_REQUIRED: frozenset(
        {TaskState.IN_TRANSIT, TaskState.DELIVERED, TaskState.ABANDONED}
    ),
    TaskState.ABANDONED: frozenset(),
}


def is_legal_task_transition(current: TaskState, nxt: TaskState) -> bool:
    """True when ``current -> nxt`` is defined. Same-state is always idempotent."""
    if current is nxt:
        return True
    return nxt in TASK_TRANSITIONS[current]


class TaskTransition(_Frozen):
    task_id: TaskId
    from_state: TaskState
    to_state: TaskState
    robot_id: RobotId
    robot_session: str = Field(max_length=40)
    #: Ownership version this transition was applied against. A stale version
    #: must be refused rather than applied.
    ownership_version: int = Field(ge=1)
    at_ns: int = Field(ge=0)
    reason: str = Field(default="", max_length=96)
    #: Idempotency key. Replaying the same (task, to_state, seq) is a no-op and
    #: must not create a second payload, pickup or completion credit.
    transition_seq: int = Field(ge=1)


class Task(_Frozen):
    """A transport job. Generated independently of assignment."""

    schema_version: str = SCHEMA_VERSION
    task_id: TaskId
    pickup_station_id: str = Field(max_length=40)
    drop_station_id: str = Field(max_length=40)
    release_at_s: Annotated[float, Field(ge=0.0, le=86400.0, allow_inf_nan=False)] = 0.0
    service_time_s: Annotated[float, Field(ge=0.0, le=3600.0, allow_inf_nan=False)] = 4.0
    required_capabilities: tuple[str, ...] = ()
    priority: Annotated[int, Field(ge=0, le=1000)] = 100
    weight_kg: Annotated[float, Field(ge=0.0, le=1000.0, allow_inf_nan=False)] = 5.0

    @model_validator(mode="after")
    def _distinct_stations(self) -> Self:
        if self.pickup_station_id == self.drop_station_id:
            raise ValueError("pickup and drop stations must differ")
        if not self.required_capabilities:
            raise ValueError("at least one required capability must be declared")
        return self

    @property
    def is_required_for_makespan(self) -> bool:
        """Only non-abandoned transport tasks count toward the headline metric."""
        return True


class TaskOwnershipState(StrEnum):
    UNOWNED = "unowned"
    RESERVED = "reserved"
    OWNED = "owned"
    RELEASED = "released"
    RECOVERY_REQUIRED = "recovery_required"


class TaskOwnership(_Frozen):
    """Logical ownership. Monotonic version; stale transitions are refused."""

    task_id: TaskId
    owner: RobotId | None = None
    owner_session: str | None = Field(default=None, max_length=40)
    ownership_version: Annotated[int, Field(ge=1)] = 1
    allocation_round: int = Field(ge=0)
    state: TaskOwnershipState = TaskOwnershipState.UNOWNED
    awarded_at_ns: int = Field(ge=0)
    #: Digest of the bid set that produced this award. Lets a peer recompute
    #: whether it agrees, instead of trusting an opaque verdict.
    bid_set_digest: str = Field(default="", max_length=64)
    evidence: str = Field(default="", max_length=120)


class CustodyState(StrEnum):
    AT_STATION = "at_station"
    ATTACHED = "attached"
    DELIVERED = "delivered"
    AWAITING_RECOVERY = "awaiting_recovery"


class PayloadCustody(_Frozen):
    """Physical possession. Never inferred from ownership."""

    task_id: TaskId
    holder: RobotId | None = None
    holder_session: str | None = Field(default=None, max_length=40)
    state: CustodyState = CustodyState.AT_STATION
    custody_version: Annotated[int, Field(ge=1)] = 1
    picked_up_at_ns: int | None = None
    delivered_at_ns: int | None = None


class BidComponent(_Frozen):
    """One declared term of a local bid. Shown verbatim in the UI."""

    name: str = Field(min_length=1, max_length=32)
    value: Annotated[float, Field(allow_inf_nan=False)]
    unit: str = Field(min_length=1, max_length=16)


class TaskBid(_Frozen):
    """Computed locally by one robot from its own available state only."""

    schema_version: str = SCHEMA_VERSION
    run_id: IdStr
    epoch: IdStr
    task_id: TaskId
    robot_id: RobotId
    robot_session: str = Field(max_length=40)
    round_id: IdStr
    #: Lower wins. Must be a deterministic function of the declared components.
    total_cost: Annotated[float, Field(allow_inf_nan=False)]
    components: tuple[BidComponent, ...] = ()
    feasible: bool = True
    infeasible_reason: str = Field(default="", max_length=96)
    at_ns: int = Field(ge=0)
    #: Bounded, used for deterministic tie-breaks after the digest.
    tie_break: Annotated[int, Field(ge=0, le=1_000_000_000)] = 0

    @model_validator(mode="after")
    def _components_present(self) -> Self:
        if self.feasible and not self.components:
            raise ValueError("a feasible bid must declare its cost components")
        if not self.feasible and not self.infeasible_reason:
            raise ValueError("an infeasible bid must state a reason")
        return self


class TaskAward(_Frozen):
    """Announcement of the outcome of one allocation round.

    Awarding is deterministic given the same bid set: lowest ``total_cost``
    among feasible bids, ties broken by ``tie_break`` then ``robot_id``. A robot
    computes this locally from received bids; no backend picks winners.
    """

    schema_version: str = SCHEMA_VERSION
    run_id: IdStr
    epoch: IdStr
    task_id: TaskId
    round_id: IdStr
    winner: RobotId
    winner_session: str = Field(max_length=40)
    ownership_version: int = Field(ge=1)
    bid_set_digest: str = Field(min_length=1, max_length=64)
    #: Explicit no-bid / insufficient-bid record, so silence is never ambiguous.
    explicit_no_bid: bool = False
    announced_by: RobotId = ""
    at_ns: int = Field(ge=0)


class AllocationRound(_Frozen):
    """Immutable round identity. Serialising rounds is what prevents a robot
    winning two auctions against the same availability."""

    round_id: IdStr
    run_id: IdStr
    epoch: IdStr
    index: int = Field(ge=0)
    released_task_ids: tuple[TaskId, ...] = ()
    #: Every bid must carry this. A bid for a different round is discarded.
    snapshot_digest: str = Field(min_length=1, max_length=64)
    opened_at_ns: int = Field(ge=0)
    #: If a peer is unreachable, capacity is *reserved* by this robot for the
    #: whole round rather than offered to a competing bid.
    reserve_capacity_on_timeout: bool = True

"""Local bid computation: a pure, deterministic function of one robot's beliefs.

The cost formula - the single place it is defined
--------------------------------------------------
::

    total_cost = quantise(
          weight_travel_time_s      * travel_time_s
        + weight_queue_delay_s      * queue_delay_s
        + weight_battery_cost_c     * battery_cost_c
        + weight_service_time_s     * service_time_s
        + weight_feasibility_risk_s * feasibility_risk_s
    )

All five weights live in :class:`CostModel` and nowhere else. Each one converts
its component into the same dimensionless scalar, in which *lower wins*:

``weight_travel_time_s``
    Identity. Travel is the dominant, most comparable quantity.
``weight_queue_delay_s``
    Identity, and deliberately the same as travel's: waiting for a zone is time,
    exactly like driving is. Merging the two would make the UI unable to explain
    *why* a bid lost.
``weight_battery_cost_c``
    ``250000``. Calibration: the declared
    :class:`~niharamesh.domain.config.BatteryModel` drains ``4e-5 C/m``, so a
    100 m round trip costs ``4e-3 C`` and contributes ``1000`` units - the same
    order as ``1000 s`` of travel. This is a *configured preference*, not a
    measured optimum, and it is stated here so a reader can disagree with it.
``weight_service_time_s``
    Identity. Station dwell is real fleet time.
``weight_feasibility_risk_s``
    Identity. See ``feasibility_risk_s`` below.

Components (shown verbatim in the UI, never summarised)
------------------------------------------------------
``travel_time_s``
    The planner's own estimate for ``robot -> pickup`` plus ``pickup -> drop``.
``queue_delay_s``
    ``max(0, release_at_s - now_s)`` plus one configured hold estimate per route
    zone that *this* robot believes another robot holds. Conservative by
    construction (AGENTS.md rule 4): a lost heartbeat or an expired claim does
    **not** zero a zone's contribution. A stale claim keeps its delay *and*
    gains a risk penalty.
``battery_cost_c``
    ``drain_per_metre_c * distance_m + drain_per_second_idle_c * busy_s +
    service_drain_c``, where ``busy_s = travel_time_s + queue_delay_s``.
``service_time_s``
    The task's declared ``service_time_s``.
``feasibility_risk_s``
    ``risk_per_unconfirmed_zone_s`` for every route zone this robot believes is
    held by a peer but cannot confirm (claim age over
    ``max_claim_age_ns``). This is the *risk* that the queue estimate rests on
    unverifiable evidence - distinct from the delay itself.

Determinism
-----------
There is no stochastic term anywhere in this module. A stochastic bid would make
``total_cost`` impossible to recompute from the announced components, which is
precisely the property that lets every robot recompute the award independently.
``BidStreams.planner_seed`` is accepted for interface symmetry with the
simulator's seeded per-component streams and recorded for provenance; it is
deliberately *not* mixed into the bid. So "same inputs and same seed" and "same
inputs and any seed" both give an identical :class:`TaskBid` - the second, weaker
claim is the one that matters.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from enum import StrEnum

from niharamesh.domain.config import BatteryModel
from niharamesh.domain.map import ZoneState
from niharamesh.domain.pose import Footprint, Pose2
from niharamesh.domain.task import BidComponent, Task, TaskBid
from niharamesh.domain.units import TimeDomain

__all__ = [
    "TOTAL_COST_FORMULA",
    "BidComponentValues",
    "BidRequest",
    "BidStreams",
    "CostModel",
    "TravelEstimate",
    "ZoneClaim",
    "compute_bid",
    "tie_break_of",
]

#: Human-readable statement of the formula, for the docs and the operator UI.
TOTAL_COST_FORMULA: str = (
    "total_cost = quantise(w_travel*travel_time_s + w_queue*queue_delay_s "
    "+ w_battery*battery_cost_c + w_service*service_time_s "
    "+ w_feasibility*feasibility_risk_s)"
)

#: ``TaskBid.tie_break`` bounds, mirrored from the domain contract.
_TIE_BREAK_MODULUS: int = 1_000_000_000


class BidInfeasibility(StrEnum):
    """Why a local bid is infeasible. Checked in this order; first match wins."""

    CAPACITY_HELD = "capacity_held"
    MISSING_CAPABILITY = "missing_capability"
    BATTERY_UNAVAILABLE = "battery_unavailable"
    BATTERY_BELOW_RESERVE = "battery_below_reserve"
    ZONE_FENCED = "zone_fenced"
    NO_ROUTE_TO_PICKUP = "no_route_to_pickup"
    NO_ROUTE_TO_DROP = "no_route_to_drop"


@dataclass(frozen=True, slots=True)
class ZoneClaim:
    """What *this* robot believes about one route zone.

    A claim, never ground truth. ``observed_at_ns`` and the caller's ``now_ns``
    must share one :class:`TimeDomain`; the caller is responsible for that and
    this record states the domain so a reader can check.
    """

    zone_id: str
    holder: str | None
    state: ZoneState
    observed_at_ns: int
    time_domain: TimeDomain = TimeDomain.LOGICAL

    def is_held_by_peer(self, robot_id: str) -> bool:
        return (
            self.state in (ZoneState.OCCUPIED, ZoneState.PROMISED)
            and self.holder is not None
            and self.holder != robot_id
        )


@dataclass(frozen=True, slots=True)
class TravelEstimate:
    """The robot's own planner estimate for the two legs of a task.

    ``to_pickup_reason`` / ``pickup_to_drop_reason`` carry the planner's
    explicit failure reason (``ok`` when the leg succeeded), so an infeasible
    bid can quote *why* instead of just refusing.
    """

    to_pickup_s: float
    pickup_to_drop_s: float
    to_pickup_distance_m: float
    pickup_to_drop_distance_m: float
    to_pickup_reason: str = "ok"
    pickup_to_drop_reason: str = "ok"

    def __post_init__(self) -> None:
        for name in ("to_pickup_s", "pickup_to_drop_s", "to_pickup_distance_m", "pickup_to_drop_distance_m"):
            if not math.isfinite(getattr(self, name)):
                raise ValueError(f"TravelEstimate.{name} must be finite")
        if self.to_pickup_s < 0.0 or self.pickup_to_drop_s < 0.0:
            raise ValueError("travel estimates must be non-negative")

    @property
    def ok(self) -> bool:
        return self.to_pickup_reason == "ok" and self.pickup_to_drop_reason == "ok"

    @property
    def total_s(self) -> float:
        return self.to_pickup_s + self.pickup_to_drop_s

    @property
    def total_distance_m(self) -> float:
        return self.to_pickup_distance_m + self.pickup_to_drop_distance_m


@dataclass(frozen=True, slots=True)
class BidRequest:
    """Everything one robot knows when it prices one task.

    Nothing here is another robot's truth: zone claims are published messages,
    travel is the robot's own planner output, and the battery number is the
    robot's own measurement.
    """

    robot_id: str
    robot_session: str
    run_id: str
    epoch: str
    task_id: str
    now_ns: int
    now_s: float
    pose: Pose2
    battery_fraction: float | None
    capabilities: tuple[str, ...]
    footprint: Footprint
    carrying_task_id: str | None
    travel: TravelEstimate
    zone_claims: tuple[ZoneClaim, ...] = ()
    time_domain: TimeDomain = TimeDomain.LOGICAL


@dataclass(frozen=True, slots=True)
class BidStreams:
    """Declared stream identity for one bid computation.

    ``planner_seed`` is recorded, never consumed: see the module docstring.
    """

    run_id: str
    epoch: str
    round_id: str
    planner_seed: int = 1

    def __post_init__(self) -> None:
        if self.planner_seed < 0:
            raise ValueError("planner_seed must be non-negative")


@dataclass(frozen=True, slots=True)
class BidComponentValues:
    """The five declared component values, before weighting."""

    travel_time_s: float
    queue_delay_s: float
    battery_cost_c: float
    service_time_s: float
    feasibility_risk_s: float


@dataclass(frozen=True, slots=True)
class CostModel:
    """Weights and tuning for one bid computation. All weights live here only."""

    weight_travel_time_s: float = 1.0
    weight_queue_delay_s: float = 1.0
    #: Calibrated so 100 m at the declared drain rate contributes ~1000 units.
    weight_battery_cost_c: float = 250_000.0
    weight_service_time_s: float = 1.0
    weight_feasibility_risk_s: float = 1.0
    #: Decimals the total is rounded to before it is announced. Rounding makes the
    #: bid-set digest independent of platform float formatting; 1e-6 is far
    #: below any meaningful cost difference and cannot reorder two bids except
    #: within 1e-6, which ``tie_break`` then resolves deterministically.
    quantise_decimals: int = 6
    #: Below this the robot declines rather than bidding to die on a charger.
    min_battery_reserve_fraction: float = 0.12
    #: Added per route zone believed held by a peer.
    zone_hold_overhead_s: float = 2.0
    #: A claim older than this can no longer be *confirmed*, so it gains risk.
    max_claim_age_ns: int = 3_000_000_000
    risk_per_unconfirmed_zone_s: float = 8.0
    battery: BatteryModel = field(default_factory=BatteryModel)

    def __post_init__(self) -> None:
        for name in (
            "weight_travel_time_s",
            "weight_queue_delay_s",
            "weight_battery_cost_c",
            "weight_service_time_s",
            "weight_feasibility_risk_s",
        ):
            if getattr(self, name) < 0.0:
                raise ValueError(f"{name} must be non-negative")
        if not (0.0 <= self.min_battery_reserve_fraction <= 1.0):
            raise ValueError("min_battery_reserve_fraction must be in [0, 1]")
        if self.quantise_decimals < 0 or self.quantise_decimals > 12:
            raise ValueError("quantise_decimals must be in [0, 12]")
        if self.max_claim_age_ns < 0:
            raise ValueError("max_claim_age_ns must be non-negative")

    @property
    def formula(self) -> str:
        return TOTAL_COST_FORMULA

    def total_cost(self, components: BidComponentValues) -> float:
        """The one implementation of the formula. See the module docstring."""
        raw = (
            self.weight_travel_time_s * components.travel_time_s
            + self.weight_queue_delay_s * components.queue_delay_s
            + self.weight_battery_cost_c * components.battery_cost_c
            + self.weight_service_time_s * components.service_time_s
            + self.weight_feasibility_risk_s * components.feasibility_risk_s
        )
        return round(raw, self.quantise_decimals)


def tie_break_of(round_id: str, task_id: str, robot_id: str) -> int:
    """Stable, coordination-free tie-break key in ``[0, 1e9)``.

    Derived from a hash of ``(round_id, task_id, robot_id)`` only. No robot needs
    to hear from any other robot to know its own value, and two robots in the same
    round compute the *same* key for the *same* triple - which is what lets the
    award rule "lowest cost, then lowest tie_break, then lowest robot_id" be
    evaluated identically everywhere without an election.
    """
    raw = f"{round_id}|{task_id}|{robot_id}".encode()
    return int(hashlib.sha256(raw).hexdigest()[:15], 16) % _TIE_BREAK_MODULUS


def compute_bid(
    task: Task,
    robot_state: BidRequest,
    cost_model: CostModel,
    streams: BidStreams,
) -> TaskBid:
    """Price one task for one robot. Pure, deterministic, locally computable."""
    if robot_state.task_id != task.task_id:
        raise ValueError("BidRequest.task_id does not match the Task being priced")
    if streams.round_id == "":
        raise ValueError("a bid must carry its allocation round id")
    if streams.run_id != robot_state.run_id or streams.epoch != robot_state.epoch:
        raise ValueError("BidStreams and BidRequest disagree about run/epoch")

    reason = _infeasibility(task, robot_state, cost_model)
    if reason is not None:
        return TaskBid(
            run_id=robot_state.run_id,
            epoch=robot_state.epoch,
            task_id=task.task_id,
            robot_id=robot_state.robot_id,
            robot_session=robot_state.robot_session,
            round_id=streams.round_id,
            total_cost=0.0,
            components=(),
            feasible=False,
            infeasible_reason=reason,
            at_ns=robot_state.now_ns,
            tie_break=tie_break_of(streams.round_id, task.task_id, robot_state.robot_id),
        )

    values = _components(task, robot_state, cost_model)
    total = cost_model.total_cost(values)
    return TaskBid(
        run_id=robot_state.run_id,
        epoch=robot_state.epoch,
        task_id=task.task_id,
        robot_id=robot_state.robot_id,
        robot_session=robot_state.robot_session,
        round_id=streams.round_id,
        total_cost=total,
        components=(
            BidComponent(name="travel_time_s", value=values.travel_time_s, unit="s"),
            BidComponent(name="queue_delay_s", value=values.queue_delay_s, unit="s"),
            BidComponent(name="battery_cost_c", value=values.battery_cost_c, unit="C"),
            BidComponent(name="service_time_s", value=values.service_time_s, unit="s"),
            BidComponent(name="feasibility", value=values.feasibility_risk_s, unit="s"),
        ),
        feasible=True,
        infeasible_reason="",
        at_ns=robot_state.now_ns,
        tie_break=tie_break_of(streams.round_id, task.task_id, robot_state.robot_id),
    )


def _infeasibility(task: Task, state: BidRequest, cost_model: CostModel) -> str | None:
    """First failing feasibility check, or ``None``. Order is part of the contract."""
    if state.carrying_task_id is not None and state.carrying_task_id != task.task_id:
        return f"{BidInfeasibility.CAPACITY_HELD.value}:{state.carrying_task_id}"
    missing = sorted(set(task.required_capabilities) - set(state.capabilities))
    if missing:
        return f"{BidInfeasibility.MISSING_CAPABILITY.value}:{'+'.join(missing)}"
    if state.battery_fraction is None:
        return BidInfeasibility.BATTERY_UNAVAILABLE.value
    if state.battery_fraction < cost_model.min_battery_reserve_fraction:
        return (
            f"{BidInfeasibility.BATTERY_BELOW_RESERVE.value}:"
            f"{state.battery_fraction:.3f}<{cost_model.min_battery_reserve_fraction:.3f}"
        )
    for claim in state.zone_claims:
        if claim.state is ZoneState.FENCED:
            return f"{BidInfeasibility.ZONE_FENCED.value}:{claim.zone_id}"
    if state.travel.to_pickup_reason != "ok":
        return f"{BidInfeasibility.NO_ROUTE_TO_PICKUP.value}:{state.travel.to_pickup_reason}"
    if state.travel.pickup_to_drop_reason != "ok":
        return f"{BidInfeasibility.NO_ROUTE_TO_DROP.value}:{state.travel.pickup_to_drop_reason}"
    return None


def _components(task: Task, state: BidRequest, cost_model: CostModel) -> BidComponentValues:
    travel_time_s = state.travel.total_s
    held_by_peer = [claim for claim in state.zone_claims if claim.is_held_by_peer(state.robot_id)]
    queue_delay_s = max(0.0, task.release_at_s - state.now_s)
    for _claim in held_by_peer:
        # Conservative occupancy (AGENTS.md rule 4): a claim that has gone stale,
        # lost its heartbeat or lost its release still costs the full estimate.
        queue_delay_s += cost_model.zone_hold_overhead_s
    unconfirmed = sum(
        1 for claim in held_by_peer if state.now_ns - claim.observed_at_ns > cost_model.max_claim_age_ns
    )
    feasibility_risk_s = cost_model.risk_per_unconfirmed_zone_s * unconfirmed
    busy_s = travel_time_s + queue_delay_s
    battery = cost_model.battery
    battery_cost_c = (
        battery.drain_per_metre_c * state.travel.total_distance_m
        + battery.drain_per_second_idle_c * busy_s
        + battery.service_drain_c
    )
    return BidComponentValues(
        travel_time_s=travel_time_s,
        queue_delay_s=queue_delay_s,
        battery_cost_c=battery_cost_c,
        service_time_s=task.service_time_s,
        feasibility_risk_s=feasibility_risk_s,
    )

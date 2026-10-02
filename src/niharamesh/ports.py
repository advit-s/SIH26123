"""Port interfaces that separate the system's responsibilities.

These are structural :class:`typing.Protocol` types. Implementations live in
``simulator``, ``transport``, ``planning``, ``coordination`` and ``persistence``;
nothing here imports them. This module is the reviewable boundary that makes the
authority split in ``AGENTS.md`` mechanically checkable.

The dependency direction is strictly:

    agent  ->  ports  <-  simulator / transport / persistence / planner
    api    ->  ports  <-  telemetry read models
    browser never appears here: it has no in-process access to truth.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Protocol, runtime_checkable

from niharamesh.domain.config import SimulationConfig
from niharamesh.domain.coordination import FreshnessClass, PeerMessage
from niharamesh.domain.identity import Membership, RobotIdentity, RobotSession
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import (
    ActuatorState,
    Footprint,
    MotionCommand,
    MotionState,
    PoseEstimate,
    StopReason,
    UncertaintyModel,
)
from niharamesh.domain.scenario import ScenarioSnapshot

__all__ = [
    "AuthorityJournal",
    "FreshnessVerdict",
    "Observation",
    "ObservationSink",
    "PeerTransport",
    "PlannerPort",
    "RangeRay",
    "SafetyDecision",
    "SafetyGatePort",
    "SensorObservation",
    "TaskAllocator",
    "WorldPort",
    "WorldTruth",
    "ZoneCoordinator",
]


class RangeRay:
    """One polar observation: a bearing, a measured distance and what it hit."""

    __slots__ = ("age_ns", "bearing_rad", "distance_m", "kind", "observed_at_ns")

    def __init__(
        self,
        bearing_rad: float,
        distance_m: float,
        kind: str,
        observed_at_ns: int,
        age_ns: int,
    ) -> None:
        self.bearing_rad = bearing_rad
        self.distance_m = distance_m
        self.kind = kind  # "obstacle" | "boundary" | "free" | "robot"
        self.observed_at_ns = observed_at_ns
        self.age_ns = age_ns

    def __repr__(self) -> str:
        return (
            f"RangeRay({self.bearing_rad:+.3f} rad, {self.distance_m:.3f} m, "
            f"{self.kind}, age {self.age_ns / 1e9:.3f} s)"
        )


class SensorObservation:
    """What a robot's sensors actually reported, with latency and age.

    ``observed_at_ns`` is when the measurement was taken; ``delivered_at_ns`` is
    when it reached the agent. The difference is modelled sensor latency, and
    the difference between ``delivered_at_ns`` and *now* is observation age.
    Both are in the world's declared time domain.
    """

    __slots__ = ("delivered_at_ns", "dropped", "observed_at_ns", "rays", "robot_id")

    def __init__(
        self,
        robot_id: str,
        observed_at_ns: int,
        delivered_at_ns: int,
        rays: Sequence[RangeRay],
        dropped: bool = False,
    ) -> None:
        self.robot_id = robot_id
        self.observed_at_ns = observed_at_ns
        self.delivered_at_ns = delivered_at_ns
        self.rays = tuple(rays)
        self.dropped = dropped

    def age_ns(self, now_ns: int) -> int:
        return max(0, now_ns - self.delivered_at_ns)

    def obstacles(self) -> tuple[RangeRay, ...]:
        return tuple(r for r in self.rays if r.kind in ("obstacle", "boundary", "robot"))


class Observation:
    """Everything one robot is allowed to know about itself and its world at one
    instant. Deliberately excludes other robots' true poses."""

    __slots__ = ("battery_fraction", "motion", "pose_estimate", "robot_id", "sensor", "sim_time_ns")

    def __init__(
        self,
        robot_id: str,
        pose_estimate: PoseEstimate,
        motion: MotionState,
        sensor: SensorObservation,
        battery_fraction: float | None,
        sim_time_ns: int,
    ) -> None:
        self.robot_id = robot_id
        self.pose_estimate = pose_estimate
        self.motion = motion
        self.sensor = sensor
        self.battery_fraction = battery_fraction
        self.sim_time_ns = sim_time_ns

    @property
    def localisation_age_ns(self) -> int:
        return max(0, self.sim_time_ns - self.pose_estimate.observed_at_ns)

    @property
    def localisation_stale(self) -> bool:
        """Configured staleness bound. Deliberately explicit, not implicit."""
        return self.localisation_age_ns > 1_000_000_000  # 1.0 s


class RobotTruth:
    """Evaluator/UI-only exact robot state. Must never reach an agent."""

    __slots__ = ("battery", "carrying", "omega", "robot_id", "theta", "v", "x", "y")

    def __init__(
        self,
        robot_id: str,
        x: float,
        y: float,
        theta: float,
        v: float,
        omega: float,
        battery: float,
        carrying: str | None,
    ) -> None:
        self.robot_id = robot_id
        self.x = x
        self.y = y
        self.theta = theta
        self.v = v
        self.omega = omega
        self.battery = battery
        self.carrying = carrying


class WorldTruth:
    """Exact simulator state. Used by the evaluator and the labelled debug
    overlay only. There is deliberately no accessor path from an agent to this."""

    __slots__ = ("dynamic_obstacles", "robots", "sim_time_ns", "stops")

    def __init__(
        self,
        sim_time_ns: int,
        robots: dict[str, RobotTruth],
        dynamic_obstacles: tuple[tuple[float, float, float, float, float], ...],
        stops: Sequence[object] = (),
    ) -> None:
        self.sim_time_ns = sim_time_ns
        self.robots = robots
        self.dynamic_obstacles = dynamic_obstacles
        self.stops = tuple(stops)


@runtime_checkable
class WorldPort(Protocol):
    """Physical world. Applies commands per declared physics.

    It must NOT plan routes, choose auction winners or grant intersections, and
    it must not refuse a colliding command - a collision is applied and then
    detected independently.
    """

    def reset(self, snapshot: ScenarioSnapshot) -> None: ...

    def step(self, dt_s: float) -> None: ...

    @property
    def sim_time_ns(self) -> int: ...

    def apply_command(self, command: MotionCommand) -> bool: ...

    def observe(self, robot_id: str) -> Observation: ...

    def truth(self) -> WorldTruth: ...

    @property
    def config(self) -> SimulationConfig: ...


@runtime_checkable
class PeerTransport(Protocol):
    """Direct agent-to-agent framed message exchange.

    The fault layer may delay/drop/duplicate/reorder declared channels. It must
    not make decisions for the agents, and it must not route traffic through the
    application API.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def send(self, peer_robot_id: str, message: PeerMessage) -> None: ...

    def inbox(self) -> AsyncIterator[PeerMessage]: ...

    @property
    def peers(self) -> tuple[str, ...]: ...


@runtime_checkable
class AuthorityJournal(Protocol):
    """Durable, append-only per-agent record of authority and custody promises.

    A promise must be durable *before* it is acknowledged. Missing or corrupt
    persistence enters stopped/unknown recovery, never normal operation.
    """

    def append(self, record_type: str, payload: dict[str, object]) -> str: ...

    def read_all(self) -> list[dict[str, object]]: ...

    def latest(self, record_type: str) -> dict[str, object] | None: ...

    def mark_corrupt(self, reason: str) -> None: ...

    @property
    def healthy(self) -> bool: ...

    def close(self) -> None: ...


@runtime_checkable
class ObservationSink(Protocol):
    """Recorder/observer. Reads state and events; holds no authority.

    Losing the observer must not stop the simulator clock or remove any agent's
    decision authority.
    """

    def emit(
        self, event_type: str, source: str, payload: dict[str, object], **kw: object
    ) -> None: ...

    def health(self) -> dict[str, object]: ...


class PlannerPort(Protocol):
    """Local spatial planner over the validated map. No global knowledge."""

    def plan(
        self, goal: tuple[float, float], footprint: Footprint
    ) -> tuple[tuple[float, float], ...] | None: ...

    def blocked_aware_plan(
        self,
        goal: tuple[float, float],
        footprint: Footprint,
        blocked: Sequence[tuple[float, float, float]],
    ) -> tuple[tuple[float, float], ...] | None: ...

    @property
    def plan_version(self) -> int: ...


class FreshnessVerdict:
    """Result of classifying one peer message.

    ``age_ns`` is a *conservative lower bound*: it never under-estimates how old
    a message is. ``UNKNOWN`` means the clock relationship was not established
    well enough to make any claim, which callers must treat as STALE for
    permission purposes while reporting it distinctly.
    """

    __slots__ = ("age_ns", "freshness", "reason", "uncertainty_ns")

    def __init__(
        self,
        freshness: FreshnessClass,
        age_ns: float | None,
        uncertainty_ns: int,
        reason: str,
    ) -> None:
        self.freshness = freshness
        self.age_ns = age_ns
        self.uncertainty_ns = uncertainty_ns
        self.reason = reason

    @property
    def usable(self) -> bool:
        return self.freshness is FreshnessClass.FRESH

    def __repr__(self) -> str:
        age = "unknown" if self.age_ns is None else f"{self.age_ns / 1e9:.3f}s"
        return f"FreshnessVerdict({self.freshness.value}, age={age}, reason={self.reason!r})"


@runtime_checkable
class ZoneCoordinator(Protocol):
    """Exclusive-zone authority. Owns nothing else."""

    def required_voters(self, requester: str) -> tuple[str, ...]: ...

    def required_set_digest(self, requester: str, zone_id: str) -> str: ...

    def may_enter(self, zone_id: str) -> bool: ...

    def why_blocked(self, zone_id: str) -> str: ...

    def begin_acquire(self, zone_id: str) -> None: ...

    def cancel(self, reason: str) -> None: ...

    def release(self) -> None: ...

    def handle(self, message: PeerMessage) -> None: ...

    def tick(self, now_ns: int) -> None: ...


@runtime_checkable
class TaskAllocator(Protocol):
    """Distributed auction. Bids are computed locally; no backend picks winners."""

    def bid(self, now_ns: int) -> list[object]: ...

    def handle(self, message: PeerMessage) -> None: ...

    def owned_task(self) -> str | None: ...

    def tick(self, now_ns: int) -> None: ...


class SafetyDecision:
    """Veto result from the safety gate. Always explicit and attributable."""

    __slots__ = ("evidence_age_ns", "limiting_constraint", "permitted", "reason")

    def __init__(
        self,
        permitted: bool,
        reason: StopReason,
        limiting_constraint: str = "",
        evidence_age_ns: float | None = None,
    ) -> None:
        self.permitted = permitted
        self.reason = reason
        self.limiting_constraint = limiting_constraint
        self.evidence_age_ns = evidence_age_ns

    def __bool__(self) -> bool:
        return self.permitted

    def __repr__(self) -> str:
        return (
            f"SafetyDecision(permitted={self.permitted}, reason={self.reason.value}, "
            f"constraint={self.limiting_constraint!r})"
        )


@runtime_checkable
class SafetyGatePort(Protocol):
    """Single veto point every actuator command passes through.

    It can veto planner, coordinator and operator-requested motion alike.
    """

    def evaluate(self, command: MotionCommand, now_ns: int) -> SafetyDecision: ...


SendFn = Callable[[PeerMessage], Awaitable[None]]
MembershipLike = Membership
IdentityLike = RobotIdentity
SessionLike = RobotSession
MapLike = WarehouseMap
UncertaintyLike = UncertaintyModel
ActuatorLike = ActuatorState

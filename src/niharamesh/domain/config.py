"""Policy, configuration and feature-flag contracts.

Two comparison dimensions must never be conflated:

* **coordination-only** - identical task assignments, identical routing policy;
  only the movement-coordination policy differs. This isolates the protocol.
* **end-to-end** - assignment and routing policies may differ, but the task
  set and initial conditions are identical.

Both use the same geometry, speed limits, sensing, task release schedule and
stopping conditions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "ActuatorModel",
    "AssignmentPolicy",
    "BatteryModel",
    "ComparisonMode",
    "CoordinationPolicy",
    "FeatureFlags",
    "ProtocolTiming",
    "RoutingPolicy",
    "SensorModel",
    "SimulationConfig",
    "StoppingBudget",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CoordinationPolicy(StrEnum):
    """The two policies that must sit behind identical interfaces."""

    STOP_AND_WAIT = "stop_and_wait"
    """Frozen baseline. A robot entering a constrained passage stops completely
    at the stop line and waits until the passage is physically clear, then
    proceeds. Same limits, same safety gate, same sensing. Not sabotaged."""

    CANONICAL_SEQUENTIAL = "canonical_sequential"
    """The proposed freshness-aware policy: exclusive zones acquired by
    canonical sequential grant protocol with conservative occupancy retention."""


class AssignmentPolicy(StrEnum):
    NONE = "none"
    """Fixed assignment from the scenario. Used for coordination-only comparison."""

    LOCAL_AUCTION = "local_auction"
    """Round-serialised local bids over a common task feed."""


class RoutingPolicy(StrEnum):
    SHORTEST = "shortest"
    BLOCKED_AWARE = "blocked_aware"
    """Replans around a reported obstruction instead of waiting, with a
    documented cost comparison."""

    TEMPORAL_SIPP_APPROX = "temporal_sipp_approx"
    """Simplified space-time reservation planning. Honestly named approximate."""


class ComparisonMode(StrEnum):
    COORDINATION_ONLY = "coordination_only"
    END_TO_END = "end_to_end"


class FeatureFlags(_Frozen):
    """Ablation switches. Unsafe research variants are namespaced so they can
    never be enabled by accident in a physical deployment."""

    temporal_planning: bool = False
    blocked_aware_routing: bool = True
    task_reassignment: bool = True
    fairness_aware_priority: bool = True
    #: Ablation: expire occupancy on a timer instead of requiring a reconciled
    #: release. Research-only. Records ``unsafe_research_variant=True``.
    timer_expiry_occupancy: bool = False
    #: Ablation: skip the local safety gate entirely. Research-only.
    disable_safety_gate: bool = False

    unsafe_research_variant: bool = False
    """Derived, read-only: true when any safety-weakening ablation is on."""

    unsafe_flags: tuple[str, ...] = ()
    """Derived, read-only: the names of the safety-weakening ablations that are on."""

    @model_validator(mode="before")
    @classmethod
    def _derive_research_flags(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        unsafe: list[str] = []
        if data.get("timer_expiry_occupancy"):
            unsafe.append("timer_expiry_occupancy")
        if data.get("disable_safety_gate"):
            unsafe.append("disable_safety_gate")
        merged = {**data, "unsafe_research_variant": bool(unsafe), "unsafe_flags": tuple(unsafe)}
        return merged

    def physical_actuation_permitted(self) -> bool:
        """No ablation that weakens safety may ever gate physical actuation."""
        return not self.unsafe_research_variant


class StoppingBudget(_Frozen):
    """Derived stopping distance parameters.

    These are *configured assumptions* for a low-speed simulation. They are not
    certified real-world limits and are never presented as a safety guarantee.

    Example from the brief at v=0.4 m/s, t_r=0.30 s, a=0.8 m/s^2, margin=0.10 m:
    reaction 0.12 m + braking 0.10 m + margin 0.10 m = 0.32 m.
    """

    max_speed_mps: Annotated[float, Field(gt=0.0, le=2.0, allow_inf_nan=False)] = 0.4
    reaction_time_s: Annotated[float, Field(ge=0.0, le=5.0, allow_inf_nan=False)] = 0.30
    braking_decel_mps2: Annotated[float, Field(gt=0.0, le=10.0, allow_inf_nan=False)] = 0.8
    extra_margin_m: Annotated[float, Field(ge=0.0, le=5.0, allow_inf_nan=False)] = 0.10

    @property
    def reaction_distance_m(self) -> float:
        return self.max_speed_mps * self.reaction_time_s

    @property
    def braking_distance_m(self) -> float:
        return (self.max_speed_mps**2) / (2.0 * self.braking_decel_mps2)

    @property
    def total_distance_m(self) -> float:
        return self.reaction_distance_m + self.braking_distance_m + self.extra_margin_m


class SensorModel(_Frozen):
    """Declared sensing limits and noise. Every value is a simulation
    configuration, labelled as such wherever it is displayed."""

    range_m: Annotated[float, Field(gt=0.1, le=100.0, allow_inf_nan=False)] = 3.0
    field_of_view_rad: Annotated[float, Field(gt=0.1, le=2.0 * 3.14159, allow_inf_nan=False)] = (
        4.712
    )
    angular_resolution_rad: Annotated[float, Field(gt=0.001, le=0.5, allow_inf_nan=False)] = 0.0436
    observation_latency_s: Annotated[float, Field(ge=0.0, le=10.0, allow_inf_nan=False)] = 0.1
    position_sigma_m: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.02
    heading_sigma_rad: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.01
    dropout_probability: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.02
    range_noise_m: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.02


class ActuatorModel(_Frozen):
    max_linear_mps: Annotated[float, Field(gt=0.0, le=2.0, allow_inf_nan=False)] = 0.4
    max_angular_radps: Annotated[float, Field(gt=0.0, le=3.0, allow_inf_nan=False)] = 1.0
    accel_mps2: Annotated[float, Field(gt=0.0, le=5.0, allow_inf_nan=False)] = 0.5
    decel_mps2: Annotated[float, Field(gt=0.0, le=10.0, allow_inf_nan=False)] = 0.8
    angular_accel_radps2: Annotated[float, Field(gt=0.0, le=10.0, allow_inf_nan=False)] = 1.5
    #: A command older than this triggers watchdog braking at ``decel_mps2``.
    command_ttl_s: Annotated[float, Field(gt=0.01, le=10.0, allow_inf_nan=False)] = 0.4


class BatteryModel(_Frozen):
    """Declared battery model. UI must state ``source`` alongside any value."""

    drain_per_metre_c: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.00004
    drain_per_second_idle_c: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.000008
    service_drain_c: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.0005
    start_fraction: Annotated[float, Field(ge=0.01, le=1.0, allow_inf_nan=False)] = 0.92
    source: str = Field(default="simulated", max_length=16)


class ProtocolTiming(_Frozen):
    """All protocol deadlines live in the agent's declared time domain."""

    heartbeat_period_s: Annotated[float, Field(gt=0.01, le=10.0, allow_inf_nan=False)] = 0.2
    freshness_horizon_s: Annotated[float, Field(gt=0.01, le=10.0, allow_inf_nan=False)] = 1.0
    #: Advertised intent validity. Beyond this, an intent is STALE even if the
    #: transport delivered it reliably.
    intent_validity_s: Annotated[float, Field(gt=0.05, le=30.0, allow_inf_nan=False)] = 3.0
    solicit_timeout_s: Annotated[float, Field(gt=0.01, le=10.0, allow_inf_nan=False)] = 0.8
    cancel_timeout_s: Annotated[float, Field(gt=0.01, le=10.0, allow_inf_nan=False)] = 1.5
    release_timeout_s: Annotated[float, Field(gt=0.01, le=30.0, allow_inf_nan=False)] = 5.0
    state_publish_period_s: Annotated[float, Field(gt=0.01, le=5.0, allow_inf_nan=False)] = 0.1
    intent_publish_period_s: Annotated[float, Field(gt=0.01, le=5.0, allow_inf_nan=False)] = 0.5
    #: Queue service order is FIFO by arrival; this only breaks ties in arrival.
    queue_tiebreak_s: Annotated[float, Field(ge=0.0, le=5.0, allow_inf_nan=False)] = 0.0
    control_period_s: Annotated[float, Field(gt=0.005, le=1.0, allow_inf_nan=False)] = 0.05


class SimulationConfig(_Frozen):
    schema_version: str = SCHEMA_VERSION
    physics_step_hz: Annotated[int, Field(ge=5, le=200)] = 20
    state_publish_hz: Annotated[int, Field(ge=1, le=60)] = 10
    actuator: ActuatorModel = ActuatorModel()
    sensor: SensorModel = SensorModel()
    battery: BatteryModel = BatteryModel()
    stopping: StoppingBudget = StoppingBudget()
    protocol: ProtocolTiming = ProtocolTiming()
    features: FeatureFlags = FeatureFlags()
    #: Physical actuation is disabled by default, always.
    physical_actuation_enabled: bool = False

    @model_validator(mode="after")
    def _step_covers_publish(self) -> SimulationConfig:
        if self.state_publish_hz > self.physics_step_hz:
            raise ValueError("state_publish_hz cannot exceed physics_step_hz")
        if self.physical_actuation_enabled and not self.features.physical_actuation_permitted():
            raise ValueError("physical actuation cannot be enabled with an unsafe research flag")
        return self

    @property
    def dt_s(self) -> float:
        return 1.0 / self.physics_step_hz

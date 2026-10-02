"""Pose, motion, footprint and battery value objects (wire + geometry bridge)."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.geometry import OrientedBox, Pose
from niharamesh.domain.units import TimeDomain, require_finite, wrap_angle

__all__ = [
    "ActuatorState",
    "BatterySource",
    "BatteryState",
    "FiniteFloat",
    "Footprint",
    "MotionCommand",
    "MotionState",
    "Pose2",
    "PoseEstimate",
    "StopReason",
    "UncertaintyModel",
]

FiniteFloat = Annotated[float, Field(allow_inf_nan=False, ge=-1.0e9, le=1.0e9)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Pose2(_Frozen):
    """Planar pose in metres/radians. Distinct from a *measured* pose estimate."""

    x: FiniteFloat
    y: FiniteFloat
    theta: FiniteFloat

    @model_validator(mode="after")
    def _wrap(self) -> Self:
        object.__setattr__(self, "theta", wrap_angle(self.theta))
        return self

    def to_geometry(self) -> Pose:
        return Pose(self.x, self.y, self.theta)

    @classmethod
    def from_geometry(cls, pose: Pose) -> Self:
        return cls(x=pose.x, y=pose.y, theta=pose.theta)

    def distance_to(self, other: Pose2) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


class UncertaintyModel(_Frozen):
    """Declared localisation uncertainty. Never implicit.

    ``kind`` must be reported so a consumer can tell a modelled sigma from a
    hard bound. ``sigma_m`` is the 1-sigma standard deviation of planar
    position error; ``sigma_rad`` the 1-sigma of heading error.
    """

    kind: Literal["gaussian_sigma", "hard_bound", "unknown"]
    sigma_m: FiniteFloat = 0.0
    sigma_rad: FiniteFloat = 0.0
    max_m: FiniteFloat = 0.0
    source: str = Field(default="configured-assumption", max_length=64)


class PoseEstimate(_Frozen):
    """An estimate with its observation time and uncertainty.

    This is deliberately *not* a pose: an estimate can be stale, and the system
    must be able to represent "last known pose, age 3.2 s, uncertain".
    """

    map_id: str = Field(max_length=64)
    frame_id: str = Field(default="warehouse", max_length=32)
    pose: Pose2
    observed_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    uncertainty: UncertaintyModel
    #: True when the estimate came from a fused localiser rather than a single
    #: fix. Purely descriptive; never used for authority.
    fused: bool = False

    @property
    def is_uncertain(self) -> bool:
        return self.uncertainty.kind != "unknown"


class Footprint(_Frozen):
    """Finite robot geometry, plus payload overhang when carrying.

    ``length_m``/``width_m`` describe the chassis. ``payload_length_m`` and
    ``payload_width_m`` describe the largest carried load. ``payload_offset_m``
    is the distance from the chassis centre to the payload centre along the
    chassis ``+x`` axis (positive = front overhang).
    """

    length_m: Annotated[float, Field(gt=0.0, le=5.0, allow_inf_nan=False)]
    width_m: Annotated[float, Field(gt=0.0, le=5.0, allow_inf_nan=False)]
    payload_length_m: Annotated[float, Field(ge=0.0, le=5.0, allow_inf_nan=False)] = 0.0
    payload_width_m: Annotated[float, Field(ge=0.0, le=5.0, allow_inf_nan=False)] = 0.0
    payload_offset_m: Annotated[float, Field(ge=-1.0, le=1.0, allow_inf_nan=False)] = 0.0
    #: Radius of the turning circle used as the conservative planning inflation.
    turning_radius_m: Annotated[float, Field(gt=0.0, le=5.0, allow_inf_nan=False)] = 0.35

    @model_validator(mode="after")
    def _payload_fits_sense(self) -> Self:
        if self.payload_length_m > 0.0 and self.payload_width_m <= 0.0:
            raise ValueError("payload_width_m must be positive when payload_length_m > 0")
        if self.payload_length_m > self.length_m + 0.001:
            raise ValueError(
                "payload_length_m exceeds chassis length; use payload_offset_m instead"
            )
        return self

    @property
    def chassis(self) -> OrientedBox:
        return OrientedBox(0.0, 0.0, 0.0, self.length_m, self.width_m)

    @property
    def half_diagonal_m(self) -> float:
        return math.hypot(self.length_m, self.width_m) / 2.0

    def body_at(self, pose: Pose) -> OrientedBox:
        return OrientedBox(pose.x, pose.y, pose.theta, self.length_m, self.width_m)

    def payload_at(self, pose: Pose) -> OrientedBox | None:
        if self.payload_length_m <= 0.0:
            return None
        cx = pose.x + self.payload_offset_m * math.cos(pose.theta)
        cy = pose.y + self.payload_offset_m * math.sin(pose.theta)
        return OrientedBox(cx, cy, pose.theta, self.payload_length_m, self.payload_width_m)

    def occupied_boxes(self, pose: Pose) -> tuple[OrientedBox, ...]:
        """Chassis plus payload when carried. Used by collision + clearance."""
        payload = self.payload_at(pose)
        return (self.body_at(pose),) if payload is None else (self.body_at(pose), payload)

    def clearance_radius_m(self) -> float:
        """Conservative radius enclosing the chassis or a carried payload.

        Used for planner inflation and coarse broad-phase rejection. Exact
        oriented-box tests are used everywhere it actually matters.
        """
        chassis_r = self.half_diagonal_m
        if self.payload_length_m <= 0.0:
            return chassis_r
        payload_r = math.hypot(self.payload_length_m, self.payload_width_m) / 2.0
        return math.hypot(self.payload_offset_m + payload_r, chassis_r)


class ActuatorState(StrEnum):
    """Physical state of the actuator chain. Never inferred from a flag."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    BRAKING = "braking"
    WATCHDOG_BRAKING = "watchdog_braking"
    ESTOP = "estop"
    FAULT = "fault"


class StopReason(StrEnum):
    """Why motion is or is not happening. Every stop is attributed."""

    NONE = "none"
    COMMAND_EXPIRED = "command_expired"
    SAFETY_GATE_VETO = "safety_gate_veto"
    ZONE_AUTHORITY_MISSING = "zone_authority_missing"
    FRESHNESS_UNCERTAIN = "freshness_uncertain"
    OBSTACLE_IN_PATH = "obstacle_in_path"
    STALE_LOCALISATION = "stale_localisation"
    CONTROL_LOOP_STALLED = "control_loop_stalled"
    OPERATOR_REQUEST = "operator_request"
    SCHEDULED_STOP = "scheduled_stop"
    WORKLOAD_COMPLETE = "workload_complete"
    CRASH_RECOVERY = "crash_recovery"
    ACTUATOR_FAULT = "actuator_fault"


class MotionState(_Frozen):
    """Observed motion, the command that was asked for, and the actuator story."""

    linear_velocity_mps: FiniteFloat = 0.0
    angular_velocity_radps: FiniteFloat = 0.0
    commanded_linear_mps: FiniteFloat = 0.0
    commanded_angular_radps: FiniteFloat = 0.0
    command_seq: int = Field(default=0, ge=0)
    command_expires_at_ns: int | None = None
    actuator: ActuatorState = ActuatorState.DISABLED
    stop_reason: StopReason = StopReason.NONE
    #: Physical actuation is disabled by default and must be explicitly enabled.
    actuation_enabled: bool = False

    @model_validator(mode="after")
    def _finite_all(self) -> Self:
        for name in (
            "linear_velocity_mps",
            "angular_velocity_radps",
            "commanded_linear_mps",
            "commanded_angular_radps",
        ):
            require_finite(getattr(self, name), field=f"MotionState.{name}")
        return self

    @property
    def moving(self) -> bool:
        return abs(self.linear_velocity_mps) > 1e-3 or abs(self.angular_velocity_radps) > 1e-3


class BatterySource(StrEnum):
    """Provenance of a battery number. Never guessed."""

    MEASURED = "measured"
    SIMULATED = "simulated"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class BatteryState(_Frozen):
    source: BatterySource
    fraction: Annotated[float, Field(ge=-0.05, le=1.05, allow_inf_nan=False)] | None = None
    estimated_range_m: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None = None
    drain_model: str | None = Field(default=None, max_length=80)


class MotionCommand(_Frozen):
    """The only thing an agent may hand to the world.

    ``expires_at_ns`` is in the agent's declared ``time_domain``; the world
    compares it against the clock of that same domain. Expiry causes *braking at
    the configured deceleration*, never an instantaneous stop.
    """

    robot_id: str = Field(max_length=40)
    command_seq: int = Field(ge=0)
    linear_mps: Annotated[float, Field(ge=-2.0, le=2.0, allow_inf_nan=False)]
    angular_radps: Annotated[float, Field(ge=-3.0, le=3.0, allow_inf_nan=False)]
    issued_at_ns: int = Field(ge=0)
    expires_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    hold_position: bool = False

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.expires_at_ns < self.issued_at_ns:
            raise ValueError("expires_at_ns must be >= issued_at_ns")
        return self

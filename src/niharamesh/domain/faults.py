"""Fault injection contracts.

Two channels exist and they are never conflated:

``coordination``
    agent-to-agent protocol traffic. Delaying or partitioning this is a genuine
    decentralisation experiment.

``telemetry``
    observer/dashboard data. Breaking it creates a data gap, not a change in
    robot behaviour. Robots must keep deciding normally.

A fault never makes a decision for an agent. It only delays, drops, duplicates,
reorders or withholds bytes, or acts on a process/object.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import IdStr, RobotId, ZoneId
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "FaultChannel",
    "FaultExpectation",
    "FaultKind",
    "FaultSpec",
    "FaultState",
    "FaultTarget",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FaultChannel(StrEnum):
    COORDINATION = "coordination"
    TELEMETRY = "telemetry"


class FaultKind(StrEnum):
    DELAY = "delay"
    LOSS = "loss"
    DUPLICATE = "duplicate"
    REORDER = "reorder"
    PARTITION = "partition"
    """Unidirectional or bidirectional cut of a declared channel."""

    CLOCK_SKEW = "clock_skew"
    """Perturbs the *declared* offset estimate, never the real clock."""

    OBSTACLE_INSERT = "obstacle_insert"
    OBSTACLE_REMOVE = "obstacle_remove"
    SENSOR_STALE = "sensor_stale"
    SENSOR_DROPOUT = "sensor_dropout"
    CONTROL_OVERLOAD = "control_overload"
    """Delays the agent's control loop so commands expire and the watchdog brakes."""

    PROCESS_CRASH = "process_crash"
    PROCESS_RESTART = "process_restart"
    JOURNAL_CORRUPT = "journal_corrupt"
    """Simulates missing/corrupt durable persistence -> stopped/unknown recovery."""


class FaultState(StrEnum):
    SCHEDULED = "scheduled"
    ACTIVE = "active"
    ELAPSED = "elapsed"
    CANCELLED = "cancelled"
    FAILED = "failed"


type FaultParam = float | int | bool | str


class FaultTarget(_Frozen):
    """Explicit sender/receiver targeting. A fault with no target is invalid -
    the brief requires directed fault injection, not a global toggle."""

    channel: FaultChannel
    kind: FaultKind
    #: When set, only traffic from this sender is affected.
    sender: RobotId | None = None
    #: When set, only traffic to this receiver is affected.
    receiver: RobotId | None = None
    zone_id: ZoneId | None = None
    #: For object-targeted faults (crash, obstacle, sensor).
    robot: RobotId | None = None
    #: For obstacle faults.
    position: tuple[float, float] | None = None
    #: For message-kind faults.
    message_kind: str | None = Field(default=None, max_length=32)


class FaultSpec(_Frozen):
    schema_version: str = SCHEMA_VERSION
    fault_id: IdStr
    target: FaultTarget
    #: Simulation seconds from the declared run start.
    start_at_s: Annotated[float, Field(ge=0.0, le=86400.0, allow_inf_nan=False)] = 0.0
    duration_s: Annotated[float, Field(ge=0.0, le=86400.0, allow_inf_nan=False)] = 1.0
    #: Deterministic seed for the stochastic behaviour of this fault. Required
    #: so a run is reproducible from its manifest.
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 0
    params: dict[str, FaultParam] = Field(default_factory=dict)
    """Fault parameters. Numbers, booleans or short identifiers (e.g. the id of
    an obstacle a fault replaces). Never nested structures."""
    #: What must remain true while the fault is active. Surfaced in the UI so a
    #: run that violates it is obviously wrong rather than quietly plausible.
    expected_invariant: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _target_is_specific(self) -> Self:
        t = self.target
        directed_kinds = {
            FaultKind.DELAY,
            FaultKind.LOSS,
            FaultKind.DUPLICATE,
            FaultKind.REORDER,
            FaultKind.PARTITION,
        }
        if (
            t.channel is FaultChannel.COORDINATION
            and t.kind in directed_kinds
            and t.sender is None
            and t.receiver is None
        ):
            raise ValueError("channel faults must name a sender or a receiver")
        if (
            t.kind
            in {
                FaultKind.PROCESS_CRASH,
                FaultKind.PROCESS_RESTART,
                FaultKind.JOURNAL_CORRUPT,
            }
            and t.robot is None
        ):
            raise ValueError(f"{t.kind.value} requires target.robot")
        if t.kind in {FaultKind.OBSTACLE_INSERT, FaultKind.OBSTACLE_REMOVE} and t.position is None:
            raise ValueError(f"{t.kind.value} requires target.position")
        return self

    @property
    def end_at_s(self) -> float:
        return self.start_at_s + self.duration_s


class FaultExpectation(_Frozen):
    """The invariant a specific fault is meant to exercise, evaluated after
    the run against exported evidence rather than asserted in prose."""

    fault_id: IdStr
    invariant: str
    scope: str = Field(default="run", max_length=32)
    verified_by: str = Field(min_length=1, max_length=120)


class FaultRecord(_Frozen):
    """A runtime observation of a fault's state. Manual injections become
    timestamped run events; scheduled ones are part of the scenario snapshot."""

    fault_id: IdStr
    state: FaultState
    started_at_ns: int = Field(ge=0)
    ended_at_ns: int | None = None
    #: True when the fault was injected by an operator rather than scheduled.
    manual: bool = False
    injected_by: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=160)
    digest: str = Field(default="", max_length=64)

    @staticmethod
    def spec_digest(spec: FaultSpec) -> str:
        return hashlib.sha256(
            json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:32]

"""Durable event log, run manifest, metrics and run result contracts.

The event log is append-only. Authority and evaluation events are never dropped;
only replaceable high-rate telemetry may be decimated, and any such drop is
recorded as an explicit gap.
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import IdStr, RobotId, RunId
from niharamesh.domain.units import SCHEMA_VERSION, TimeDomain

__all__ = [
    "DomainEvent",
    "EnvironmentRecord",
    "EventCategory",
    "EventSeverity",
    "MetricAvailability",
    "MetricDefinition",
    "MetricValue",
    "RecordingGap",
    "ReplayIndex",
    "RunManifest",
    "RunOutcome",
    "RunResult",
    "RunState",
    "TelemetrySample",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class EventCategory(StrEnum):
    #: Authority transitions. Must never be dropped.
    AUTHORITY = "authority"
    #: Evaluation evidence. Must never be dropped.
    EVALUATION = "evaluation"
    #: Task lifecycle and custody. Must never be dropped.
    TASK = "task"
    #: Planning / route decisions (explainability).
    PLANNING = "planning"
    #: Safety-gate decisions.
    SAFETY = "safety"
    #: Fault injection state changes.
    FAULT = "fault"
    #: Operator commands: requested / acknowledged / applied / observed.
    COMMAND = "command"
    #: Process lifecycle.
    LIFECYCLE = "lifecycle"
    #: Replaceable high-rate telemetry. May be decimated; gaps recorded.
    TELEMETRY = "telemetry"


#: Categories whose loss invalidates claims of complete evidence.
DURABLE_CATEGORIES: frozenset[EventCategory] = frozenset(
    {
        EventCategory.AUTHORITY,
        EventCategory.EVALUATION,
        EventCategory.TASK,
        EventCategory.SAFETY,
        EventCategory.FAULT,
        EventCategory.COMMAND,
    }
)


class EventSeverity(StrEnum):
    INFO = "info"
    ATTENTION = "attention"
    FAULT = "fault"
    VIOLATION = "violation"
    """An invariant was broken. Always visible, never filtered out."""


class DomainEvent(_Frozen):
    """One durable record. Append-only, globally sequenced by ``seq``."""

    schema_version: str = SCHEMA_VERSION
    run_id: RunId
    #: Observer-assigned total order. Stable across reconnects.
    seq: int = Field(ge=0)
    source: str = Field(max_length=64)
    source_session: str = Field(default="", max_length=40)
    #: Sender's clock at the moment of the event, with its domain.
    event_time_ns: int = Field(ge=0)
    time_domain: TimeDomain
    #: Observer's clock at receipt. Different domain from ``event_time_ns``.
    receive_time_ns: int = Field(ge=0)
    receive_time_domain: TimeDomain
    #: Simulation time in seconds since the declared run start.
    sim_time_s: Annotated[float, Field(ge=-1.0, allow_inf_nan=False)] = 0.0
    type: str = Field(min_length=1, max_length=64)
    category: EventCategory
    severity: EventSeverity = EventSeverity.INFO
    reason: str = Field(default="", max_length=240)
    correlation_id: str = Field(default="", max_length=64)
    #: Optional entity references used by the UI's filtered timeline.
    robot_id: RobotId | None = None
    task_id: str | None = Field(default=None, max_length=40)
    zone_id: str | None = Field(default=None, max_length=40)
    fault_id: str | None = Field(default=None, max_length=64)
    payload: dict[str, object] = Field(default_factory=dict)

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]


class TelemetrySample(_Frozen):
    """Replaceable high-rate sample. Never an authority or evaluation record."""

    run_id: RunId
    robot_id: RobotId
    sample_index: int = Field(ge=0)
    sim_time_s: Annotated[float, Field(ge=-1.0, allow_inf_nan=False)]
    x: float
    y: float
    theta: float
    linear_mps: float
    angular_radps: float
    battery_fraction: Annotated[float, Field(ge=-0.05, le=1.05, allow_inf_nan=False)] | None = None
    stop_reason: str = Field(default="none", max_length=32)


class RecordingGap(_Frozen):
    """An explicit, visible hole in durable evidence.

    A run with an unresolved gap in a durable category is marked incomplete and
    its affected metrics are excluded from claims requiring complete evidence.
    """

    run_id: RunId
    category: EventCategory
    from_seq: int = Field(ge=0)
    to_seq: int = Field(ge=0)
    sim_time_from_s: float
    sim_time_to_s: float
    cause: str = Field(max_length=160)
    recovered: bool = False

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.to_seq < self.from_seq:
            raise ValueError("gap to_seq must be >= from_seq")
        return self


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    UNSAFE = "unsafe"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    @property
    def terminal(self) -> bool:
        return self in {
            RunState.COMPLETED,
            RunState.UNSAFE,
            RunState.FAILED,
            RunState.TIMED_OUT,
            RunState.CANCELLED,
        }


class RunOutcome(StrEnum):
    SUCCESS = "success"
    UNSAFE = "unsafe"
    DEGRADED = "degraded"
    """Completed safely but with faults/interventions. Not eligible to be
    presented as a clean comparison point without being stated."""
    EXPECTED_SAFE_STOP = "expected_safe_stop"
    """A diagnostic scenario whose correct result is a safe, explained stop."""
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"


class EnvironmentRecord(_Frozen):
    """What the run actually executed on. Recorded, never guessed."""

    os_name: str
    os_version: str
    machine: str
    python_version: str
    cpu_model: str = ""
    cpu_count: int = 0
    accelerator: str = ""
    #: Monotonic start/stop of the harness, for real-process wall-clock claims.
    wall_start_utc_ns: int = 0
    wall_end_utc_ns: int = 0
    docker: bool = False

    @staticmethod
    def capture(docker: bool = False) -> EnvironmentRecord:
        import os

        model = ""
        try:
            if sys.platform == "win32":  # pragma: no cover - platform specific
                import ctypes

                buf = ctypes.create_string_buffer(256)
                ctypes.windll.kernel32.GetWindowsComputerNameA(ctypes.byref(buf), None)
                model = buf.value.decode(errors="replace")
        except Exception:
            model = ""
        return EnvironmentRecord(
            os_name=platform.system(),
            os_version=platform.release(),
            machine=platform.machine(),
            python_version=platform.python_version(),
            cpu_model=model or platform.processor(),
            cpu_count=os.cpu_count() or 0,
            docker=docker,
        )


class RunManifest(_Frozen):
    """Everything needed to reproduce and audit one run."""

    schema_version: str = SCHEMA_VERSION
    run_id: RunId
    created_utc_ns: int = Field(ge=0)
    #: Git identity at launch. ``dirty`` is recorded honestly, never cleaned.
    source_revision: str = Field(max_length=64)
    source_dirty: bool = True
    #: Immutable hashes of every input that defines the experiment.
    scenario_digest: str = Field(min_length=1, max_length=64)
    scenario_revision: int = Field(ge=1)
    map_digest: str = Field(min_length=1, max_length=64)
    config_digest: str = Field(min_length=1, max_length=64)
    schema_version_id: str = SCHEMA_VERSION
    mode: Literal["deterministic", "processes"]
    coordination_policy: str
    assignment_policy: str
    routing_policy: str
    comparison_mode: str
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    #: The two actuation switches, recorded separately because they answer different
    #: questions and because an artefact that omitted them could not tell a
    #: simulated run from one that energised a real drive train.
    #:
    #: ``simulated_actuation_enabled`` is a physics question -- may the declared
    #: actuator model integrate accepted commands. ``physical_actuation_enabled`` is
    #: a hardware-boundary question -- may a command reach a real drive train. The
    #: cockpit reads the second one and renders a warning band, so this field is a
    #: safety signal on the artefact, not a formality.
    simulated_actuation_enabled: bool = True
    physical_actuation_enabled: bool = False
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)]
    robot_ids: tuple[RobotId, ...] = ()
    task_count: int = Field(ge=0)
    fault_ids: tuple[IdStr, ...] = ()
    #: Declared run deadline in simulation seconds. A run past this is
    #: ``timed_out``, never silently "completed".
    max_sim_time_s: Annotated[float, Field(gt=0.0, le=86400.0, allow_inf_nan=False)] = 900.0
    environment: EnvironmentRecord = Field(default_factory=EnvironmentRecord.capture)
    #: Expected-failure diagnostic runs are labelled here and are excluded from
    #: successful-completion comparisons.
    expected_failure_scenario: bool = False
    expected_failure_reason: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=400)

    @model_validator(mode="after")
    def _unique_robots(self) -> Self:
        if len(set(self.robot_ids)) != len(self.robot_ids):
            raise ValueError("duplicate robot id in manifest")
        return self

    @property
    def benchmark_eligible_seed(self) -> bool:
        return not self.expected_failure_scenario


class MetricAvailability(StrEnum):
    MEASURED = "measured"
    UNAVAILABLE = "unavailable"
    """Not collected in this run. Never coerced to zero."""

    EXCLUDED = "excluded"
    """Collected but excluded from this aggregate (e.g. incomplete evidence)."""


class MetricDefinition(_Frozen):
    """A metric is defined once and referenced everywhere."""

    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,48}$")
    label: str = Field(max_length=80)
    unit: str = Field(max_length=16)
    description: str = Field(max_length=400)
    #: Higher is better / lower is better / neutral.
    direction: Literal["higher_is_better", "lower_is_better", "neutral"] = "neutral"
    #: False for metrics excluded from the headline (e.g. diagnostics).
    headline: bool = False
    #: True when a zero value must not be read as a proof (collision count).
    zero_is_not_proof: bool = False

    @property
    def registry_key(self) -> str:
        return self.key


class MetricValue(_Frozen):
    key: str
    availability: MetricAvailability
    value: float | None = None
    sample_count: int | None = Field(default=None, ge=0)
    note: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.availability is MetricAvailability.MEASURED and self.value is None:
            raise ValueError(f"metric {self.key!r} marked measured without a value")
        if self.availability is not MetricAvailability.MEASURED and self.value is not None:
            raise ValueError(f"metric {self.key!r} marked {self.availability} must not carry a value")
        return self

    @classmethod
    def measured(
        cls, key: str, value: float, *, sample_count: int | None = None, note: str = ""
    ) -> MetricValue:
        return cls(
            key=key,
            availability=MetricAvailability.MEASURED,
            value=value,
            sample_count=sample_count,
            note=note,
        )

    @classmethod
    def unavailable(cls, key: str, note: str) -> MetricValue:
        return cls(key=key, availability=MetricAvailability.UNAVAILABLE, note=note)


class RunResult(_Frozen):
    """The outcome of one run, always including failures and timeouts."""

    run_id: RunId
    state: RunState
    outcome: RunOutcome
    manifest_digest: str = Field(min_length=1, max_length=64)
    sim_duration_s: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    #: Elapsed from the declared common run start to delivery of every required
    #: task. ``None`` unless the workload actually completed.
    makespan_s: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None = None
    tasks_total: int = Field(ge=0)
    tasks_completed: int = Field(ge=0)
    collisions: int = Field(ge=0)
    min_clearance_m: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None = None
    metrics: tuple[MetricValue, ...] = ()
    gaps: tuple[RecordingGap, ...] = ()
    stop_reason: str = Field(default="", max_length=200)
    events_path: str = Field(default="", max_length=400)
    digest: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.tasks_completed > self.tasks_total:
            raise ValueError("tasks_completed cannot exceed tasks_total")
        if (
            self.makespan_s is not None
            and self.outcome is RunOutcome.SUCCESS
            and self.tasks_completed < self.tasks_total
        ):
            raise ValueError("success outcome requires every required task delivered")
        return self

    @property
    def eligible_for_completion_comparison(self) -> bool:
        """Only clean, complete, safe, fully evidenced runs."""
        return (
            self.outcome is RunOutcome.SUCCESS
            and self.collisions == 0
            and self.tasks_completed == self.tasks_total
            and self.makespan_s is not None
            and not any(not g.recovered and g.category in DURABLE_CATEGORIES for g in self.gaps)
        )

    def metric(self, key: str) -> MetricValue:
        for m in self.metrics:
            if m.key == key:
                return m
        return MetricValue.unavailable(key, "not collected in this run")


class ReplayIndex(_Frozen):
    """Rebuilds the world at any timestamp. Never fabricates future state."""

    run_id: RunId
    events_path: str
    event_count: int = Field(ge=0)
    first_sim_time_s: float
    last_sim_time_s: float
    #: Category histogram, so the UI can show what evidence exists.
    categories: dict[str, int] = Field(default_factory=dict)
    gaps: tuple[RecordingGap, ...] = ()
    complete: bool = True
    notes: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _index_consistent(self) -> Self:
        expected_complete = not any(not g.recovered and g.category in DURABLE_CATEGORIES for g in self.gaps)
        if self.complete and not expected_complete:
            raise ValueError("replay marked complete despite an unrecovered durable gap")
        return self


def compute_digest(value: object) -> str:
    """Stable sha256 digest of any canonically JSON-serialisable value.

    Models are dumped with sorted keys; plain dicts/lists work directly.
    """
    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()[:32]


class RunDescriptor(_Frozen):
    """Lightweight listing record for the experiments matrix."""

    run_id: RunId
    state: RunState
    outcome: RunOutcome
    coordination_policy: str
    scenario_revision: int
    seed: int
    created_utc_ns: int
    sim_duration_s: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    tasks_total: int = Field(ge=0)
    tasks_completed: int = Field(ge=0)
    collisions: int = Field(ge=0)
    makespan_s: Annotated[float, Field(ge=0.0, allow_inf_nan=False)] | None = None
    evidence_complete: bool = True
    note: str = Field(default="", max_length=160)
    idempotency_key: str = Field(default="", max_length=64)


SelfRef = Self

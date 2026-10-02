"""Scenario: the immutable, hashable bundle that defines one experiment.

A scenario references a map, a task feed, scheduled faults, robot starts,
policy selection and seeds. Launching a run freezes a snapshot of it: editing
the scenario library afterwards must never change an experiment already run.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.config import (
    AssignmentPolicy,
    ComparisonMode,
    CoordinationPolicy,
    RoutingPolicy,
    SimulationConfig,
)
from niharamesh.domain.faults import FaultSpec
from niharamesh.domain.identity import RobotIdentity
from niharamesh.domain.ids import IdStr, ShortIdStr, TaskId
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import FiniteFloat, Pose2
from niharamesh.domain.task import Task
from niharamesh.domain.units import SCHEMA_VERSION

__all__ = [
    "IntentDescription",
    "RobotStart",
    "RunPolicy",
    "Scenario",
    "ScenarioSnapshot",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RobotStart(_Frozen):
    robot_id: str = Field(max_length=40)
    pose: Pose2
    #: Optional fixed assignment for coordination-only comparisons.
    assigned_task_id: TaskId | None = None
    #: Initial custody, for recovery scenarios.
    holding_task_id: TaskId | None = None

    @model_validator(mode="after")
    def _holding_implies_assignment(self) -> Self:
        if self.holding_task_id is not None and self.assigned_task_id != self.holding_task_id:
            raise ValueError("a robot holding a payload must be assigned that same task")
        return self


class IntentDescription(_Frozen):
    """Human-readable description of the experiment, shown in the UI."""

    goal: str = Field(min_length=1, max_length=240)
    #: What the operator should watch for.
    expect: str = Field(default="", max_length=400)
    #: Diagnostic scenarios whose *correct* result is a safe explained stop.
    expected_failure_reason: str = Field(default="", max_length=200)


class RunPolicy(_Frozen):
    coordination: CoordinationPolicy = CoordinationPolicy.CANONICAL_SEQUENTIAL
    assignment: AssignmentPolicy = AssignmentPolicy.LOCAL_AUCTION
    routing: RoutingPolicy = RoutingPolicy.BLOCKED_AWARE
    comparison_mode: ComparisonMode = ComparisonMode.COORDINATION_ONLY
    #: Seeds one component's random stream separately so a change in one
    #: component's noise does not perturb every other stream.
    planner_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 1
    sensor_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 2
    fault_seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 3


class Scenario(_Frozen):
    """The authored experiment. Validated separately (structure vs feasibility)."""

    schema_version: str = SCHEMA_VERSION
    scenario_id: ShortIdStr
    revision: Annotated[int, Field(ge=1)] = 1
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=400)
    kind: Literal["nominal", "fault", "diagnostic", "benchmark"] = "nominal"
    intent: IntentDescription
    map: WarehouseMap
    robots: tuple[RobotIdentity, ...]
    starts: tuple[RobotStart, ...]
    tasks: tuple[Task, ...] = ()
    faults: tuple[FaultSpec, ...] = ()
    policy: RunPolicy = RunPolicy()
    simulation: SimulationConfig = SimulationConfig()
    seed: Annotated[int, Field(ge=0, le=2**31 - 1)] = 20260101
    max_sim_time_s: Annotated[float, Field(gt=1.0, le=86400.0, allow_inf_nan=False)] = 900.0

    @model_validator(mode="after")
    def _structural(self) -> Self:
        if not self.robots:
            raise ValueError("scenario must declare at least one robot")
        if len(self.robots) < 3:
            # Not a structural failure: the harness requires >= 3 robots in
            # multi-robot mode, and validation reports this as a warning with
            # an actionable message.
            pass
        robot_ids = [r.robot_id for r in self.robots]
        if len(set(robot_ids)) != len(robot_ids):
            raise ValueError("duplicate robot_id in scenario.robots")
        start_ids = [s.robot_id for s in self.starts]
        if len(set(start_ids)) != len(start_ids):
            raise ValueError("duplicate robot_id in scenario.starts")
        if set(start_ids) != set(robot_ids):
            raise ValueError("every declared robot needs exactly one start")
        task_ids = [t.task_id for t in self.tasks]
        if len(set(task_ids)) != len(task_ids):
            raise ValueError("duplicate task_id")
        fault_ids = [f.fault_id for f in self.faults]
        if len(set(fault_ids)) != len(fault_ids):
            raise ValueError("duplicate fault_id")
        for start in self.starts:
            for ref in (start.assigned_task_id, start.holding_task_id):
                if ref is not None and ref not in task_ids:
                    raise ValueError(f"start {start.robot_id!r} references unknown task {ref!r}")
        return self

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()[:32]

    def robot(self, robot_id: str) -> RobotIdentity:
        for r in self.robots:
            if r.robot_id == robot_id:
                return r
        raise KeyError(f"unknown robot {robot_id!r}")

    def start_of(self, robot_id: str) -> RobotStart:
        for s in self.starts:
            if s.robot_id == robot_id:
                return s
        raise KeyError(f"no start for robot {robot_id!r}")

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.task_id == task_id:
                return t
        raise KeyError(f"unknown task {task_id!r}")


class ScenarioSnapshot(_Frozen):
    """A frozen copy handed to a launched run.

    Contains the full scenario plus the digests that must be quoted by every
    result derived from it. Never mutated after creation.
    """

    snapshot_id: IdStr
    created_utc_ns: int = Field(ge=0)
    scenario: Scenario
    scenario_digest: str = Field(min_length=1, max_length=64)
    map_digest: str = Field(min_length=1, max_length=64)
    config_digest: str = Field(min_length=1, max_length=64)
    fault_digest: str = Field(min_length=1, max_length=64)
    task_digest: str = Field(min_length=1, max_length=64)

    @staticmethod
    def freeze(scenario: Scenario, *, created_utc_ns: int) -> ScenarioSnapshot:
        from niharamesh.domain.telemetry import compute_digest

        return ScenarioSnapshot(
            snapshot_id=scenario.digest()[:16],
            created_utc_ns=created_utc_ns,
            scenario=scenario,
            scenario_digest=scenario.digest(),
            map_digest=scenario.map.digest(),
            config_digest=compute_digest(scenario.simulation),
            fault_digest=compute_digest(tuple(f.model_dump(mode="json") for f in scenario.faults)),
            task_digest=compute_digest(tuple(t.model_dump(mode="json") for t in scenario.tasks)),
        )

    def with_policy(self, policy: RunPolicy) -> ScenarioSnapshot:
        """Produce a new snapshot with a different policy.

        Returns a new object. The original is never mutated, which is what keeps
        a baseline run's evidence honest when the candidate is retuned.
        """
        from niharamesh.domain.telemetry import compute_digest

        new_scenario = self.scenario.model_copy(update={"policy": policy})
        return ScenarioSnapshot(
            snapshot_id=self.snapshot_id,
            created_utc_ns=self.created_utc_ns,
            scenario=new_scenario,
            scenario_digest=new_scenario.digest(),
            map_digest=new_scenario.map.digest(),
            config_digest=compute_digest(new_scenario.simulation),
            fault_digest=compute_digest([f.model_dump(mode="json") for f in new_scenario.faults]),
            task_digest=compute_digest([t.model_dump(mode="json") for t in new_scenario.tasks]),
        )


F64 = FiniteFloat
ScenarioSelf = Self

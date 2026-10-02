"""Run orchestration: manifests, snapshots, the harness and the run lifecycle.

This module owns the *experiment* layer. It does not own:

* physics (that is the world process),
* planning or coordination (that is each agent process),
* evaluation verdicts (that is :mod:`niharamesh.evaluation`, which reads recorded
  evidence rather than live state).

Everything it produces is traceable to an immutable scenario snapshot plus a
manifest, because a measurement nobody can reproduce is not evidence.
"""

from __future__ import annotations

import pathlib
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from niharamesh.domain.scenario import Scenario, ScenarioSnapshot
from niharamesh.domain.telemetry import (
    EnvironmentRecord,
    MetricValue,
    RecordingGap,
    RunManifest,
    RunOutcome,
    RunResult,
    RunState,
    compute_digest,
)
from niharamesh.domain.units import TimeDomain

__all__ = [
    "ExecutionMode",
    "RunHandle",
    "RunLifecycle",
    "build_manifest",
    "freeze_snapshot",
    "git_identity",
]

#: The two honest execution modes. Kept as an alias of the manifest's literal type
#: so a typo becomes a type error rather than a rejected run at launch.
ExecutionMode = Literal["deterministic", "processes"]


def _git_exe() -> str:
    """Absolute git path. Absolute avoids a PATH lookup surprise mid-run."""
    return shutil.which("git") or "git"


def git_identity(root: pathlib.Path | None = None) -> tuple[str, bool]:
    """Return ``(revision, dirty)``.

    Recorded honestly. A dirty tree is reported as dirty; nothing is stashed,
    committed or cleaned to make a run look reproducible.
    """
    import subprocess

    base = root or pathlib.Path.cwd()
    try:
        rev = subprocess.run(  # noqa: S603 - git resolved to an absolute path, args are literals
            [_git_exe(), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=base,
            check=False,
        )
        status = subprocess.run(  # noqa: S603 - git resolved to an absolute path, args are literals
            [_git_exe(), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=base,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unavailable", True
    revision = rev.stdout.strip() or "unavailable"
    dirty = bool(status.stdout.strip()) or rev.returncode != 0
    return revision, dirty


def freeze_snapshot(scenario: Scenario) -> ScenarioSnapshot:
    """Freeze a scenario into the immutable bundle a run is bound to.

    From this moment the run refers only to the snapshot. Editing the scenario
    library afterwards cannot change an experiment already launched.
    """
    return ScenarioSnapshot.freeze(scenario, created_utc_ns=time.time_ns())


def build_manifest(
    snapshot: ScenarioSnapshot,
    *,
    run_id: str,
    mode: ExecutionMode,
    seed: int,
    environment: EnvironmentRecord | None = None,
) -> RunManifest:
    """Assemble the manifest that every derived artefact must quote."""
    scenario = snapshot.scenario
    revision, dirty = git_identity()
    manifest = RunManifest(
        run_id=run_id,
        created_utc_ns=time.time_ns(),
        source_revision=revision,
        source_dirty=dirty,
        scenario_digest=snapshot.scenario_digest,
        scenario_revision=scenario.revision,
        map_digest=snapshot.map_digest,
        config_digest=snapshot.config_digest,
        mode=mode,
        coordination_policy=scenario.policy.coordination.value,
        assignment_policy=scenario.policy.assignment.value,
        routing_policy=scenario.policy.routing.value,
        comparison_mode=scenario.policy.comparison_mode.value,
        feature_flags={
            "temporal_planning": scenario.simulation.features.temporal_planning,
            "blocked_aware_routing": scenario.simulation.features.blocked_aware_routing,
            "task_reassignment": scenario.simulation.features.task_reassignment,
            "fairness_aware_priority": scenario.simulation.features.fairness_aware_priority,
            "timer_expiry_occupancy": scenario.simulation.features.timer_expiry_occupancy,
            "disable_safety_gate": scenario.simulation.features.disable_safety_gate,
            "unsafe_research_variant": scenario.simulation.features.unsafe_research_variant,
        },
        seed=seed,
        robot_ids=tuple(r.robot_id for r in scenario.robots),
        task_count=len(scenario.tasks),
        fault_ids=tuple(f.fault_id for f in scenario.faults),
        max_sim_time_s=scenario.max_sim_time_s,
        environment=environment or EnvironmentRecord.capture(),
        expected_failure_scenario=scenario.kind == "diagnostic",
        expected_failure_reason=scenario.intent.expected_failure_reason,
    )
    return manifest.model_copy(update={"run_id": run_id, "created_utc_ns": manifest.created_utc_ns})


@dataclass(slots=True)
class RunHandle:
    """Live bookkeeping for one run. Holds no authority over the agents."""

    run_id: str
    manifest: RunManifest
    snapshot: ScenarioSnapshot
    state: RunState = RunState.QUEUED
    outcome: RunOutcome = RunOutcome.FAILED
    stop_reason: str = ""
    artifacts: pathlib.Path | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def manifest_digest(self) -> str:
        return compute_digest(self.manifest)

    @property
    def terminal(self) -> bool:
        return self.state.terminal

    def advance(self, state: RunState, *, reason: str = "") -> None:
        """Move to *state*, refusing a transition that would rewrite history."""
        if self.terminal and state is not self.state:
            raise RuntimeError(
                f"run {self.run_id} is already {self.state.value}; refusing to become {state.value}"
            )
        if state is RunState.CANCELLED and self.terminal:
            return
        self.state = state
        if reason:
            self.stop_reason = reason

    def to_result(
        self,
        *,
        sim_duration_s: float,
        tasks_total: int,
        tasks_completed: int,
        collisions: int,
        min_clearance_m: float | None,
        metrics: Sequence[MetricValue] = (),
        gaps: Sequence[RecordingGap] = (),
    ) -> RunResult:
        """Build the final result. Missing measurements stay ``None``."""
        result = RunResult(
            run_id=self.run_id,
            state=self.state,
            outcome=self.outcome,
            manifest_digest=self.manifest_digest,
            sim_duration_s=sim_duration_s,
            makespan_s=sim_duration_s if self.outcome is RunOutcome.SUCCESS else None,
            tasks_total=tasks_total,
            tasks_completed=tasks_completed,
            collisions=collisions,
            min_clearance_m=min_clearance_m,
            metrics=tuple(metrics),
            gaps=tuple(gaps),
            stop_reason=self.stop_reason,
            events_path=str(self.artifacts) if self.artifacts else "",
        )
        return result.model_copy(update={"digest": compute_digest(result)})


class RunLifecycle:
    """State transitions a run is allowed to make.

    Written out rather than sprinkled through the harness so an illegal
    transition is a single, testable rule.
    """

    ALLOWED: ClassVar[dict[RunState, frozenset[RunState]]] = {
        RunState.QUEUED: frozenset({RunState.RUNNING, RunState.CANCELLED, RunState.FAILED}),
        RunState.RUNNING: frozenset(
            {
                RunState.PAUSED,
                RunState.COMPLETED,
                RunState.UNSAFE,
                RunState.FAILED,
                RunState.TIMED_OUT,
                RunState.CANCELLED,
            }
        ),
        RunState.PAUSED: frozenset(
            {RunState.RUNNING, RunState.CANCELLED, RunState.FAILED, RunState.TIMED_OUT}
        ),
        # terminal states have no successors
        RunState.COMPLETED: frozenset(),
        RunState.UNSAFE: frozenset(),
        RunState.FAILED: frozenset(),
        RunState.TIMED_OUT: frozenset(),
        RunState.CANCELLED: frozenset(),
    }

    @classmethod
    def is_allowed(cls, current: RunState, nxt: RunState) -> bool:
        return current is nxt or nxt in cls.ALLOWED[current]

    @classmethod
    def require(cls, current: RunState, nxt: RunState) -> None:
        if not cls.is_allowed(current, nxt):
            raise ValueError(f"illegal run transition {current.value} -> {nxt.value}")


_TIME_DOMAIN_NOTE = (
    "Run durations below are in SIM_SECONDS. Wall-clock durations, where measured, are "
    "kept separately in EnvironmentRecord and are never mixed with them."
)
_TIME_DOMAIN = TimeDomain.SIM_SECONDS
assert _TIME_DOMAIN_NOTE and _TIME_DOMAIN

"""The deterministic single-process harness.

Runs a whole scenario in one process with **isolated per-agent state**. Each
agent has its own planner, coordinator, journal and safety gate, and the agents
exchange messages only through declared inboxes that are delivered by this
harness -- exactly the shape the real transport produces, minus the sockets.

What this harness is good for
-----------------------------
Fast, repeatable evidence that the *algorithms* work: same inputs and seed give
the same canonical event/outcome hash.

What it is **not**
-----------------
Evidence of process isolation. An agent in this harness cannot crash the way a
separate process can, and two agents here share one event loop. So the product also
runs real separate processes (`tests/network/test_three_process_peers.py`), and
the architecture tests cover that. The harness documents the difference rather
than letting it be assumed.

The tick barrier below is a *simulation scheduling mechanism*. It exists so a
fixed-step world can be deterministic. It is not a coordinator, it grants nothing,
and no agent can observe it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Protocol

from niharamesh.agent.runtime import RobotAgent
from niharamesh.clocks import LogicalClock
from niharamesh.domain.coordination import PeerMessage
from niharamesh.domain.identity import Membership, RobotSession
from niharamesh.domain.pose import MotionCommand
from niharamesh.domain.scenario import Scenario, ScenarioSnapshot
from niharamesh.domain.units import PROTOCOL_EPOCH
from niharamesh.ports import Observation
from niharamesh.simulator.scheduler import DeterministicScheduler
from niharamesh.simulator.world import World

__all__ = ["DeterministicHarness", "HarnessResult", "run_scenario"]


class TransportLike(Protocol):
    """The slice of peer transport the harness needs."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def send(self, peer_robot_id: str, message: PeerMessage) -> None: ...


@dataclass(slots=True)
class RobotTrace:
    """Per-robot record of what it did, kept for the report and the inspector."""

    robot_id: str
    commands: int = 0
    gate_vetoes: int = 0
    stopped_for: dict[str, int] = field(default_factory=dict)
    zones_entered: list[str] = field(default_factory=list)
    tasks_completed: list[str] = field(default_factory=list)


@dataclass(slots=True)
class HarnessResult:
    run_id: str
    sim_duration_s: float
    steps: int
    robots: dict[str, RobotTrace]
    inspections: list[dict[str, object]]
    outcome: str
    outcome_hash: str
    events: list[dict[str, object]] = field(default_factory=list)


class _RobotActuator:
    """One robot's outward channel, bound to that robot at construction.

    The binding is the point: an agent physically cannot reach the world on a
    peer's behalf, because there is no argument through which it could name one.
    Every method here is a *physical* fact about one body -- a command the gate has
    permitted, a station visit, a payload on the deck. None of them grants
    authority, awards work, or reads another robot's state.
    """

    __slots__ = ("_robot_id", "_world")

    def __init__(self, robot_id: str, world: World) -> None:
        self._robot_id = robot_id
        self._world = world

    def apply_command(self, command: MotionCommand) -> bool:
        if command.robot_id != self._robot_id:
            return False
        return self._world.apply_command(command)

    def start_service(self, station_id: str, duration_s: float) -> bool:
        return self._world.begin_service(self._robot_id, station_id, duration_s)

    def service_running(self) -> bool:
        """True while this robot's station visit is still in progress.

        Reads the world's *level* query, not its completion *event*. The event is
        edge-triggered and cleared at the start of every step, so a caller polling it
        once per control period reads "not servicing" from the tick after the visit
        finished -- which would let a robot re-enter a station it had already left.
        """
        return self._world.is_servicing(self._robot_id)

    def take_payload(self, task_id: str) -> bool:
        return self._world.attach_payload(self._robot_id, task_id)


class DeterministicHarness:
    """Owns the world, the agents, and the inbox exchange between them."""

    def __init__(self, snapshot: ScenarioSnapshot, *, run_id: str, speed: float = 1.0) -> None:
        self.snapshot = snapshot
        self.scenario: Scenario = snapshot.scenario
        self.run_id = run_id
        self.clock = LogicalClock(0, speed_multiplier=speed)
        self.world = World(snapshot)
        self.scheduler = DeterministicScheduler(
            step_s=1.0 / self.scenario.simulation.physics_step_hz,
            max_steps=int(self.scenario.max_sim_time_s * self.scenario.simulation.physics_step_hz),
        )
        self.membership = Membership(
            run_id=run_id,
            epoch=PROTOCOL_EPOCH,
            members=tuple(sorted(r.robot_id for r in self.scenario.robots)),
        ).model_copy(update={"digest": self.scenario.map.digest()})

        sessions: dict[str, str] = {r.robot_id: f"{r.robot_id}-s1" for r in self.scenario.robots}
        self.agents: dict[str, RobotAgent] = {}
        for identity in self.scenario.robots:
            session = RobotSession(
                robot_id=identity.robot_id,
                session_id=f"{identity.robot_id}-s1",
                started_at_ns=0,
                listening_port=0,
            )
            self.agents[identity.robot_id] = RobotAgent(
                identity=identity,
                session=session,
                scenario=self.scenario,
                membership=self.membership,
                clock=self.clock,
                run_id=run_id,
                actuator=_RobotActuator(identity.robot_id, self.world),
                # The harness owns the run's session table. Admission needs it so a
                # request from a superseded boot is refused rather than merged.
                session_registry=lambda peer: sessions.get(peer),
            )

        self._inbox: dict[str, list[PeerMessage]] = {rid: [] for rid in self.agents}
        self.traces = {rid: RobotTrace(robot_id=rid) for rid in self.agents}
        self._events: list[dict[str, object]] = []
        self._seq = 0
        self._faults_applied: set[str] = set()
        self._credited: set[tuple[str, str]] = set()
        #: Which zone each robot is currently physically inside, so entry is an
        #: edge-triggered event rather than a state that repeats every tick.
        self._entered: dict[str, str | None] = dict.fromkeys(self.agents)

    # ------------------------------------------------------------------ loop

    def run(self, *, max_sim_time_s: float | None = None) -> HarnessResult:
        """Advance the world until the deadline or the workload finishes."""
        deadline = max_sim_time_s if max_sim_time_s is not None else self.scenario.max_sim_time_s
        required = len(self.scenario.tasks)

        while self.clock.now_s() < deadline:
            for _ in range(self.scenario.simulation.physics_step_hz):
                now_ns = self.clock.now_ns()
                self._apply_faults(now_ns)

                for robot_id, agent in self.agents.items():
                    observation = self.world.observe(robot_id)
                    command = agent.tick(observation)
                    trace = self.traces[robot_id]
                    trace.commands += 1
                    if not command.linear_mps and agent.stop_reason.value != "none":
                        key = agent.stop_reason.value
                        trace.stopped_for[key] = trace.stopped_for.get(key, 0) + 1
                        trace.gate_vetoes += 1
                    self.world.apply_command(command)
                    self._collect_completions(robot_id, agent, now_ns)
                    self._collect_zone_events(robot_id, agent, now_ns)

                self._drain_outboxes()
                self._deliver()
                self.world.step(self.scenario.simulation.dt_s)
                self.clock.advance_seconds(self.scenario.simulation.dt_s)
                if required and self._completed_count() >= required:
                    break
            if required and self._completed_count() >= required:
                break

        return self._result()

    def _completed_count(self) -> int:
        """Distinct tasks holding a completion credit across the whole fleet."""
        return len({task for _, task in self._credited})

    def _collect_completions(self, robot_id: str, agent: RobotAgent, now_ns: int) -> None:
        """Record completion credits the agent's own ledger granted, exactly once.

        Derived from the custody ledger rather than from a state comparison, because
        a credit is the only thing in the system that means "this task is done", and
        because a ledger that refuses a duplicate can be relied on to make a second
        entry impossible. The harness cannot grant one.
        """
        for task_id in agent.completed_tasks:
            key = (robot_id, task_id)
            if key in self._credited:
                continue
            self._credited.add(key)
            self.traces[robot_id].tasks_completed.append(task_id)
            self._record("task_completed", task_id, now_ns, robot_id=robot_id)

    def _collect_zone_events(self, robot_id: str, agent: RobotAgent, now_ns: int) -> None:
        """Record zone entry and release from the agent's own declarations."""
        evidence = agent.zone_evidence
        if evidence is None:
            return
        occupied = evidence.occupied_zone
        if occupied is not None and occupied != self._entered.get(robot_id):
            self._entered[robot_id] = occupied
            self.traces[robot_id].zones_entered.append(occupied)
            self._record("zone_occupied", occupied, now_ns, robot_id=robot_id)

    # --------------------------------------------------------------- plumbing

    def _apply_faults(self, now_ns: int) -> None:
        for fault in self.scenario.faults:
            if fault.fault_id in self._faults_applied:
                continue
            start_ns = int(fault.start_at_s * 1e9)
            if now_ns < start_ns:
                continue
            self._faults_applied.add(fault.fault_id)
            self._record("fault_injected", fault.fault_id, now_ns)
            if fault.target.kind.value == "obstacle_insert" and fault.target.position:
                x, y = fault.target.position
                self.world.insert_obstacle(
                    obstacle_id=fault.fault_id,
                    x=x,
                    y=y,
                    length_m=float(fault.params.get("length_m", 0.8)),
                    width_m=float(fault.params.get("width_m", 0.8)),
                    theta=float(fault.params.get("theta", 0.0)),
                )
                self._record("obstacle_inserted", fault.fault_id, now_ns, x=x, y=y)

    def _publish(self, robot_id: str, now_ns: int, command: MotionCommand) -> None:
        """No state broadcast is synthesised here.

        Real process mode has each agent publish its own velocity through the
        socket transport. The deterministic harness deliberately does *not* fake
        one: inventing a message the agent never produced would make the recorded
        evidence claim more communication than actually happened. Coordination
        still works because it runs over the protocol outbox, which the agents
        themselves fill.
        """
        del robot_id, now_ns, command

    def _drain_outboxes(self) -> None:
        """Route only the framed messages each coordinator actually emitted.

        Collect every sender before delivery so a reply produced by ingest waits
        until the next physics tick, independently of recipient iteration order.
        The protocol owns local-voter calls, framing and sequence numbers; this
        channel must neither synthesise authority nor bypass those boundaries.
        """
        for sender in sorted(self.agents):
            outbox = self.agents[sender].coordinator.outbox
            for target, message in outbox:
                self._inbox[target].append(message)
            outbox.clear()

    def _deliver(self) -> None:
        """Move queued messages to their recipients and ingest them.

        The exchange order is deterministic: sorted by sender then sequence. No
        set iteration, no dict ordering assumption, no wall-clock read.
        """
        for target in sorted(self._inbox):
            queued = self._inbox[target]
            self._inbox[target] = []
            for message in sorted(queued, key=lambda m: (m.envelope.sender, m.envelope.seq)):
                self.agents[target].ingest(message)

    def exchange(self, sender: str, recipients: list[str], message: PeerMessage) -> None:
        """Deliver *message* from *sender* to each recipient. Deterministic order."""
        for target in sorted(recipients):
            self._inbox[target].append(message)
        del sender

    def _record(self, event_type: str, subject: str, now_ns: int, **fields: object) -> None:
        self._seq += 1
        self._events.append(
            {
                "seq": self._seq,
                "sim_time_s": round(now_ns / 1e9, 6),
                "type": event_type,
                "subject": subject,
                **fields,
            }
        )

    def _result(self) -> HarnessResult:
        outcome = self._classify()
        return HarnessResult(
            run_id=self.run_id,
            sim_duration_s=round(self.clock.now_s(), 3),
            steps=self.world.step_index,
            robots=self.traces,
            inspections=[a.inspect() for _, a in sorted(self.agents.items())],
            outcome=outcome,
            outcome_hash=self._outcome_hash(outcome),
            events=self._events,
        )

    def _classify(self) -> str:
        """Honest outcome classification.

        A diagnostic scenario whose robots stop safely is ``expected_safe_stop``,
        not a failure and not a success. Anything that did not finish every task is
        never reported as a completed workload.
        """
        completed = sum(len(t.tasks_completed) for t in self.traces.values())
        required = len(self.scenario.tasks)
        unreachable: list[str] = []
        for robot_id in sorted(self.agents):
            task_block = self.agents[robot_id].inspect().get("task")
            if isinstance(task_block, dict) and task_block.get("unreachable_reason"):
                unreachable.append(robot_id)
        if unreachable:
            return "expected_safe_stop" if self.scenario.kind == "diagnostic" else "unreachable_workload"
        if required == 0 or completed >= required:
            return "success"
        return "incomplete"

    def _outcome_hash(self, outcome: str) -> str:
        """Canonical hash of the run's decisions.

        Normalises only genuinely non-reproducible fields. It never normalises
        event content or ordering, so a changed decision changes the hash.
        """
        payload = {
            "scenario": self.snapshot.scenario_digest,
            "outcome": outcome,
            "sim_duration_s": round(self.clock.now_s(), 3),
            "robots": [
                {
                    "robot_id": rid,
                    "commands": t.commands,
                    "vetoes": t.gate_vetoes,
                    "stops": dict(sorted(t.stopped_for.items())),
                    "zones": list(t.zones_entered),
                    "tasks": list(t.tasks_completed),
                }
                for rid, t in sorted(self.traces.items())
            ],
            "events": self._events,
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def run_scenario(
    scenario: Scenario,
    *,
    run_id: str,
    speed: float = 1.0,
    max_sim_time_s: float | None = None,
) -> HarnessResult:
    """Convenience entry point: freeze the scenario and run it."""
    from niharamesh.runs.orchestrator import freeze_snapshot

    snapshot = freeze_snapshot(scenario)
    harness = DeterministicHarness(snapshot, run_id=run_id, speed=speed)
    return harness.run(max_sim_time_s=max_sim_time_s)


def _unused(_: Observation) -> None:  # pragma: no cover
    """Placeholder retained so the Observation import documents the harness surface."""

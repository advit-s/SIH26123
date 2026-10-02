"""The physical world. It applies commands; it never prevents them.

The rule this module exists to obey
-----------------------------------
"The physics engine must not conceal unsafe control by refusing all colliding
motion or teleporting a robot away from an obstacle." Concretely, each of the
following is forbidden here, and each has a test in ``tests/unit/test_world.py``:

* refusing an ``apply_command`` because the motion would collide,
* clamping a position so a robot stops at a wall,
* snapping a velocity to zero when a command expires (the watchdog *brakes*),
* resolving a penetration by moving one of the bodies apart.

Collisions are therefore *applied* and then detected by the independent checkers in
:mod:`niharamesh.safety.collision`. An unsafe run has to be able to produce evidence,
which it cannot if the world quietly makes it safe.

The authority surface, deliberately small
-----------------------------------------
Three accessors reveal exact geometry -- :meth:`World.truth`,
:meth:`World.bodies_for_evaluation` and :meth:`World.static_boxes_for_evaluation` --
and each is labelled in place as evaluator and debug-overlay only. They are
reachable because the simulator process owns them, not because they are harmless:
the agent-facing RPC surface of that process exposes :meth:`World.observe` only,
and ``tests/unit/test_world.py`` asserts that ``observe`` carries no collection,
no peer pose and no collision verdict.

Clock domains
-------------
The world owns exactly one clock: ``sim_time_ns`` in the ``LOGICAL`` domain. A
``MotionCommand`` is accepted only if it declares that same domain; a command in
``MONOTONIC`` is refused rather than compared against a value it cannot legally be
compared to. Sensor latency is modelled by carrying two timestamps, never by
subtracting across domains.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from niharamesh.clocks import SeededStreams
from niharamesh.domain.config import SimulationConfig
from niharamesh.domain.faults import FaultKind
from niharamesh.domain.geometry import OrientedBox, Pose
from niharamesh.domain.identity import RobotIdentity
from niharamesh.domain.map import Obstacle, ObstacleKind, WarehouseMap
from niharamesh.domain.pose import (
    ActuatorState,
    Footprint,
    MotionCommand,
    MotionState,
    Pose2,
    StopReason,
)
from niharamesh.domain.scenario import ScenarioSnapshot
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import Observation, RobotTruth, WorldTruth
from niharamesh.simulator import kinematics
from niharamesh.simulator.sensors import (
    NS_PER_S,
    SensorScene,
    generate_observation,
    generate_pose_estimate,
    obstacle_boxes,
)

__all__ = ["World"]

_DEFAULT_DYNAMIC_LENGTH_M: Final[float] = 0.8
_DEFAULT_DYNAMIC_WIDTH_M: Final[float] = 0.8


@dataclass(slots=True)
class _Service:
    """An in-progress station visit."""

    station_id: str
    started_at_ns: int
    duration_s: float

    @property
    def due_at_ns(self) -> int:
        return self.started_at_ns + int(self.duration_s * NS_PER_S)


@dataclass(slots=True)
class _RobotState:
    """Exact simulator state for one robot. Never handed to that robot's agent."""

    identity: RobotIdentity
    pose: Pose
    v: float = 0.0
    omega: float = 0.0
    actuator: ActuatorState = ActuatorState.DISABLED
    stop_reason: StopReason = StopReason.NONE
    command: MotionCommand | None = None
    command_seq: int = 0
    actuation_enabled: bool = False
    battery_c: float = 1.0
    carrying: str | None = None
    service: _Service | None = None
    odometry_m: float = 0.0


class World:
    """Concrete :class:`~niharamesh.ports.WorldPort`.

    Construct from a frozen :class:`ScenarioSnapshot` so editing the scenario
    library afterwards cannot change a run that already launched (invariant 9).
    """

    __slots__ = (
        "_completed_this_step",
        "_config",
        "_dynamic",
        "_fired_faults",
        "_now_ns",
        "_robots",
        "_snapshot",
        "_step_index",
        "_streams",
    )

    def __init__(self, snapshot: ScenarioSnapshot) -> None:
        self.reset(snapshot)

    # -- port surface ------------------------------------------------------- #

    @property
    def config(self) -> SimulationConfig:
        return self._config

    @property
    def snapshot(self) -> ScenarioSnapshot:
        """The immutable scenario bundle. Agents legitimately receive this."""
        return self._snapshot

    @property
    def map(self) -> WarehouseMap:
        """The immutable shared map. Every agent receives this same object."""
        return self._snapshot.scenario.map

    @property
    def sim_time_ns(self) -> int:
        return self._now_ns

    @property
    def step_index(self) -> int:
        return self._step_index

    def reset(self, snapshot: ScenarioSnapshot) -> None:
        """Rebuild every robot from *snapshot*. Total state replacement."""
        self._snapshot = snapshot
        self._config = snapshot.scenario.simulation
        self._streams = SeededStreams(base_seed=snapshot.scenario.policy.sensor_seed)
        self._now_ns = 0
        self._step_index = 0
        # Robots whose station service finished during the current step, so
        # ``service_complete`` can report the event exactly once to a caller that
        # polls after stepping rather than before.
        self._completed_this_step: set[str] = set()
        self._dynamic: dict[str, Obstacle] = {}
        self._fired_faults: set[str] = set()
        self._robots: dict[str, _RobotState] = {}
        for identity in snapshot.scenario.robots:
            start = snapshot.scenario.start_of(identity.robot_id)
            self._robots[identity.robot_id] = _RobotState(
                identity=identity,
                pose=Pose(start.pose.x, start.pose.y, start.pose.theta),
                actuation_enabled=self._config.physical_actuation_enabled,
                battery_c=self._config.battery.start_fraction,
                carrying=start.holding_task_id,
            )
        self._apply_scheduled_faults()

    def apply_command(self, command: MotionCommand) -> bool:
        """Hold *command* for the robot it names. Returns whether it was accepted.

        Acceptance is a question of *authority over the actuator*, not of safety.
        The command is refused only when:

        * the robot is unknown to this world,
        * the command declares a clock domain other than the world's,
        * the command sequence is not newer than the one already held (a replayed
          or reordered command is not a new instruction), or
        * physical actuation is disabled, which is the default.

        It is **never** refused because the resulting motion would collide, would
        leave the map, or would enter a zone. Those outcomes are applied and then
        detected independently.
        """
        state = self._robots.get(command.robot_id)
        if state is None:
            return False
        if command.time_domain is not TimeDomain.LOGICAL:
            # Comparing an expiry in another domain against logical time would be
            # the exact mistake invariant 8 forbids.
            return False
        if command.command_seq <= state.command_seq:
            return False
        if not self._config.physical_actuation_enabled:
            return False

        state.command = command
        state.command_seq = command.command_seq
        state.actuation_enabled = True
        state.stop_reason = StopReason.NONE
        return True

    def step(self, dt_s: float) -> None:
        """Advance every robot, battery, service timer and dynamic obstacle."""
        if dt_s < 0.0:
            raise ValueError("dt_s must be non-negative")
        self._now_ns += round(dt_s * NS_PER_S)
        self._step_index += 1
        self._completed_this_step = set()

        actuator = self._config.actuator
        for robot_id in sorted(self._robots):
            state = self._robots[robot_id]
            command = state.command
            expired = command is not None and self._now_ns >= command.expires_at_ns
            requested_v = 0.0 if command is None else command.linear_mps
            requested_omega = 0.0 if command is None else command.angular_radps
            if command is not None and command.hold_position:
                requested_v = 0.0

            if command is None:
                enabled = False
            elif expired:
                state.stop_reason = StopReason.COMMAND_EXPIRED
                state.actuator = ActuatorState.WATCHDOG_BRAKING
                requested_v = 0.0
                requested_omega = 0.0
                enabled = False
            else:
                enabled = state.actuation_enabled

            result = kinematics.step(
                x=state.pose.x,
                y=state.pose.y,
                theta=state.pose.theta,
                v=state.v,
                omega=state.omega,
                command_v=requested_v,
                command_omega=requested_omega,
                dt=dt_s,
                actuator=actuator,
                command_expired=expired,
                actuation_enabled=enabled,
            )
            # No clamping, no penetration resolution: the new pose is whatever the
            # declared actuator model produced, however unsafe.
            state.pose = Pose(result.x, result.y, result.theta)
            state.v = result.v
            state.omega = result.omega
            state.actuator = result.actuator
            state.odometry_m += result.distance_m
            self._integrate_battery(state, result.distance_m, dt_s, servicing=state.service is not None)

        for robot_id in sorted(self._robots):
            state = self._robots[robot_id]
            if state.service is not None and self._now_ns >= state.service.due_at_ns:
                self._finish_service(robot_id)

        self._apply_scheduled_faults()

    def observe(self, robot_id: str) -> Observation:
        """This robot's own declared observation. Nothing else is in scope.

        The returned object carries a *noisy* estimate of its own pose, its own
        motion state, its own battery fraction, and a range scan in which peers
        appear only as distances.
        """
        state = self._robots[robot_id]
        sensor_model = self._config.sensor
        latency_ns = int(sensor_model.observation_latency_s * NS_PER_S)

        estimate = generate_pose_estimate(
            true_pose=state.pose,
            map_id=self.map.map_id,
            sensor_model=sensor_model,
            streams=self._streams,
            rng_stream_name=f"sensor/{robot_id}/pose",
            observed_at_ns=max(0, self._now_ns - latency_ns),
        )
        scan = generate_observation(
            world_geometry=self._sensor_scene(robot_id),
            robot_id=robot_id,
            true_pose=state.pose,
            footprint=state.identity.footprint,
            sim_time_ns=self._now_ns,
            sensor_model=sensor_model,
            streams=self._streams,
            rng_stream_name=f"sensor/{robot_id}/scan",
        )
        command = state.command
        motion = MotionState(
            linear_velocity_mps=state.v,
            angular_velocity_radps=state.omega,
            commanded_linear_mps=0.0 if command is None else command.linear_mps,
            commanded_angular_radps=0.0 if command is None else command.angular_radps,
            command_seq=state.command_seq,
            command_expires_at_ns=None if command is None else command.expires_at_ns,
            actuator=state.actuator,
            stop_reason=state.stop_reason,
            actuation_enabled=state.actuation_enabled,
        )
        return Observation(
            robot_id=robot_id,
            pose_estimate=estimate,
            motion=motion,
            sensor=scan,
            battery_fraction=max(0.0, state.battery_c),
            sim_time_ns=self._now_ns,
        )

    def truth(self) -> WorldTruth:
        """Exact state. **Evaluator and labelled debug overlay only.**

        This is one of the three evaluator-side accessors on this class; none of
        them is reachable from :meth:`observe`, because the agent-facing RPC
        surface of the simulator process exposes ``observe`` only.
        """
        robots = {
            robot_id: RobotTruth(
                robot_id=robot_id,
                x=state.pose.x,
                y=state.pose.y,
                theta=state.pose.theta,
                v=state.v,
                omega=state.omega,
                battery=state.battery_c,
                carrying=state.carrying,
            )
            for robot_id, state in sorted(self._robots.items())
        }
        dynamic = tuple(
            (o.pose.x, o.pose.y, o.pose.theta, o.length_m, o.width_m)
            for o in sorted(self._dynamic.values(), key=lambda o: o.id)
        )
        stops = tuple(
            state.stop_reason
            for _, state in sorted(self._robots.items())
            if state.stop_reason is not StopReason.NONE
        )
        return WorldTruth(
            sim_time_ns=self._now_ns,
            robots=robots,
            dynamic_obstacles=dynamic,
            stops=stops,
        )

    def bodies_for_evaluation(self) -> dict[str, tuple[OrientedBox, ...]]:
        """Every robot's occupied bodies, chassis plus payload when loaded.

        **Evaluator and labelled debug overlay only.** Feeding this to
        :func:`niharamesh.safety.collision.resolve_collision_report` is the
        supported way to audit a run. It is deliberately not reachable from
        :meth:`observe`; see the module docstring.
        """
        return {
            robot_id: _occupied_bodies(state.identity.footprint, state.pose, state.carrying)
            for robot_id, state in sorted(self._robots.items())
        }

    def static_boxes_for_evaluation(self) -> tuple[OrientedBox, ...]:
        """Every obstacle present right now: map shelves plus injected temporaries.

        **Evaluator and labelled debug overlay only**, for the same reason as
        :meth:`bodies_for_evaluation`.
        """
        return obstacle_boxes(self._sensor_map())

    # -- dynamic obstacles (fault injection) ------------------------------- #

    def insert_obstacle(
        self,
        obstacle_id: str,
        x: float,
        y: float,
        theta: float = 0.0,
        length_m: float = _DEFAULT_DYNAMIC_LENGTH_M,
        width_m: float = _DEFAULT_DYNAMIC_WIDTH_M,
    ) -> bool:
        """Add a temporary obstacle. Returns False when the id is already present."""
        if obstacle_id in self._dynamic:
            return False
        self._dynamic[obstacle_id] = Obstacle(
            id=obstacle_id,
            kind=ObstacleKind.TEMPORARY,
            pose=Pose2(x=x, y=y, theta=theta),
            length_m=length_m,
            width_m=width_m,
            dynamic=True,
        )
        return True

    def remove_obstacle(self, obstacle_id: str) -> bool:
        """Remove an injected temporary obstacle. Returns whether it existed."""
        return self._dynamic.pop(obstacle_id, None) is not None

    # -- station service and payload custody ------------------------------- #

    def begin_service(self, robot_id: str, station_id: str, duration_s: float) -> bool:
        """Start a station visit. Refuses a busy robot or one that is not at the station.

        The distance check is a *world* rule, not coordination: a robot cannot be
        serviced by a station it is not standing at. It considers neither zones
        nor authority nor any other robot's business.
        """
        state = self._robots.get(robot_id)
        if state is None or state.service is not None:
            return False
        station = self.map.station(station_id)
        tolerance = max(0.25, self.map.nominal_aisle_width_m / 2.0)
        if math.hypot(station.pose.x - state.pose.x, station.pose.y - state.pose.y) > tolerance:
            return False
        state.service = _Service(
            station_id=station_id,
            started_at_ns=self._now_ns,
            duration_s=min(duration_s, station.service_time_s),
        )
        state.actuator = ActuatorState.DISABLED
        state.stop_reason = StopReason.SCHEDULED_STOP
        return True

    def service_complete(self, robot_id: str) -> bool:
        """True when this robot's station service finished during the last step.

        The timer is serviced by :meth:`step`, so a caller polling afterwards would
        otherwise always see ``False`` and could never observe the event. The flag
        is cleared at the start of every step, which makes the event edge-triggered
        and exactly-once: polling twice in a row reports ``True`` then ``False``.
        """
        return robot_id in self._completed_this_step

    def attach_payload(self, robot_id: str, task_id: str) -> bool:
        """Give a robot custody of a load. Physical custody, not logical ownership."""
        state = self._robots.get(robot_id)
        if state is None or state.carrying is not None:
            return False
        state.carrying = task_id
        return True

    def detach_payload(self, robot_id: str) -> str | None:
        """Take custody back. Returns the task id, or ``None`` when empty-handed."""
        state = self._robots.get(robot_id)
        if state is None:
            return None
        carried = state.carrying
        state.carrying = None
        return carried

    def carrying(self, robot_id: str) -> str | None:
        """This robot's own custody. Truth about *itself*, not about a peer."""
        state = self._robots.get(robot_id)
        return None if state is None else state.carrying

    # -- internals ---------------------------------------------------------- #

    def _sensor_map(self) -> WarehouseMap:
        """The immutable map with injected obstacles merged in, in a stable order."""
        if not self._dynamic:
            return self.map
        extras = tuple(sorted(self._dynamic.values(), key=lambda o: o.id))
        return self.map.model_copy(update={"obstacles": self.map.obstacles + extras})

    def _sensor_scene(self, robot_id: str) -> SensorScene:
        """Rays for this robot see every obstacle plus every *other* robot's bodies."""
        bodies: list[OrientedBox] = []
        for other_id in sorted(self._robots):
            if other_id == robot_id:
                continue
            other = self._robots[other_id]
            bodies.extend(
                _occupied_bodies(other.identity.footprint, other.pose, other.carrying)
            )
        return SensorScene(map=self._sensor_map(), other_bodies=tuple(bodies))

    def _finish_service(self, robot_id: str) -> None:
        state = self._robots[robot_id]
        if state.service is None:
            return
        state.service = None
        state.stop_reason = StopReason.WORKLOAD_COMPLETE
        self._completed_this_step.add(robot_id)

    def _integrate_battery(
        self, state: _RobotState, distance_m: float, dt_s: float, *, servicing: bool
    ) -> None:
        """Drain the battery from the declared model, clamped at zero.

        Clamping at zero is the honest floor: a robot with an empty pack still
        exists and still occupies space. It does not vanish and it does not get a
        free charge.
        """
        model = self._config.battery
        drain = distance_m * model.drain_per_metre_c + dt_s * model.drain_per_second_idle_c
        if servicing:
            drain += model.service_drain_c
        state.battery_c = max(0.0, state.battery_c - drain)

    def _apply_scheduled_faults(self) -> None:
        """Apply scenario-declared obstacle faults whose start time has arrived.

        Only the two obstacle faults are handled here. Message and process faults
        belong to the transport and launcher layers; this world has no business
        delaying bytes or killing an agent, and doing so here would let a
        simulation fault masquerade as a coordination result.
        """
        now_s = self._now_ns / NS_PER_S
        for spec in sorted(self._snapshot.scenario.faults, key=lambda f: f.fault_id):
            target = spec.target
            if target.kind not in (FaultKind.OBSTACLE_INSERT, FaultKind.OBSTACLE_REMOVE):
                continue
            if spec.start_at_s > now_s or spec.fault_id in self._fired_faults:
                continue
            self._fired_faults.add(spec.fault_id)
            position = target.position or (0.0, 0.0)
            if target.kind is FaultKind.OBSTACLE_INSERT:
                self.insert_obstacle(
                    spec.fault_id,
                    position[0],
                    position[1],
                    float(spec.params.get("theta_rad", 0.0)),
                    float(spec.params.get("length_m", _DEFAULT_DYNAMIC_LENGTH_M)),
                    float(spec.params.get("width_m", _DEFAULT_DYNAMIC_WIDTH_M)),
                )
            else:
                self.remove_obstacle(spec.fault_id)


def _occupied_bodies(
    footprint: Footprint, pose: Pose, carrying: str | None
) -> tuple[OrientedBox, ...]:
    """Chassis alone when empty-handed, chassis plus load when carrying.

    ``Footprint.occupied_boxes`` reports the payload whenever the footprint
    *declares* a payload capacity, because on its own it has no way to know what is
    physically on the deck. The world does know, so it applies the distinction here:
    treating an empty robot as though it were loaded would inflate every fleet's
    collision envelope and manufacture contacts that cannot happen.
    """
    if carrying is None:
        return (footprint.body_at(pose),)
    return footprint.occupied_boxes(pose)

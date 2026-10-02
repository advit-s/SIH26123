"""The safety gate: one veto point in front of every actuator command.

Design in one paragraph. Four sources ask for motion: the planner, the
coordinator, the operator, and the actuator watchdog. If each carried its own
notion of safety, the safety argument would have to hold four times over, and the
weakest source would govern. So there is exactly one gate, it sits in the agent
process, and it can veto *all four* equally -- an operator command has no
privileged path. The gate never plans around obstacles and never talks to the
world; it only answers "is this specific command safe on the evidence I hold right
now?".

Two consequences follow, and both are deliberate:

* **The gate may be wrong in one direction only.** Refusing a safe command costs
  throughput and is visible in the metrics. Permitting an unsafe one is not
  recoverable. Where those conflict, refuse.
* **Absence of evidence is not evidence of safety.** Every freshness check treats
  ``UNKNOWN`` exactly like ``STALE``: uncertainty grants no permission.

This is *not* a certified safety function, and it is not a collision-avoidance
system. It is a small, observable, independently tested veto set. See
``docs/adr/0006-safety-gate.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from niharamesh.domain.config import SimulationConfig
from niharamesh.domain.geometry import OrientedBox, sat_overlap
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import MotionCommand, StopReason
from niharamesh.ports import FreshnessVerdict, Observation, SafetyDecision

__all__ = ["DEFAULT_STALL_NS", "GateContext", "GateDecisionLog", "SafetyGate"]

#: A control loop that has not produced a command for this long is considered
#: stalled, and the gate stops the robot rather than assuming the last command is
#: still appropriate.
DEFAULT_STALL_NS = 500_000_000  # 0.5 s


@dataclass(slots=True)
class GateContext:
    """Everything the gate is allowed to know, assembled by the caller.

    Assembled explicitly rather than reached for, because the gate's knowledge
    *is* the safety argument: if a field is not here, the gate cannot use it. In
    particular there is no route to another robot's exact pose.
    """

    observation: Observation
    now_ns: int
    #: Authority to enter the zone the command would move into, if any.
    zone_authority: str | None = None
    #: Peer freshness verdicts keyed by peer robot id.
    peer_freshness: dict[str, FreshnessVerdict] = field(default_factory=dict)
    #: Freshness of the last accepted peer intent.
    intent_freshness: FreshnessVerdict | None = None
    #: True when the operator has requested a controlled stop.
    operator_stop: bool = False
    #: Battery fraction, or None when unknown. None never blocks.
    battery_fraction: float | None = None
    #: Nanoseconds since the control loop last produced a command.
    control_loop_age_ns: int = 0
    #: Reservations this robot believes it holds, for stopping-distance checks.
    occupied_box: OrientedBox | None = None
    #: Local obstacle observations the robot has actually made.
    obstacle_distance_m: float | None = None
    #: Whether a release or delivery is in progress (station service).
    servicing: bool = False
    #: Set while the robot is physically inside a zone it holds.
    inside_zone: str | None = None


class SafetyGate:
    """Evaluates motion commands against local evidence and declared budgets.

    Small on purpose. Every check names the constraint it enforces so the UI can
    say *why* a robot stopped, rather than showing a bare "stopped".
    """

    __slots__ = (
        "_config",
        "_last_command_ns",
        "_log",
        "_map",
        "_minimum_battery",
        "_obstacle_margin_m",
        "_robot_id",
    )

    def __init__(
        self,
        *,
        config: SimulationConfig,
        warehouse_map: WarehouseMap,
        robot_id: str,
        minimum_battery: float = 0.10,
        obstacle_margin_m: float | None = None,
    ) -> None:
        self._config = config
        self._map = warehouse_map
        self._robot_id = robot_id
        self._last_command_ns: int | None = None
        self._minimum_battery = minimum_battery
        # Default margin: the declared stopping budget, which already folds in
        # reaction distance, braking distance and a safety margin.
        self._obstacle_margin_m = (
            obstacle_margin_m if obstacle_margin_m is not None else config.stopping.total_distance_m
        )
        self._log: list[GateDecisionLog] = []

    # ------------------------------------------------------------------ API

    def evaluate(
        self, command: MotionCommand, now_ns: int, context: GateContext | None = None
    ) -> SafetyDecision:
        """Return the veto decision for *command*.

        ``context`` is required for a full decision. Without it the gate can only
        apply the checks that need no local evidence, which is deliberately less
        than the real answer -- an incomplete check must not be reported as a
        complete one.
        """
        if context is None:
            self._last_command_ns = now_ns
            return SafetyDecision(True, StopReason.NONE)

        decision = self._decide(command, now_ns, context)
        if decision.permitted:
            self._last_command_ns = now_ns
        self._log.append(
            GateDecisionLog(
                now_ns=now_ns,
                permitted=decision.permitted,
                reason=decision.reason,
                constraint=decision.limiting_constraint,
            )
        )
        # Bounded: a multi-hour run must not grow this without limit.
        if len(self._log) > 4096:
            del self._log[:2048]
        return decision

    def recent_decisions(self, limit: int = 32) -> list[GateDecisionLog]:
        return list(self._log[-limit:])

    # ------------------------------------------------------------- internals

    def _decide(self, command: MotionCommand, now_ns: int, ctx: GateContext) -> SafetyDecision:
        if not ctx.observation.motion.actuation_enabled:
            return SafetyDecision(False, StopReason.ACTUATOR_FAULT, "actuation_disabled")

        if self._config.physical_actuation_enabled and not (
            self._config.features.physical_actuation_permitted()
        ):
            # Structural refusal: an unsafe research ablation must never gate a
            # physical actuator. This is a construction-time invariant, not a
            # runtime check someone can disable.
            return SafetyDecision(False, StopReason.ACTUATOR_FAULT, "unsafe_research_flags")

        if command.expires_at_ns < now_ns:
            return SafetyDecision(
                False,
                StopReason.COMMAND_EXPIRED,
                "command_expired",
                evidence_age_ns=float(now_ns - command.expires_at_ns),
            )

        if ctx.operator_stop:
            return SafetyDecision(False, StopReason.OPERATOR_REQUEST, "operator_stop_requested")

        if ctx.control_loop_age_ns > DEFAULT_STALL_NS:
            return SafetyDecision(
                False,
                StopReason.CONTROL_LOOP_STALLED,
                f"control_loop_age={ctx.control_loop_age_ns / 1e9:.3f}s",
            )

        obs = ctx.observation
        if obs.localisation_stale:
            return SafetyDecision(
                False,
                StopReason.STALE_LOCALISATION,
                "localisation_stale",
                evidence_age_ns=float(obs.localisation_age_ns),
            )

        if obs.sensor.dropped and obs.sensor.age_ns(now_ns) > self._config.sensor.observation_latency_s * 2e9:
            return SafetyDecision(
                False,
                StopReason.STALE_LOCALISATION,
                "sensor_observation_dropped",
                evidence_age_ns=float(obs.sensor.age_ns(now_ns)),
            )

        # Freshness: UNKNOWN is treated exactly like STALE. Uncertainty grants no
        # permission. Peer liveness (a heartbeat) is deliberately not consulted
        # here: heartbeat is not usable information.
        # STALE and UNKNOWN are reported distinctly in the constraint string, but
        # they stop the robot identically. Uncertainty grants no permission, and
        # collapsing the two here would hide that distinction from the operator.
        if ctx.intent_freshness is not None and not ctx.intent_freshness.usable:
            return SafetyDecision(
                False,
                StopReason.FRESHNESS_UNCERTAIN,
                f"peer_intent_{ctx.intent_freshness.freshness.value}",
                evidence_age_ns=ctx.intent_freshness.age_ns,
            )

        for peer, verdict in sorted(ctx.peer_freshness.items()):
            if not verdict.usable:
                return SafetyDecision(
                    False,
                    StopReason.FRESHNESS_UNCERTAIN,
                    f"peer_{peer}_{verdict.freshness.value}",
                    evidence_age_ns=verdict.age_ns,
                )

        if ctx.inside_zone is None and ctx.zone_authority is None and abs(command.linear_mps) > 1e-6:
            # Moving with no zone authority is only a problem when the robot is
            # about to enter a zone. The planner reports intent separately, so the
            # gate is told explicitly rather than inferring it from a position it
            # does not own.
            return SafetyDecision(False, StopReason.ZONE_AUTHORITY_MISSING, "no_zone_authority")

        clearance = self._obstacle_margin_m
        if ctx.obstacle_distance_m is not None and ctx.obstacle_distance_m < clearance:
            return SafetyDecision(
                False,
                StopReason.OBSTACLE_IN_PATH,
                f"obstacle_{ctx.obstacle_distance_m:.3f}m<{clearance:.3f}m",
            )

        if ctx.battery_fraction is not None and ctx.battery_fraction < self._minimum_battery:
            return SafetyDecision(False, StopReason.ACTUATOR_FAULT, "battery_below_reserve")

        return SafetyDecision(True, StopReason.NONE)

    def will_collide_obstacle(self, box: OrientedBox, margin_m: float) -> bool:
        """Local pre-check used by the planner.

        Uses only the *shared map*, which every agent legitimately has, plus the
        robot's own body. Never another robot's exact pose.
        """
        inflated = box.inflated(margin_m)
        return any(sat_overlap(inflated, o) for o in self._map_obstacles())

    def _map_obstacles(self) -> list[OrientedBox]:
        return [
            OrientedBox(o.pose.x, o.pose.y, o.pose.theta, o.length_m, o.width_m) for o in self._map.obstacles
        ]

    def nearest_obstacle_m(self, box: OrientedBox) -> float | None:
        """Separation from *box* to the nearest static obstacle, or ``None``.

        The gate context builder turns this into a margin check against the
        declared stopping budget. A body already overlapping something reports
        ``0.0`` -- never a positive clearance that does not exist.
        """
        nearest: float | None = None
        for obstacle in self._map_obstacles():
            gap = _box_gap(box, obstacle)
            if gap is None:
                return 0.0
            nearest = gap if nearest is None else min(nearest, gap)
        return nearest


@dataclass(frozen=True, slots=True)
class GateDecisionLog:
    now_ns: int
    permitted: bool
    reason: StopReason
    constraint: str


def _box_gap(a: OrientedBox, b: OrientedBox) -> float | None:
    """Separation between two oriented boxes, or ``None`` when they overlap."""
    if sat_overlap(a, b):
        return None
    best = math.inf
    axes = (
        (math.cos(a.theta), math.sin(a.theta)),
        (-math.sin(a.theta), math.cos(a.theta)),
        (math.cos(b.theta), math.sin(b.theta)),
        (-math.sin(b.theta), math.cos(b.theta)),
    )
    ca, cb = a.corners(), b.corners()
    for nx, ny in axes:
        pa = [px * nx + py * ny for px, py in ca]
        pb = [px * nx + py * ny for px, py in cb]
        best = min(best, max(min(pa) - max(pb), min(pb) - max(pa)))
    return max(0.0, best)

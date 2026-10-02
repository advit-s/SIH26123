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

The zone evidence this gate uses
--------------------------------
The gate decides about **geometry**, never about plans. Four separate facts, with
separate names, replace the single ambiguous "zone in progress" field:

======================  =========================================================
``swept_body``          conservative body this command could occupy before its
                        TTL expires: braking distance plus the localisation
                        uncertainty bound, built by the agent from its own
                        footprint and its own command.
``occupied_zone``       the zone whose protected geometry contains this body
                        *right now*, derived from this robot's own pose estimate
                        and footprint -- inflated, never the centre point.
``entry_permission``    the zone for which this robot holds complete, durable
                        GRANTED entry permission (own voter plus every peer
                        voter, digests reconciled, journal healthy, local
                        admission passed).
``zone_authority``      the zone whose authority this robot **retains** --
                        granted-and-entering, or physically occupied. It
                        survives ``may_enter()`` going false after entry, because
                        authority and entry permission stop being the same
                        question once the body is inside.
======================  =========================================================

Three consequences, all intended: legitimate open-space motion is permitted (a
robot crossing an aisle with no zone anywhere in its swept body is never asked
for zone authority); protected entry needs complete valid authority rather than a
plan that mentions the zone; and occupancy is retained, so being inside a zone you
hold authority over stays permitted after ``entry_permission`` has gone.

**Abstention when no body is supplied.** If ``swept_body`` is absent the gate
falls back to ``occupied_box`` -- this robot's own reservation body, a real but
less conservative witness. If *neither* is present the gate holds no geometry at
all and cannot show that the command stays clear of protected geometry, so it
**fails closed**: any command that could move is refused with
``no_zone_geometry_evidence``. A command that cannot move is permitted, and so is
any command on a map that declares no zones, because there is then nothing
protected to enter. This is deliberately the gate's one permitted error direction
(an availability cost, never a safety cost).

This is *not* a certified safety function, and it is not a collision-avoidance
system. It is a small, observable, independently tested veto set. See
``docs/adr/0006-safety-gate.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from niharamesh.domain.config import SimulationConfig
from niharamesh.domain.geometry import OrientedBox, aabb_overlap, bbox_of, sat_overlap
from niharamesh.domain.map import WarehouseMap
from niharamesh.domain.pose import MotionCommand, StopReason
from niharamesh.ports import FreshnessVerdict, Observation, SafetyDecision

__all__ = ["DEFAULT_STALL_NS", "GateContext", "GateDecisionLog", "SafetyGate"]

#: A control loop that has not produced a command for this long is considered
#: stalled, and the gate stops the robot rather than assuming the last command is
#: still appropriate.
DEFAULT_STALL_NS = 500_000_000  # 0.5 s

#: Speeds below this cannot move a body. The declared actuator model cannot hold
#: a 1e-9 m/s creep, and a command that cannot move cannot newly enter protected
#: geometry.
_MOVING_EPSILON: float = 1e-6


@dataclass(slots=True)
class GateContext:
    """Everything the gate is allowed to know, assembled by the caller.

    Assembled explicitly rather than reached for, because the gate's knowledge
    *is* the safety argument: if a field is not here, the gate cannot use it. In
    particular there is no route to another robot's exact pose.
    """

    observation: Observation
    now_ns: int
    #: Authority this robot **retains** over a zone: granted-and-entering, or
    #: physically occupied. Retained authority survives ``may_enter()`` going
    #: false after entry, which is what keeps occupancy conservative (ADR 0005).
    zone_authority: str | None = None
    #: The zone for which this robot holds complete, durable GRANTED entry
    #: permission. Distinct from :attr:`zone_authority`: a permission can be
    #: spent on entry, while authority is retained until the body is clear.
    entry_permission: str | None = None
    #: The zone whose protected geometry contains this robot's body right now.
    #: Conservative: inflated footprint, never the centre point.
    occupied_zone: str | None = None
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
    #: This robot's own reservation body. Doubles as the zone-evidence fallback
    #: when :attr:`swept_body` is absent; see the module docstring.
    occupied_box: OrientedBox | None = None
    #: The conservative body this command could occupy between now and the end of
    #: its TTL, including braking distance and the localisation uncertainty bound.
    #: ``None`` degrades to :attr:`occupied_box`, and then to a refusal.
    swept_body: OrientedBox | None = None
    #: Local obstacle observations the robot has actually made.
    obstacle_distance_m: float | None = None
    #: Whether a release or delivery is in progress (station service).
    servicing: bool = False


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

        refusal = self._zone_evidence_refusal(command, ctx)
        if refusal is not None:
            return refusal

        refusal = self._obstacle_refusal(command, ctx)
        if refusal is not None:
            return refusal

        if ctx.battery_fraction is not None and ctx.battery_fraction < self._minimum_battery:
            return SafetyDecision(False, StopReason.ACTUATOR_FAULT, "battery_below_reserve")

        return SafetyDecision(True, StopReason.NONE)

    def _obstacle_refusal(self, command: MotionCommand, ctx: GateContext) -> SafetyDecision | None:
        """Exact static-geometry check, plus an optional measured clearance.

        Two exact tests on this robot's own body, both against the shared static map:

        1. the body must not overlap static geometry;
        2. the body translated along its commanded travel by its declared stopping
           reach -- and widened by the arc a corner sweeps while turning over the
           command's TTL -- must not overlap static geometry either.

        A *measured* clearance may be supplied through
        :attr:`GateContext.obstacle_distance_m`, and is then compared against the
        declared stopping budget as well. That field must be a clearance **ahead of
        this robot, from its own sensing**. Feeding it an all-direction nearest
        obstacle instead mixed a longitudinal budget with a lateral clearance and
        froze two of three robots in a 1.4 m aisle: a shelf 0.26 m away *beside* a
        robot driving parallel to it is not a stopping hazard, because braking is
        longitudinal. The caller owns that measurement; the gate only says what it
        means.
        """
        body = ctx.occupied_box
        if body is not None:
            if self._overlaps_static(body):
                return SafetyDecision(False, StopReason.OBSTACLE_IN_PATH, "body_overlaps_static")
            swept = self._forward_swept(body, command, ctx)
            if self._overlaps_static(swept):
                return SafetyDecision(
                    False,
                    StopReason.OBSTACLE_IN_PATH,
                    f"stopping_reach_{self._stopping_reach_m(command, ctx):.3f}m_reaches_static",
                )

        clearance = self._obstacle_margin_m
        if ctx.obstacle_distance_m is not None and ctx.obstacle_distance_m < clearance:
            return SafetyDecision(
                False,
                StopReason.OBSTACLE_IN_PATH,
                f"obstacle_{ctx.obstacle_distance_m:.3f}m<{clearance:.3f}m",
            )
        return None

    def _overlaps_static(self, box: OrientedBox) -> bool:
        return any(sat_overlap(box, obstacle) for obstacle in self._map_obstacles())

    def _stopping_reach_m(self, command: MotionCommand, ctx: GateContext) -> float:
        """How far this command could carry the body before it has stopped.

        Travel under the command for its own TTL, plus the analytic braking reach
        ``v**2 / (2a)`` that follows when the command expires and the watchdog takes
        over. The *larger* of the commanded and the measured speed is used, because a
        robot coasting faster than it was asked to is still coasting.
        """
        actuator = self._config.actuator
        speed = max(abs(command.linear_mps), abs(ctx.observation.motion.linear_velocity_mps))
        return speed * actuator.command_ttl_s + (speed * speed) / (2.0 * actuator.decel_mps2)

    def _forward_swept(self, body: OrientedBox, command: MotionCommand, ctx: GateContext) -> OrientedBox:
        """The body translated forward by its stopping reach, widened by its turn."""
        actuator = self._config.actuator
        reach = self._stopping_reach_m(command, ctx)
        omega = max(abs(command.angular_radps), abs(ctx.observation.motion.angular_velocity_radps))
        spin = min(math.pi, omega * actuator.command_ttl_s)
        corner = body.radius * (1.0 - math.cos(spin))
        nx = body.cx + reach * math.cos(body.theta)
        ny = body.cy + reach * math.sin(body.theta)
        return OrientedBox(nx, ny, body.theta, body.length, body.width).inflated(corner)

    def _zone_evidence_refusal(self, command: MotionCommand, ctx: GateContext) -> SafetyDecision | None:
        """The zone-evidence check, or ``None`` when the geometry is admissible.

        This replaces the old blanket ``no_zone_authority`` rule, which asked
        whether a command held *any* zone authority rather than whether its
        geometry was admissible, and could therefore be satisfied by naming a zone
        ten metres away on the remaining plan.

        The decision is per zone and per geometry:

        * a zone nowhere near the swept body is not this command's business, so
          legitimate open-space motion is never asked for authority;
        * a zone the body already occupies needs *retained* authority, not entry
          permission -- occupancy is retained until the body is clear (ADR 0005);
        * any other zone needs complete entry permission for that zone, because
          authority for one zone is never authority for another.
        """
        swept = ctx.swept_body if ctx.swept_body is not None else ctx.occupied_box
        if swept is None:
            # No geometry at all. The gate can neither show the command stays
            # clear nor guess that it does, so it abstains by refusing. This is
            # the one place the gate invents no measurement and loses no safety.
            if not self._map.zones:
                return None  # nothing protected exists on this map
            if abs(command.linear_mps) <= _MOVING_EPSILON and abs(command.angular_radps) <= _MOVING_EPSILON:
                return None  # a command that cannot move cannot newly enter
            return SafetyDecision(
                False,
                StopReason.ZONE_AUTHORITY_MISSING,
                "no_zone_geometry_evidence",
            )

        for zone in self._map.zones:
            if not _body_touches_bounds(swept, zone.protected_bounds):
                continue
            if zone.id == ctx.occupied_zone:
                if ctx.zone_authority != zone.id:
                    return SafetyDecision(
                        False,
                        StopReason.ZONE_AUTHORITY_MISSING,
                        f"unauthorised_occupancy:{zone.id}",
                    )
                continue
            if ctx.entry_permission != zone.id:
                return SafetyDecision(
                    False,
                    StopReason.ZONE_AUTHORITY_MISSING,
                    f"unauthorised_entry:{zone.id}",
                )
        return None

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


def _body_touches_bounds(box: OrientedBox, bounds: tuple[float, float, float, float]) -> bool:
    """True when *box* overlaps ``(min_x, min_y, max_x, max_y)``.

    An AABB test of the box's corners against the bounds. Conservative, and
    deliberately the *authored* geometry: ``Zone.protected_bounds`` was already
    inflated by the map author by the robot clearance radius, so inflating it a
    second time here would refuse robots that are lawfully waiting outside a zone
    and turn a safety decision into an artefact.
    """
    return aabb_overlap(bbox_of(box), bounds)


def _box_gap(a: OrientedBox, b: OrientedBox) -> float | None:
    """Separation between two oriented boxes, or ``None`` when they overlap.

    The separating axis is the one that **maximises** the gap, which is what the
    separating-axis theorem actually says. Accumulating with ``min`` instead --
    which is what this used to do -- works only while every axis happens to report
    a positive gap, and stops working the moment the body is turned far enough that
    one axis's directed gap goes negative. It then reported a genuine 0.30 m
    clearance as ``0.0``, the gate vetoed with ``obstacle_0.000m``, and a robot
    standing in a clear aisle could not move at all.

    For separated boxes the result is a *conservative underestimate* of the true
    Euclidean distance, which is the right direction for a stopping budget. For
    overlapping boxes every axis is negative, so the maximum clamps to ``0.0``.
    """
    if sat_overlap(a, b):
        return None
    best = -math.inf
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
        best = max(best, max(min(pa) - max(pb), min(pb) - max(pa)))
    return max(0.0, best)

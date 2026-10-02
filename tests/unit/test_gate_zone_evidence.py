"""The gate decides about geometry, not about plans (contract section A2).

The old zone check asked one blanket question:

    ``if ctx.inside_zone is None and ctx.zone_authority is None and v > 0``

and the runtime answered it with the *next zone anywhere on the remaining plan*.
A robot with no grant therefore satisfied the zone check by naming a zone ten
metres away. The fix separates three facts that used to be one field:

* ``occupied_zone``    - protected geometry contains this body *right now*,
* ``entry_permission`` - complete, durable, GRANTED permission to enter,
* ``zone_authority``   - authority this robot *retains* (granted-and-entering,
  or physically occupied), which survives ``may_enter()`` going false after
  entry, and
* ``swept_body``       - the conservative body this command could occupy.

Every test below names the invariant it defends. The first group is the new
zone-evidence contract; the second defends the abstention decision for a missing
swept body; the third is the rest of the veto set, each constraint vetoing for
its own reason so a failure names the thing that actually failed.
"""

from __future__ import annotations

import pytest

from niharamesh.domain.config import FeatureFlags, SimulationConfig
from niharamesh.domain.coordination import FreshnessClass
from niharamesh.domain.geometry import OrientedBox, bbox_of
from niharamesh.domain.map import WarehouseMap, Zone
from niharamesh.domain.pose import (
    ActuatorState,
    MotionCommand,
    MotionState,
    Pose2,
    PoseEstimate,
    StopReason,
    UncertaintyModel,
)
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import FreshnessVerdict, Observation, SafetyDecision, SensorObservation
from niharamesh.safety.gate import DEFAULT_STALL_NS, GateContext, SafetyGate
from niharamesh.scenario.builders import AMR_FOOTPRINT, base_warehouse
from niharamesh.scenario.library import cycle_with_holding, three_way_junction

_JUNCTION: str = "zn-junction"
_CYCLE_BOTTOM: str = "zn-cycle-bottom"
_CYCLE_MIDDLE: str = "zn-cycle-middle"

#: A body small enough that the "footprint not centre point" test is meaningful:
#: 0.60 m long, so a centre 0.24 m outside the protected bounds still overlaps.
_BODY_LENGTH_M = 0.60
_BODY_WIDTH_M = 0.40


# --------------------------------------------------------------------------- #
# fixtures / builders
# --------------------------------------------------------------------------- #


def _junction_map() -> WarehouseMap:
    return three_way_junction().map


def _cycle_map() -> WarehouseMap:
    return cycle_with_holding().map


def _bounds(zone: Zone) -> tuple[float, float, float, float]:
    return zone.protected_bounds


def _body(cx: float, cy: float, *, theta: float = 0.0, length: float = _BODY_LENGTH_M) -> OrientedBox:
    return OrientedBox(cx, cy, theta, length, _BODY_WIDTH_M)


def _observation(
    *,
    now_ns: int = 0,
    actuation_enabled: bool = True,
    localisation_age_ns: int = 0,
    sensor_age_ns: int = 0,
    sensor_dropped: bool = False,
) -> Observation:
    """A clean, live observation. Individual tests degrade exactly one field."""
    return Observation(
        robot_id="amr-01",
        pose_estimate=PoseEstimate(
            map_id="map-junction",
            pose=Pose2(x=2.5, y=6.9, theta=0.0),
            observed_at_ns=max(0, now_ns - localisation_age_ns),
            time_domain=TimeDomain.LOGICAL,
            uncertainty=UncertaintyModel(kind="gaussian_sigma", sigma_m=0.02, sigma_rad=0.01),
        ),
        motion=MotionState(actuator=ActuatorState.ENABLED, actuation_enabled=actuation_enabled),
        sensor=SensorObservation(
            robot_id="amr-01",
            observed_at_ns=max(0, now_ns - sensor_age_ns),
            delivered_at_ns=max(0, now_ns - sensor_age_ns),
            rays=(),
            dropped=sensor_dropped,
        ),
        battery_fraction=0.9,
        sim_time_ns=now_ns,
    )


def _command(*, linear: float = 0.4, now_ns: int = 0, ttl_s: float = 0.4) -> MotionCommand:
    return MotionCommand(
        robot_id="amr-01",
        command_seq=1,
        linear_mps=linear,
        angular_radps=0.0,
        issued_at_ns=now_ns,
        expires_at_ns=now_ns + int(ttl_s * 1e9),
        time_domain=TimeDomain.LOGICAL,
    )


def _gate(
    warehouse_map: WarehouseMap | None = None,
    *,
    config: SimulationConfig | None = None,
) -> SafetyGate:
    return SafetyGate(
        config=config or SimulationConfig(),
        warehouse_map=warehouse_map or _junction_map(),
        robot_id="amr-01",
    )


#: A body in open floor, far from every zone in both maps used below. It is the
#: default zone evidence for contexts whose *own* subject is a different check:
#: the zone check runs before the obstacle and battery checks, so without it every
#: other constraint would be masked by ``no_zone_geometry_evidence``.
_OPEN_BODY = _body(2.5, 6.9)


def _context(**overrides: object) -> GateContext:
    """A clean context. Every override replaces exactly one fact.

    Defaults to a swept body in open space so that a test about, say, battery
    reserve isolates battery reserve rather than tripping the zone check first.
    Pass ``swept_body=None`` explicitly to exercise the abstention path.
    """
    fields: dict[str, object] = {
        "observation": _observation(),
        "now_ns": 0,
        "swept_body": _OPEN_BODY,
    }
    fields.update(overrides)
    return GateContext(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 1. Legitimate open-space motion is permitted
# --------------------------------------------------------------------------- #


def test_open_space_motion_is_permitted_without_any_zone_authority() -> None:
    """A robot crossing open floor is never asked for zone authority.

    This is a deliberate behaviour change from ``no_zone_authority``. It used to
    veto *every* moving command that held no zone authority, which is why the
    reproduced baseline showed 1200 vetoes per robot and nothing ever moved.
    """
    gate = _gate()
    context = _context(
        zone_authority=None,
        entry_permission=None,
        occupied_zone=None,
        swept_body=_body(2.5, 6.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, decision
    assert decision.reason is StopReason.NONE
    assert decision.limiting_constraint == ""


def test_a_swept_body_far_from_every_zone_is_permitted_with_a_zero_stop_command() -> None:
    """The same rule applies to a command that is already at rest."""
    gate = _gate(_cycle_map())
    context = _context(swept_body=_body(2.5, 6.9))
    decision = gate.evaluate(_command(linear=0.0), 0, context)
    assert decision.permitted is True, decision


# --------------------------------------------------------------------------- #
# 2. Protected entry needs complete authority
# --------------------------------------------------------------------------- #


def test_unauthorised_protected_entry_is_vetoed() -> None:
    """Swept body inside the protected bounds with no entry permission: refuse."""
    warehouse_map = _junction_map()
    zone = warehouse_map.zone(_JUNCTION)
    bounds = _bounds(zone)
    assert _body(13.5, 11.9).cx == pytest.approx((bounds[0] + bounds[2]) / 2.0)

    gate = _gate(warehouse_map)
    context = _context(
        zone_authority=None,
        entry_permission=None,
        occupied_zone=None,
        swept_body=_body(13.5, 11.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert _JUNCTION in decision.limiting_constraint


def test_authority_for_another_zone_does_not_permit_entry() -> None:
    """Authority for one zone is not authority for another.

    Uses real geometry with three disjoint zones, so the wrong zone genuinely
    exists and the correct one genuinely differs.
    """
    warehouse_map = _cycle_map()
    gate = _gate(warehouse_map)
    middle = warehouse_map.zone(_CYCLE_MIDDLE)
    assert _bounds(warehouse_map.zone(_CYCLE_BOTTOM))[3] < _bounds(middle)[1], "zones overlap"

    context = _context(
        zone_authority=_CYCLE_BOTTOM,
        entry_permission=None,
        occupied_zone=None,
        swept_body=_body(8.9, 9.0),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert _CYCLE_MIDDLE in decision.limiting_constraint
    assert _CYCLE_BOTTOM not in decision.limiting_constraint, (
        "the constraint must name the zone that was actually entered"
    )


def test_complete_entry_permission_permits_entry() -> None:
    """The granted case: ``entry_permission`` names the zone being entered."""
    gate = _gate()
    context = _context(
        zone_authority=_JUNCTION,
        entry_permission=_JUNCTION,
        occupied_zone=None,
        swept_body=_body(13.5, 11.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, decision


def test_a_swept_body_that_only_overlaps_by_its_corner_is_still_an_entry() -> None:
    """Touching counts. A clearance of exactly zero is not a safe clearance."""
    warehouse_map = _junction_map()
    zone = warehouse_map.zone(_JUNCTION)
    gate = _gate(warehouse_map)
    x0, y0, x1, _y1 = _bounds(zone)
    assert x1 > x0, "the premise: the zone has extent"
    # Centred half a body short of the edge, so its trailing face is *on* the bound.
    edge_body = _body(x0 - _BODY_WIDTH_M / 2.0, y0 - _BODY_WIDTH_M / 2.0, length=_BODY_WIDTH_M)
    assert bbox_of(edge_body)[2] == pytest.approx(x0)
    assert bbox_of(edge_body)[3] == pytest.approx(y0)

    context = _context(swept_body=edge_body, entry_permission=None, zone_authority=None)
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING


# --------------------------------------------------------------------------- #
# 3. Footprint, not centre point
# --------------------------------------------------------------------------- #


def test_a_footprint_that_already_intersects_the_zone_is_vetoed_although_its_centre_is_outside() -> None:
    """Real geometry from a real scenario map.

    The centre sits outside ``zn-junction``'s protected bounds while the chassis
    has already crossed the edge. A centre-point test would call this clear.
    """
    warehouse_map = _junction_map()
    gate = _gate(warehouse_map)
    zone = warehouse_map.zone(_JUNCTION)
    x0, _y0, _x1, _y1 = _bounds(zone)
    cx = x0 - 0.24  # outside the bound; the 0.60 m chassis reaches 0.06 m past it
    body = _body(cx, 11.9)

    assert zone.contains_point(cx, 11.9) is False, "the premise: the centre is outside"
    assert bbox_of(body)[2] > x0, "the premise: the footprint is not"

    gate = _gate(warehouse_map)
    context = _context(
        zone_authority=None,
        entry_permission=None,
        occupied_zone=None,
        swept_body=body,
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert _JUNCTION in decision.limiting_constraint


def test_the_gate_does_not_inflate_the_protected_bounds_a_second_time() -> None:
    """A body that clears the *authored* protected geometry is permitted.

    ``aisle_zone`` already inflates the corridor by the robot clearance radius.
    If the gate inflated again, a robot legally waiting outside a zone would be
    refused, and the refusal would be an artefact rather than a safety decision.
    """
    warehouse_map = _junction_map()
    zone = warehouse_map.zone(_JUNCTION)
    gate = _gate(warehouse_map)
    x0, y0, _x1, _y1 = _bounds(zone)
    clearance = AMR_FOOTPRINT.clearance_radius_m()
    # Wholly outside the authored bound, but inside the corridor the author
    # inflated by the robot clearance radius -- so a second inflation here would
    # refuse a robot standing exactly where the map says it may queue.
    gap = 0.02
    just_outside = _body(
        x0 - _BODY_WIDTH_M / 2.0 - gap,
        y0 - _BODY_WIDTH_M / 2.0 - gap,
        length=_BODY_WIDTH_M,
    )
    assert clearance > gap, "the test is only meaningful inside the authored margin"
    assert bbox_of(just_outside)[2] == pytest.approx(x0 - gap)
    assert bbox_of(just_outside)[3] == pytest.approx(y0 - gap)

    context = _context(swept_body=just_outside, entry_permission=None, zone_authority=None)
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, (
        f"the gate re-inflated protected geometry: {decision.limiting_constraint}"
    )


# --------------------------------------------------------------------------- #
# 4. Occupancy is retained
# --------------------------------------------------------------------------- #


def test_retained_authority_permits_continuing_inside_an_occupied_zone() -> None:
    """Inside a zone you hold authority over, ``entry_permission`` is irrelevant.

    This is the third intended consequence of the contract: authority and entry
    permission are no longer the same question once the body is inside.
    """
    gate = _gate()
    context = _context(
        occupied_zone=_JUNCTION,
        zone_authority=_JUNCTION,
        entry_permission=None,
        swept_body=_body(13.5, 11.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, decision


def test_occupancy_without_retained_authority_is_vetoed() -> None:
    """Being inside is not permission. A body inside with no retained authority stops."""
    gate = _gate()
    context = _context(
        occupied_zone=_JUNCTION,
        zone_authority=None,
        entry_permission=None,
        swept_body=_body(13.5, 11.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert decision.limiting_constraint == f"unauthorised_occupancy:{_JUNCTION}"


def test_entry_permission_does_not_substitute_for_retained_authority_inside_a_zone() -> None:
    """Holding entry permission is not the same as retaining authority once inside."""
    gate = _gate()
    context = _context(
        occupied_zone=_JUNCTION,
        zone_authority=None,
        entry_permission=_JUNCTION,
        swept_body=_body(13.5, 11.9),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.limiting_constraint == f"unauthorised_occupancy:{_JUNCTION}"


def test_retained_authority_for_a_zone_this_body_has_left_is_not_silence() -> None:
    """Leaving is fine; the veto applies to the zone the body is actually in.

    Retained authority over a *different* zone does not authorise the one entered.
    """
    warehouse_map = _cycle_map()
    gate = _gate(warehouse_map)
    context = _context(
        occupied_zone=_CYCLE_MIDDLE,
        zone_authority=_CYCLE_BOTTOM,
        entry_permission=None,
        swept_body=_body(8.9, 9.0),
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.limiting_constraint == f"unauthorised_occupancy:{_CYCLE_MIDDLE}"


# --------------------------------------------------------------------------- #
# 5. Abstention when no swept body is supplied  (documented decision)
# --------------------------------------------------------------------------- #


def test_a_missing_swept_body_falls_back_to_the_occupied_box() -> None:
    """Degraded but usable evidence: the body's current reservations.

    ``occupied_box`` is this robot's *own* reservation body, so it is a real
    (if less conservative) witness. It must be consulted rather than ignored.
    """
    gate = _gate()
    context = _context(
        swept_body=None,
        occupied_box=_body(13.5, 11.9),
        entry_permission=None,
        zone_authority=None,
    )
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert _JUNCTION in decision.limiting_constraint


def test_the_occupied_box_fallback_permits_open_space_too() -> None:
    """The fallback must not be a blanket refusal either."""
    gate = _gate()
    context = _context(swept_body=None, occupied_box=_body(2.5, 6.9))
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, decision


def test_with_no_body_evidence_at_all_a_moving_command_fails_closed() -> None:
    """Abstention, decided explicitly and documented.

    With neither ``swept_body`` nor ``occupied_box`` the gate holds *no*
    geometry, so it cannot show that the command stays clear of protected
    geometry. The gate is permitted to be wrong in one direction only, so a
    command that could move is refused. The constraint says exactly why, because
    a refusal that hides its own cause is not an attributable stop.
    """
    gate = _gate()
    context = _context(swept_body=None, occupied_box=None, entry_permission=None, zone_authority=None)
    decision = gate.evaluate(_command(linear=0.4), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert "zone" in decision.limiting_constraint
    assert "geometry" in decision.limiting_constraint


def test_with_no_body_evidence_at_all_open_space_is_permitted() -> None:
    """The mirror case: a map with no protected zones has nothing to enter."""
    zoneless = base_warehouse("map-zoneless", "No zones")
    assert zoneless.zones == ()
    gate = _gate(zoneless)
    context = _context(swept_body=None, occupied_box=None)
    decision = gate.evaluate(_command(linear=0.4), 0, context)
    assert decision.permitted is True, decision


def test_a_command_that_cannot_move_needs_no_zone_geometry() -> None:
    """Zero velocity and zero rate: nothing can newly enter protected geometry."""
    gate = _gate()
    context = _context(swept_body=None, occupied_box=None)
    decision = gate.evaluate(_command(linear=0.0), 0, context)
    assert decision.permitted is True, decision


def test_gate_context_has_no_inside_zone_field() -> None:
    """The ambiguous field is gone, not merely ignored.

    Leaving it in place would let a caller keep satisfying the zone check with
    "the next zone on my plan", which is the bypass this contract removes.
    """
    assert not hasattr(GateContext, "inside_zone")
    assert not hasattr(GateContext(observation=_observation(), now_ns=0), "inside_zone")


# --------------------------------------------------------------------------- #
# 6. Every other gate constraint still vetoes for its own reason
# --------------------------------------------------------------------------- #


def test_a_dead_actuator_chain_is_vetoed() -> None:
    gate = _gate()
    context = _context(observation=_observation(actuation_enabled=False))
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.ACTUATOR_FAULT
    assert decision.limiting_constraint == "actuation_disabled"


def test_unsafe_research_flags_never_gate_physical_actuation() -> None:
    """Construction already refuses this; the gate keeps the structural refusal.

    ``model_copy`` does not re-run validators, which is the only way to reach
    the branch from a test -- and exactly the situation it defends against.
    """
    forbidden = SimulationConfig().model_copy(
        update={
            "physical_actuation_enabled": True,
            "features": FeatureFlags(disable_safety_gate=True),
        }
    )
    gate = _gate(config=forbidden)
    decision = gate.evaluate(_command(), 0, _context())
    assert decision.permitted is False
    assert decision.reason is StopReason.ACTUATOR_FAULT
    assert decision.limiting_constraint == "unsafe_research_flags"


def test_an_expired_command_is_vetoed_with_its_evidence_age() -> None:
    """The watchdog bound is checked before anything else, and reports the gap."""
    gate = _gate()
    now_ns = 1_000_000_000
    context = _context(observation=_observation(now_ns=now_ns), now_ns=now_ns)
    decision = gate.evaluate(_command(now_ns=0, ttl_s=0.2), now_ns, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.COMMAND_EXPIRED
    assert decision.limiting_constraint == "command_expired"
    assert decision.evidence_age_ns == pytest.approx(0.8e9)


def test_a_command_expiring_exactly_now_is_not_yet_expired() -> None:
    """The expiry check is strict ``<``: a command at its boundary is still live."""
    gate = _gate()
    now_ns = 1_000_000_000
    context = _context(observation=_observation(now_ns=now_ns), now_ns=now_ns)
    decision = gate.evaluate(_command(now_ns=0, ttl_s=1.0), now_ns, context)
    assert decision.permitted is True, decision


def test_an_operator_stop_request_is_vetoed() -> None:
    gate = _gate()
    decision = gate.evaluate(_command(), 0, _context(operator_stop=True))
    assert decision.permitted is False
    assert decision.reason is StopReason.OPERATOR_REQUEST
    assert decision.limiting_constraint == "operator_stop_requested"


def test_an_operator_command_has_no_privileged_path_through_the_gate() -> None:
    """The command type carries no issuer, so no command can be exempt."""
    gate = _gate()
    override = _command(linear=0.4).model_copy(update={"hold_position": False})
    decision = gate.evaluate(override, 0, _context(swept_body=_body(13.5, 11.9)))
    assert decision.permitted is False
    assert decision.reason is StopReason.ZONE_AUTHORITY_MISSING
    assert set(MotionCommand.model_fields) == {
        "robot_id",
        "command_seq",
        "linear_mps",
        "angular_radps",
        "issued_at_ns",
        "expires_at_ns",
        "time_domain",
        "hold_position",
    }, "a privileged-path field appeared on MotionCommand"


def test_a_stalled_control_loop_is_vetoed() -> None:
    """The stall detector still fails closed."""
    gate = _gate()
    decision = gate.evaluate(_command(), 0, _context(control_loop_age_ns=DEFAULT_STALL_NS + 1))
    assert decision.permitted is False
    assert decision.reason is StopReason.CONTROL_LOOP_STALLED
    assert "control_loop_age" in decision.limiting_constraint


def test_a_control_loop_age_exactly_at_the_bound_is_permitted() -> None:
    """The bound is inclusive: the check is ``>`` ``DEFAULT_STALL_NS``."""
    gate = _gate()
    decision = gate.evaluate(_command(), 0, _context(control_loop_age_ns=DEFAULT_STALL_NS))
    assert decision.permitted is True, decision


def test_stale_localisation_is_vetoed_with_its_evidence_age() -> None:
    gate = _gate()
    now_ns = 2_000_000_000
    context = _context(observation=_observation(now_ns=now_ns, localisation_age_ns=1_500_000_000))
    decision = gate.evaluate(_command(now_ns=now_ns), now_ns, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.STALE_LOCALISATION
    assert decision.limiting_constraint == "localisation_stale"
    assert decision.evidence_age_ns == pytest.approx(1.5e9)


def test_a_dropped_sensor_observation_that_is_also_too_old_is_vetoed() -> None:
    gate = _gate()
    config = SimulationConfig()
    now_ns = 1_000_000_000
    too_old = int(config.sensor.observation_latency_s * 2e9) + 1
    context = _context(observation=_observation(now_ns=now_ns, sensor_age_ns=too_old, sensor_dropped=True))
    decision = gate.evaluate(_command(now_ns=now_ns), now_ns, context)
    assert decision.permitted is False
    assert decision.reason is StopReason.STALE_LOCALISATION
    assert decision.limiting_constraint == "sensor_observation_dropped"


def test_a_dropped_but_recent_observation_does_not_veto() -> None:
    """A dropout inside the declared latency budget is not stale evidence."""
    gate = _gate()
    context = _context(observation=_observation(sensor_dropped=True, sensor_age_ns=10_000_000))
    decision = gate.evaluate(_command(), 0, context)
    assert decision.permitted is True, decision


def test_an_unusable_peer_intent_is_vetoed() -> None:
    gate = _gate()
    verdict = FreshnessVerdict(FreshnessClass.STALE, 4.0e9, 0, "age beyond horizon")
    decision = gate.evaluate(_command(), 0, _context(intent_freshness=verdict))
    assert decision.permitted is False
    assert decision.reason is StopReason.FRESHNESS_UNCERTAIN
    assert decision.limiting_constraint == "peer_intent_stale"


def test_an_unknown_freshness_class_is_treated_exactly_like_stale() -> None:
    """Uncertainty grants no permission, and the stop is identical."""
    gate = _gate()
    unknown = FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "clock relation unestablished")
    stale = FreshnessVerdict(FreshnessClass.STALE, 4.0e9, 0, "age beyond horizon")
    from_unknown = gate.evaluate(_command(), 0, _context(intent_freshness=unknown))
    from_stale = gate.evaluate(_command(), 0, _context(intent_freshness=stale))
    assert from_unknown.permitted is from_stale.permitted is False
    assert from_unknown.reason is from_stale.reason is StopReason.FRESHNESS_UNCERTAIN
    assert "unknown" in from_unknown.limiting_constraint


def test_an_unusable_peer_verdict_is_vetoed_and_names_the_peer() -> None:
    gate = _gate()
    verdicts = {
        "amr-01": FreshnessVerdict(FreshnessClass.FRESH, 1.0e8, 0, "ok"),
        "amr-03": FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "unestablished"),
    }
    decision = gate.evaluate(_command(), 0, _context(peer_freshness=verdicts))
    assert decision.permitted is False
    assert decision.reason is StopReason.FRESHNESS_UNCERTAIN
    assert "amr-03" in decision.limiting_constraint


def test_battery_below_the_reserve_is_vetoed() -> None:
    gate = _gate()
    decision = gate.evaluate(_command(), 0, _context(battery_fraction=0.05))
    assert decision.permitted is False
    assert decision.reason is StopReason.ACTUATOR_FAULT
    assert decision.limiting_constraint == "battery_below_reserve"


def test_an_unknown_battery_fraction_never_blocks() -> None:
    """Missing is ``unavailable``, not zero. Uncertainty here blocks nothing."""
    gate = _gate()
    decision = gate.evaluate(_command(), 0, _context(battery_fraction=None))
    assert decision.permitted is True, decision


def test_an_obstacle_inside_the_stopping_budget_is_vetoed() -> None:
    gate = _gate()
    config = SimulationConfig()
    margin = config.stopping.total_distance_m
    decision = gate.evaluate(_command(), 0, _context(obstacle_distance_m=margin - 0.01))
    assert decision.permitted is False
    assert decision.reason is StopReason.OBSTACLE_IN_PATH
    assert "0.310" in decision.limiting_constraint


def test_an_obstacle_exactly_at_the_stopping_budget_is_permitted() -> None:
    """The budget is the required clearance, so the boundary is safe."""
    gate = _gate()
    margin = SimulationConfig().stopping.total_distance_m
    decision = gate.evaluate(_command(), 0, _context(obstacle_distance_m=margin))
    assert decision.permitted is True, decision


def test_every_veto_is_logged_with_its_reason_and_constraint() -> None:
    """Vetoes are observable, so the UI can say *why* rather than "stopped"."""
    gate = _gate()
    gate.evaluate(_command(), 0, _context(battery_fraction=0.01))
    gate.evaluate(_command(), 0, _context(swept_body=_body(2.5, 6.9)))
    log = gate.recent_decisions()
    assert [entry.permitted for entry in log] == [False, True]
    assert log[0].reason is StopReason.ACTUATOR_FAULT
    assert log[0].constraint == "battery_below_reserve"


def test_evaluate_without_a_context_permits_and_records_nothing() -> None:
    """Unchanged API: no context means only the checks needing no evidence.

    An incomplete check must not be reported as a complete one, so the gate says
    ``permitted`` rather than inventing a verdict -- and it records nothing.
    """
    gate = _gate()
    decision = gate.evaluate(_command(), 0, None)
    assert isinstance(decision, SafetyDecision)
    assert decision.permitted is True
    assert gate.recent_decisions() == []


# --------------------------------------------------------------------------- #
# 7. The gate's own geometry helper
# --------------------------------------------------------------------------- #


def test_body_touches_bounds_is_a_corner_aabb_test() -> None:
    from niharamesh.safety.gate import _body_touches_bounds

    bounds = (10.0, 10.0, 12.0, 12.0)
    assert _body_touches_bounds(_body(11.0, 11.0), bounds) is True
    assert _body_touches_bounds(_body(9.0, 11.0), bounds) is False
    # Rotated: a 45-degree body reaches further than its half-diagonal-free AABB.
    diagonal = OrientedBox(10.0, 11.0, 0.7853981633974483, 2.0, 0.2)
    assert _body_touches_bounds(diagonal, bounds) is True
    assert _body_touches_bounds(_body(5.0, 5.0), bounds) is False

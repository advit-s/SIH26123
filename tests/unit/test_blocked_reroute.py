"""Blocked-route policy: compare an alternative with waiting, explicitly.

The point of these tests is that the decision is *explained*: the numbers behind
it, the rule, and the evidence's age all travel with the outcome, so an operator
can see why a robot went round instead of waiting.
"""

from __future__ import annotations

import math

import pytest

from niharamesh.domain.units import TimeDomain
from niharamesh.planning.astar import PathResult, PathStatus, UnreachableReason
from niharamesh.planning.blocked import (
    BlockedRoutePolicy,
    ObstructionEvidence,
    RouteAction,
    build_path_plan,
)
from niharamesh.planning.path import PathPlan

NS = 1_000_000_000


def plan(estimated_duration_s: float, *, touches_zone: bool = True) -> PathPlan:
    return PathPlan(
        waypoints=((0.0, 0.0), (estimated_duration_s, 0.0)),
        length_m=estimated_duration_s,
        estimated_duration_s=estimated_duration_s,
        turn_count=0,
        version=1,
        zones_touched=("aisle-a",) if touches_zone else (),
        stop_line_id=None,
    )


def evidence(
    *, observed_at_ns: int = 0, now_ns: int = 0, zone_id: str | None = "aisle-a"
) -> ObstructionEvidence:
    return ObstructionEvidence(
        zone_id=zone_id,
        position=(10.0, 4.5),
        kind="stationary_obstacle",
        observed_at_ns=observed_at_ns,
        now_ns=now_ns,
        time_domain=TimeDomain.SIM_SECONDS,
        confidence=0.9,
    )


def test_cheaper_alternative_than_the_wait_estimate_replans() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate(
        "aisle-a",
        evidence(observed_at_ns=0, now_ns=200_000_000),
        plan(30.0),
        plan(5.0),
        wait_estimate_s=20.0,
    )
    assert decision.action is RouteAction.REPLAN
    assert decision.replan is True
    assert decision.comparison.alternative_cost_s == pytest.approx(5.0)
    assert decision.comparison.expected_wait_s == pytest.approx(20.0)
    assert decision.comparison.threshold_s == pytest.approx(16.0)
    assert decision.comparison.margin_s == pytest.approx(11.0)
    assert "aisle-a" in decision.reason


def test_cheaper_wait_than_the_alternative_waits() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate(
        "aisle-a",
        evidence(observed_at_ns=0, now_ns=100_000_000),
        plan(30.0),
        plan(30.0),
        wait_estimate_s=10.0,
    )
    assert decision.action is RouteAction.WAIT
    assert decision.wait is True
    assert decision.comparison.threshold_s == pytest.approx(8.0)
    assert decision.comparison.alternative_cost_s == pytest.approx(30.0)


def test_the_margin_is_what_keeps_the_decision_stable_near_parity() -> None:
    """With a ratio of 1.0 this alternative would be preferred; at 0.8 it is not.

    This is the documented reason for the 0.8: both estimates are optimistic, so a
    decision taken on parity would flip whenever the two numbers land inside each
    other's error bars.
    """
    policy = BlockedRoutePolicy()
    wait = 10.0
    slightly_cheaper = 9.0  # cheaper than the wait, but inside the margin
    decision = policy.evaluate("aisle-a", evidence(now_ns=0), plan(30.0), plan(slightly_cheaper), wait)
    assert decision.action is RouteAction.WAIT
    assert decision.comparison.threshold_s == pytest.approx(8.0)

    clearly_cheaper = 7.0
    replan = policy.evaluate("aisle-a", evidence(now_ns=0), plan(30.0), plan(clearly_cheaper), wait)
    assert replan.action is RouteAction.REPLAN

    with pytest.raises(ValueError, match="replan_ratio"):
        BlockedRoutePolicy(replan_ratio=1.5)


def test_unreachable_alternative_waits_with_the_planner_reason_quoted() -> None:
    policy = BlockedRoutePolicy()
    failed = PathResult(
        status=PathStatus.UNREACHABLE,
        reason="goal (10.000, 2.000) lies in static map geometry",
        unreachable_reason=UnreachableReason.BLOCKED_GOAL,
    )
    decision = policy.evaluate_from_results(
        "aisle-a",
        evidence(now_ns=0),
        plan(30.0),
        failed,
        wait_estimate_s=2.0,
    )
    assert decision.action is RouteAction.WAIT
    assert "alternative_plan_unreachable" in decision.reason
    assert "blocked_goal" in decision.reason
    assert "static map geometry" in decision.reason
    assert decision.comparison.alternative_available is False


def test_no_alternative_plan_at_all_waits() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate("aisle-a", evidence(now_ns=0), plan(30.0), None, 2.0)
    assert decision.action is RouteAction.WAIT
    assert "no_alternative_plan" in decision.reason


def test_no_current_plan_replans_because_there_is_nothing_to_wait_on() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate("aisle-a", evidence(now_ns=0), None, plan(99.0), 1.0)
    assert decision.action is RouteAction.REPLAN
    assert decision.reason == "no_current_plan"


def test_unverified_or_stale_evidence_never_moves_the_robot() -> None:
    policy = BlockedRoutePolicy(stale_after_ns=2 * NS)
    cheap = plan(1.0)

    unverified = policy.evaluate("aisle-a", None, plan(30.0), cheap, 60.0)
    assert unverified.action is RouteAction.WAIT
    assert "no_obstruction_evidence" in unverified.reason

    stale = policy.evaluate("aisle-a", evidence(observed_at_ns=0, now_ns=5 * NS), plan(30.0), cheap, 60.0)
    assert stale.action is RouteAction.WAIT
    assert "obstruction_evidence_stale" in stale.reason
    assert "5.000 s old" in stale.reason

    fresh = policy.evaluate("aisle-a", evidence(observed_at_ns=0, now_ns=1 * NS), plan(30.0), cheap, 60.0)
    assert fresh.action is RouteAction.REPLAN


def test_a_clear_queue_is_never_rerouted_around() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate("aisle-a", evidence(now_ns=0), plan(30.0), plan(0.1), 0.0)
    assert decision.action is RouteAction.WAIT
    assert "queue_already_clear" in decision.reason


def test_obstruction_report_carries_non_zero_age_and_provenance() -> None:
    policy = BlockedRoutePolicy(stale_after_ns=2 * NS)
    report = policy.share_obstruction(
        evidence(observed_at_ns=250_000_000, now_ns=1_250_000_000),
        robot_id="r1",
        session_id="s1",
    )
    assert report.robot_id == "r1"
    assert report.session_id == "s1"
    assert report.zone_id == "aisle-a"
    assert report.observed_at_ns == 250_000_000
    assert report.observation_age_ns == 1_000_000_000
    assert report.observation_age_ns > 0
    assert report.time_domain is TimeDomain.SIM_SECONDS
    assert report.confidence < 0.9  # faded by age, but never raised above the claim
    assert report.confidence > 0.0
    assert report.confidence == pytest.approx(0.9 * (1.0 - 1.0 / 2.0))

    fresh = policy.share_obstruction(evidence(observed_at_ns=0, now_ns=0), robot_id="r1", session_id="s1")
    assert fresh.observation_age_ns == 0
    assert fresh.confidence == pytest.approx(0.9)


def test_obstruction_report_can_override_position_and_kind() -> None:
    policy = BlockedRoutePolicy()
    report = policy.share_obstruction(
        evidence(now_ns=0),
        robot_id="r2",
        session_id="s2",
        position=(1.0, 2.0),
        kind="spilled_pallet",
    )
    assert report.position == (1.0, 2.0)
    assert report.kind == "spilled_pallet"


def test_build_path_plan_requires_a_successful_result() -> None:
    with pytest.raises(ValueError, match="successful"):
        build_path_plan(PathResult(status=PathStatus.UNREACHABLE))
    ok = PathResult(
        status=PathStatus.OK,
        waypoints=((0.0, 0.0), (1.0, 0.0)),
        length_m=1.0,
        cost_s=2.5,
        turn_count=0,
        version=4,
    )
    wrapped = build_path_plan(ok)
    assert wrapped.estimated_duration_s == pytest.approx(2.5)
    assert wrapped.version == 4
    assert wrapped.zones_touched == ()


def test_wait_estimate_must_not_be_negative() -> None:
    policy = BlockedRoutePolicy()
    with pytest.raises(ValueError, match="non-negative"):
        policy.evaluate("aisle-a", evidence(now_ns=0), plan(1.0), plan(1.0), -0.5)


def test_decision_rule_is_stated_in_the_comparison() -> None:
    policy = BlockedRoutePolicy()
    decision = policy.evaluate("aisle-a", evidence(now_ns=0), plan(30.0), plan(5.0), 20.0)
    assert "replan when alternative_cost_s <" in decision.comparison.rule
    assert "0.8" in decision.comparison.rule
    assert math.isclose(
        decision.comparison.margin_s,
        decision.comparison.threshold_s - (decision.comparison.alternative_cost_s or 0.0),
    )

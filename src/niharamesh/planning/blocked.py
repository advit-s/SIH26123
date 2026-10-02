"""Blocked-route policy: compare a feasible alternative with waiting.

The rule
--------
``BlockedRoutePolicy`` answers exactly one question - *should this robot stop and
wait for the obstructed zone, or take a different route?* - by comparing two
declared estimates:

    REPLAN  when  alternative_cost_s < expected_wait_s * REPLAN_RATIO

with ``REPLAN_RATIO = 0.8``.

Why 0.8 and not 1.0
~~~~~~~~~~~~~~~~~~~~
Both estimates are optimistic, and they fail in opposite directions:

* ``alternative_cost_s`` comes from :mod:`niharamesh.planning.path`, which
  divides length by the *declared* maximum speed and adds one rotation per
  heading change. It contains no acceleration, no braking and no tracking error,
  so it systematically **under**-estimates the alternative.
* ``expected_wait_s`` comes from the caller's own belief about the queue ahead.
  A queue that clears early makes the wait **shorter** than estimated.

A threshold of exactly 1.0 would flip the decision whenever the two estimates
come within their own error bars, and the robot would oscillate between replanning
and waiting on every re-evaluation. The 0.8 margin demands that the alternative
be 20% cheaper before the robot pays for it, which keeps the decision stable in
the region where the inputs are untrustworthy. This is a **configured
preference**, chosen for stability; it is not derived from measurement and it is
not optimal for any particular warehouse.

The decision is never made on a stale or missing premise. In order, the policy
refuses to replan when:

1. there is no current plan at all (``no_current_plan`` -> REPLAN, there is
   nothing to wait on);
2. the alternative plan is missing or did not succeed -> WAIT, and the
   alternative's own failure reason is quoted verbatim;
3. there is no obstruction evidence -> WAIT (``no_obstruction_evidence``): an
   unverifiable claim must not move a robot off a good route;
4. the evidence is older than ``stale_after_ns`` -> WAIT
   (``obstruction_evidence_stale``);
5. the estimated wait is zero -> WAIT (``queue_already_clear``): if nothing is
   actually blocking, do not thrash.

Everything this policy emits is an estimate. The zone-grant protocol still
decides whether entry is permitted at all, and the safety gate still vetoes
every command.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from niharamesh.domain.coordination import ObstructionReport
from niharamesh.domain.units import TimeDomain
from niharamesh.planning.astar import PathResult
from niharamesh.planning.path import PathPlan

__all__ = [
    "BlockedRoutePolicy",
    "CostComparison",
    "ObstructionEvidence",
    "RouteAction",
    "RouteDecision",
]

#: See the module docstring for the argument behind this number.
REPLAN_RATIO: float = 0.8


class RouteAction(StrEnum):
    REPLAN = "replan"
    WAIT = "wait"


@dataclass(frozen=True, slots=True)
class CostComparison:
    """The numbers behind the decision. Always shown, never summarised away."""

    alternative_cost_s: float | None
    expected_wait_s: float
    threshold_s: float
    rule: str
    margin_s: float | None
    """``threshold_s - alternative_cost_s``; positive means the alternative wins."""

    @property
    def alternative_available(self) -> bool:
        return self.alternative_cost_s is not None


@dataclass(frozen=True, slots=True)
class RouteDecision:
    action: RouteAction
    reason: str
    comparison: CostComparison

    @property
    def replan(self) -> bool:
        return self.action is RouteAction.REPLAN

    @property
    def wait(self) -> bool:
        return self.action is RouteAction.WAIT


@dataclass(frozen=True, slots=True)
class ObstructionEvidence:
    """What this robot believes about an obstruction, with its age.

    ``observed_at_ns`` and ``now_ns`` share one :class:`TimeDomain`, which is
    recorded explicitly: subtracting an age across two clock domains would be a
    category error (AGENTS.md rule 8).
    """

    zone_id: str | None
    position: tuple[float, float]
    kind: str
    observed_at_ns: int
    now_ns: int
    time_domain: TimeDomain
    confidence: float = 0.8

    @property
    def observation_age_ns(self) -> int:
        """Age at *now*. Zero when the claim is in the future: we report zero
        rather than a negative age, and the reader can see the claim was
        timestamped ahead of this robot's clock."""
        return max(0, self.now_ns - self.observed_at_ns)


class BlockedRoutePolicy:
    """Compare a feasible alternative route with waiting."""

    def __init__(
        self,
        *,
        replan_ratio: float = REPLAN_RATIO,
        stale_after_ns: int = 2_000_000_000,
    ) -> None:
        if not (0.0 < replan_ratio <= 1.0):
            raise ValueError("replan_ratio must be in (0, 1]")
        if stale_after_ns <= 0:
            raise ValueError("stale_after_ns must be positive")
        self.replan_ratio = replan_ratio
        self.stale_after_ns = stale_after_ns

    def evaluate(
        self,
        blocked_zone_id: str | None,
        obstruction: ObstructionEvidence | None,
        current_plan: PathPlan | None,
        alternative_plan: PathPlan | None,
        wait_estimate_s: float,
    ) -> RouteDecision:
        """Decide between waiting and replanning. See the module docstring."""
        if wait_estimate_s < 0.0:
            raise ValueError("wait_estimate_s must be non-negative")
        threshold_s = wait_estimate_s * self.replan_ratio
        rule = (
            f"replan when alternative_cost_s < {threshold_s:.3f} s "
            f"(expected_wait_s {wait_estimate_s:.3f} s x {self.replan_ratio})"
        )

        if current_plan is None:
            return RouteDecision(
                RouteAction.REPLAN,
                "no_current_plan",
                CostComparison(
                    alternative_cost_s=None
                    if alternative_plan is None
                    else alternative_plan.estimated_duration_s,
                    expected_wait_s=wait_estimate_s,
                    threshold_s=threshold_s,
                    rule=rule,
                    margin_s=None,
                ),
            )

        if alternative_plan is None:
            return RouteDecision(
                RouteAction.WAIT,
                f"no_alternative_plan: obstructed zone {blocked_zone_id!r} has no route",
                CostComparison(None, wait_estimate_s, threshold_s, rule, None),
            )

        if obstruction is None:
            return RouteDecision(
                RouteAction.WAIT,
                f"no_obstruction_evidence: zone {blocked_zone_id!r} obstruction unverified",
                CostComparison(
                    alternative_plan.estimated_duration_s,
                    wait_estimate_s,
                    threshold_s,
                    rule,
                    threshold_s - alternative_plan.estimated_duration_s,
                ),
            )

        age_ns = obstruction.observation_age_ns
        if age_ns > self.stale_after_ns:
            return RouteDecision(
                RouteAction.WAIT,
                (
                    f"obstruction_evidence_stale: {age_ns / 1e9:.3f} s old, limit "
                    f"{self.stale_after_ns / 1e9:.3f} s"
                ),
                CostComparison(
                    alternative_plan.estimated_duration_s,
                    wait_estimate_s,
                    threshold_s,
                    rule,
                    threshold_s - alternative_plan.estimated_duration_s,
                ),
            )

        if wait_estimate_s <= 0.0:
            return RouteDecision(
                RouteAction.WAIT,
                "queue_already_clear: expected wait is zero, so there is nothing to avoid",
                CostComparison(
                    alternative_plan.estimated_duration_s,
                    wait_estimate_s,
                    threshold_s,
                    rule,
                    threshold_s - alternative_plan.estimated_duration_s,
                ),
            )

        alternative_cost_s = alternative_plan.estimated_duration_s
        margin = threshold_s - alternative_cost_s
        replan = alternative_cost_s < threshold_s
        reason = (
            f"alternative {alternative_cost_s:.3f} s "
            f"{'<' if replan else '>='} threshold {threshold_s:.3f} s; "
            f"estimated wait {wait_estimate_s:.3f} s at zone {blocked_zone_id!r}"
        )
        return RouteDecision(
            RouteAction.REPLAN if replan else RouteAction.WAIT,
            reason,
            CostComparison(alternative_cost_s, wait_estimate_s, threshold_s, rule, margin),
        )

    def evaluate_from_results(
        self,
        blocked_zone_id: str | None,
        obstruction: ObstructionEvidence | None,
        current_plan: PathPlan | None,
        alternative: PathResult,
        wait_estimate_s: float,
    ) -> RouteDecision:
        """Convenience: accept a planner :class:`PathResult` for the alternative.

        A failed alternative is quoted with its own status and reason instead of
        being silently downgraded to "no alternative".
        """
        if alternative.ok:
            decision = self.evaluate(
                blocked_zone_id,
                obstruction,
                current_plan,
                build_path_plan(alternative),
                wait_estimate_s,
            )
            return decision
        decision = self.evaluate(blocked_zone_id, obstruction, current_plan, None, wait_estimate_s)
        reason = (
            f"alternative_plan_{alternative.status.value}"
            + (
                f":{alternative.unreachable_reason.value}"
                if alternative.unreachable_reason is not None
                else ""
            )
            + (f" ({alternative.reason})" if alternative.reason else "")
        )
        return RouteDecision(RouteAction.WAIT, reason, decision.comparison)

    def share_obstruction(
        self,
        evidence: ObstructionEvidence,
        robot_id: str,
        session_id: str,
        *,
        position: tuple[float, float] | None = None,
        kind: str | None = None,
    ) -> ObstructionReport:
        """Build the peer message that carries this evidence.

        Provenance travels with the claim: ``observed_at_ns``,
        ``observation_age_ns``, ``time_domain`` and ``confidence``. A peer that
        receives a three-second-old claim can reason about it; a peer that
        receives a bare "zone busy" cannot, and must not have to.
        """
        return ObstructionReport(
            robot_id=robot_id,
            session_id=session_id,
            zone_id=evidence.zone_id,
            position=position if position is not None else evidence.position,
            kind=kind if kind is not None else evidence.kind,
            observation_age_ns=evidence.observation_age_ns,
            observed_at_ns=evidence.observed_at_ns,
            time_domain=evidence.time_domain,
            confidence=_clamp_confidence(
                evidence.confidence, evidence.observation_age_ns, self.stale_after_ns
            ),
        )


def build_path_plan(result: PathResult, *, version: int | None = None) -> PathPlan:
    """Wrap a successful :class:`PathResult` as a measured :class:`PathPlan`.

    Zone and stop-line facts are absent here because a planner result does not
    carry them; they are filled in by :func:`niharamesh.planning.path.build_plan`
    when the caller has the map. The duration is the planner's own cost, which is
    on the same seconds scale by construction.
    """
    if not result.ok:
        raise ValueError("build_path_plan requires a successful PathResult")
    if not math.isfinite(result.cost_s):
        raise ValueError("planner cost must be finite")
    return PathPlan(
        waypoints=result.waypoints,
        length_m=result.length_m,
        estimated_duration_s=result.cost_s,
        turn_count=result.turn_count,
        version=result.version if version is None else version,
        zones_touched=(),
        stop_line_id=None,
    )


def _clamp_confidence(confidence: float, age_ns: int, stale_after_ns: int) -> float:
    """Fade declared confidence linearly to zero at the staleness limit.

    This is a *reporting* convention, not a probability: it tells a reader how
    much of the declared confidence survives the evidence's age, and it never
    promotes a claim above the confidence the observer declared.
    """
    if stale_after_ns <= 0:
        return confidence
    remaining = 1.0 - min(1.0, age_ns / stale_after_ns)
    return round(max(0.0, min(1.0, confidence * remaining)), 6)

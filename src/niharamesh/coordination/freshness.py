"""Freshness classification: is a peer claim old enough that it cannot be used?

The one rule that matters: **a negative raw age is never FRESH.** A message that
appears to have been sent in the future means the clock relationship or the
sender is wrong, and the honest answer to "how old is this?" is UNKNOWN, not
"very fresh".

``UNKNOWN`` is reported distinctly from ``STALE`` and behaves *identically* to
it for permissions (:attr:`~niharamesh.ports.FreshnessVerdict.usable` is False
for both). That is the whole point: reporting and permission must not be
confused.

Clock domains never mix. A message stamped in ``MONOTONIC`` is never subtracted
from a ``LOGICAL`` now without a measured offset **and** an uncertainty bound
smaller than half the horizon; otherwise the answer is UNKNOWN.

See ``docs/protocol/ZONE_PROTOCOL.md`` section 8 for the contract and
``AGENTS.md`` invariant 8 for why.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from niharamesh.clocks import SharedClockEstimator
from niharamesh.domain.coordination import FreshnessClass, Heartbeat, PeerIntent, PeerState
from niharamesh.domain.units import TimeDomain
from niharamesh.ports import FreshnessVerdict

__all__ = [
    "ClockJumpGuard",
    "FreshnessTable",
    "PeerFreshness",
    "classify",
    "classify_intent",
    "classify_logical",
    "classify_peer_state",
    "freshness_of",
    "iter_suspended",
]


class ClockJumpGuard:
    """Detects a local clock that moved backwards.

    A backwards jump makes every age computed since the jump meaningless, so the
    guard forces UNKNOWN until enough consecutive forward readings have been
    seen. It never repairs a value; it only refuses to make a claim.
    """

    __slots__ = ("_forward_run", "_last_ns", "_stable_after", "jumps")

    def __init__(self, stable_after: int = 3) -> None:
        if stable_after < 1:
            raise ValueError("stable_after must be at least one reading")
        self._last_ns: int | None = None
        self._forward_run = 0
        self._stable_after = stable_after
        self.jumps = 0

    def observe(self, now_ns: int) -> None:
        if self._last_ns is not None and now_ns < self._last_ns:
            self.jumps += 1
            self._forward_run = 0
        else:
            self._forward_run += 1
        self._last_ns = now_ns

    @property
    def stable(self) -> bool:
        return self._last_ns is not None and self._forward_run >= self._stable_after


def classify(
    peer_id: str,
    sent_at_ns: int,
    now_ns: int,
    estimator: SharedClockEstimator,
    horizon_ns: int,
) -> FreshnessVerdict:
    """Classify a cross-process timestamp using the conservative age bound.

    ``age_ns`` is a *lower* bound on age: it never under-estimates how old the
    message is, so a lower bound above the horizon really is STALE.
    """
    if horizon_ns <= 0:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "horizon_must_be_positive")
    estimate = estimator.estimate(peer_id)
    if estimate is None:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "no_clock_estimate")
    uncertainty = int(estimate.conservative_uncertainty_ns)
    if uncertainty >= horizon_ns // 2:
        return FreshnessVerdict(
            FreshnessClass.UNKNOWN, None, uncertainty, "uncertainty_exceeds_half_horizon"
        )
    lower_bound = estimator.lower_bound_age_ns(peer_id, sent_at_ns, now_ns)
    if lower_bound is None:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, uncertainty, "no_clock_estimate")
    if lower_bound < 0.0:
        return FreshnessVerdict(
            FreshnessClass.UNKNOWN, lower_bound, uncertainty, "negative_raw_age_is_not_fresh"
        )
    if lower_bound > float(horizon_ns):
        return FreshnessVerdict(
            FreshnessClass.STALE, lower_bound, uncertainty, "age_exceeds_horizon"
        )
    return FreshnessVerdict(FreshnessClass.FRESH, lower_bound, uncertainty, "age_within_horizon")


def classify_logical(message_time_ns: int, now_ns: int, horizon_ns: int) -> FreshnessVerdict:
    """Classify inside one clock domain (the deterministic single-clock mode)."""
    if horizon_ns <= 0:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "horizon_must_be_positive")
    age = float(now_ns - message_time_ns)
    if age < 0.0:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, age, 0, "negative_raw_age_is_not_fresh")
    if age > float(horizon_ns):
        return FreshnessVerdict(FreshnessClass.STALE, age, 0, "age_exceeds_horizon")
    return FreshnessVerdict(FreshnessClass.FRESH, age, 0, "age_within_horizon")


def _domain_guard(verdict_time: TimeDomain, local: TimeDomain) -> FreshnessVerdict | None:
    if verdict_time is not local:
        return FreshnessVerdict(
            FreshnessClass.UNKNOWN,
            None,
            0,
            f"domain_mismatch:{verdict_time.value}!={local.value}",
        )
    if verdict_time is TimeDomain.DISPLAY_UTC:
        return FreshnessVerdict(
            FreshnessClass.UNKNOWN, None, 0, "display_time_is_not_a_clock_domain"
        )
    return None


def _jump_guard(guard: ClockJumpGuard | None) -> FreshnessVerdict | None:
    if guard is not None and not guard.stable:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "local_clock_jump_suspected")
    return None


def classify_peer_state(
    state: PeerState,
    now_ns: int,
    local_domain: TimeDomain,
    horizon_ns: int,
    estimator: SharedClockEstimator | None = None,
    guard: ClockJumpGuard | None = None,
) -> FreshnessVerdict:
    """Classify a published :class:`PeerState`, refusing to mix domains."""
    early = _jump_guard(guard) or _domain_guard(state.time_domain, local_domain)
    if early is not None:
        return early
    if local_domain is TimeDomain.LOGICAL:
        return classify_logical(state.sent_at_ns, now_ns, horizon_ns)
    if estimator is None:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "no_clock_estimate")
    return classify(state.robot_id, state.sent_at_ns, now_ns, estimator, horizon_ns)


def classify_intent(
    intent: PeerIntent,
    now_ns: int,
    local_domain: TimeDomain,
    estimator: SharedClockEstimator | None = None,
    guard: ClockJumpGuard | None = None,
) -> FreshnessVerdict:
    """Classify an advertised intent against *its own* declared validity.

    The sender states how long its prediction is a fair claim; a perfectly
    delivered message is still STALE once that horizon has passed.
    """
    early = _jump_guard(guard) or _domain_guard(intent.time_domain, local_domain)
    if early is not None:
        return early
    horizon = intent.validity_horizon_ns
    if horizon <= 0:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "intent_declares_no_validity")
    if local_domain is TimeDomain.LOGICAL:
        return classify_logical(intent.sent_at_ns, now_ns, horizon)
    if estimator is None:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "no_clock_estimate")
    return classify(intent.robot_id, intent.sent_at_ns, now_ns, estimator, horizon)


def classify_heartbeat(
    beat: Heartbeat,
    now_ns: int,
    local_domain: TimeDomain,
    horizon_ns: int,
    estimator: SharedClockEstimator | None = None,
    guard: ClockJumpGuard | None = None,
) -> FreshnessVerdict:
    """Classify liveness. The verdict is never usable *permission*."""
    early = _jump_guard(guard) or _domain_guard(beat.time_domain, local_domain)
    if early is not None:
        return early
    if local_domain is TimeDomain.LOGICAL:
        verdict = classify_logical(beat.sent_at_ns, now_ns, horizon_ns)
    elif estimator is None:
        return FreshnessVerdict(FreshnessClass.UNKNOWN, None, 0, "no_clock_estimate")
    else:
        verdict = classify(beat.robot_id, beat.sent_at_ns, now_ns, estimator, horizon_ns)
    # A heartbeat proves the peer process is alive. It proves nothing about where
    # it is or what it wants, so it is recorded separately and never usable.
    return FreshnessVerdict(
        verdict.freshness,
        verdict.age_ns,
        verdict.uncertainty_ns,
        "liveness_only_not_a_usable_claim",
    )


def freshness_of(
    message: PeerState | PeerIntent | Heartbeat,
    now_ns: int,
    local_domain: TimeDomain,
    horizon_ns: int,
    estimator: SharedClockEstimator | None = None,
    guard: ClockJumpGuard | None = None,
) -> FreshnessVerdict:
    """Dispatch freshness classification by body type."""
    if isinstance(message, PeerState):
        return classify_peer_state(message, now_ns, local_domain, horizon_ns, estimator, guard)
    if isinstance(message, PeerIntent):
        return classify_intent(message, now_ns, local_domain, estimator, guard)
    if isinstance(message, Heartbeat):
        return classify_heartbeat(message, now_ns, local_domain, horizon_ns, estimator, guard)
    raise TypeError(f"unsupported freshness subject {type(message).__name__}")


@dataclass(slots=True)
class PeerFreshness:
    """Last verdict for one peer, with the claim it was derived from."""

    peer_id: str
    session_id: str
    seq: int
    sent_at_ns: int
    time_domain: TimeDomain
    freshness: FreshnessClass
    age_ns: float | None
    uncertainty_ns: int
    reason: str
    classified_at_ns: int
    from_heartbeat: bool = False

    @property
    def usable(self) -> bool:
        return self.freshness is FreshnessClass.FRESH and not self.from_heartbeat


@dataclass(slots=True)
class FreshnessTable:
    """Per-peer freshness with an explicit permission consequence.

    Withdrawal is *permission to assume*: it stops this robot from relying on a
    peer claim. It never touches a zone record, because a peer whose telemetry
    went quiet may still be physically inside the aisle.
    """

    local_domain: TimeDomain
    horizon_ns: int
    estimator: SharedClockEstimator | None = None
    guard: ClockJumpGuard = field(default_factory=ClockJumpGuard)
    _peers: dict[str, PeerFreshness] = field(default_factory=dict, repr=False)

    def record(
        self,
        peer_id: str,
        session_id: str,
        seq: int,
        sent_at_ns: int,
        time_domain: TimeDomain,
        verdict: FreshnessVerdict,
        now_ns: int,
        *,
        from_heartbeat: bool = False,
    ) -> PeerFreshness:
        """Store a verdict, rejecting claims from a superseded boot."""
        existing = self._peers.get(peer_id)
        if (
            existing is not None
            and existing.session_id != session_id
            and session_id < existing.session_id
        ):
            return existing
        entry = PeerFreshness(
            peer_id=peer_id,
            session_id=session_id,
            seq=seq,
            sent_at_ns=sent_at_ns,
            time_domain=time_domain,
            freshness=verdict.freshness,
            age_ns=verdict.age_ns,
            uncertainty_ns=verdict.uncertainty_ns,
            reason=verdict.reason,
            classified_at_ns=now_ns,
            from_heartbeat=from_heartbeat,
        )
        self._peers[peer_id] = entry
        return entry

    def get(self, peer_id: str) -> PeerFreshness | None:
        return self._peers.get(peer_id)

    def suspended_peers(self) -> tuple[str, ...]:
        """Peers we have heard from but may no longer assume anything about."""
        return tuple(sorted(p for p, e in self._peers.items() if not e.usable))

    def observe_now(self, now_ns: int) -> None:
        """Re-classify every remembered claim against the new now."""
        self.guard.observe(now_ns)
        for peer_id, entry in list(self._peers.items()):
            if self.local_domain is TimeDomain.LOGICAL and entry.time_domain is TimeDomain.LOGICAL:
                verdict = classify_logical(entry.sent_at_ns, now_ns, self.horizon_ns)
            elif self.estimator is not None and self.guard.stable:
                verdict = classify(
                    peer_id, entry.sent_at_ns, now_ns, self.estimator, self.horizon_ns
                )
            else:
                verdict = FreshnessVerdict(
                    FreshnessClass.UNKNOWN,
                    None,
                    entry.uncertainty_ns,
                    "local_clock_jump_suspected" if not self.guard.stable else "no_clock_estimate",
                )
            entry.freshness = verdict.freshness
            entry.age_ns = verdict.age_ns
            entry.uncertainty_ns = verdict.uncertainty_ns
            entry.reason = verdict.reason
            entry.classified_at_ns = now_ns


def iter_suspended(table: FreshnessTable, required: Iterable[str]) -> tuple[str, ...]:
    """Required voters whose claims this robot may no longer assume."""
    suspended = set(table.suspended_peers())
    return tuple(sorted(suspended.intersection(required)))

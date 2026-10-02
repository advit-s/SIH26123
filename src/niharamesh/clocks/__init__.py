"""Clock and random-stream abstraction.

Five distinct notions of time exist in this system and are never mixed:

``LogicalClock``
    Injected simulation time. Pauses freeze deadlines; acceleration advances time
    without changing scenario semantics. Used by the deterministic mode and by
    the single-process harness.

``MonotonicClock``
    ``time.monotonic_ns()``. Used by real agent processes. Values are only
    comparable *within one process* unless a measured offset is carried with an
    explicit uncertainty.

``SharedClockEstimator``
    A measured offset between two processes' monotonic clocks, with an explicit
    uncertainty bound. Freshness maths uses the *conservative* bound: it assumes
    the sender's clock is behind by ``uncertainty`` when in doubt, so a
    negative raw age is classified UNKNOWN rather than FRESH.

``DisplayClock``
    UTC for human display. Never used for expiry.

``SeededStreams``
    Named, independently seeded random streams. Changing one component's noise
    must not perturb another component's draws.
"""

from __future__ import annotations

import random
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Final, Protocol

from niharamesh.domain.units import TimeDomain

__all__ = [
    "Clock",
    "ClockOffset",
    "DisplayClock",
    "LogicalClock",
    "MonotonicClock",
    "PauseState",
    "SeededStreams",
    "SharedClockEstimator",
]

NS_PER_S: Final[int] = 1_000_000_000


class Clock(ABC):
    """Minimal clock surface. Everything else is built on this."""

    @property
    @abstractmethod
    def domain(self) -> TimeDomain: ...

    @abstractmethod
    def now_ns(self) -> int:
        """Current time in nanoseconds, in :attr:`domain`."""

    def now_s(self) -> float:
        return self.now_ns() / NS_PER_S

    def seconds_until(self, deadline_ns: int) -> float:
        """Signed seconds until *deadline_ns*. Negative means already past."""
        return (deadline_ns - self.now_ns()) / NS_PER_S


class MonotonicClock(Clock):
    """Real per-process monotonic time. The only clock used for deadlines in
    real-process mode."""

    __slots__ = ("_origin_ns",)

    def __init__(self) -> None:
        self._origin_ns = time.monotonic_ns()

    @property
    def domain(self) -> TimeDomain:
        return TimeDomain.MONOTONIC

    def now_ns(self) -> int:
        return time.monotonic_ns() - self._origin_ns

    @staticmethod
    def raw_ns() -> int:
        """Absolute ``time.monotonic_ns()``, used for offset measurement."""
        return time.monotonic_ns()


class DisplayClock(Clock):
    """UTC wall time for humans. Never for expiry."""

    __slots__ = ()

    @property
    def domain(self) -> TimeDomain:
        return TimeDomain.DISPLAY_UTC

    def now_ns(self) -> int:
        return time.time_ns()

    def iso(self) -> str:
        from datetime import UTC, datetime

        return datetime.fromtimestamp(self.now_ns() / NS_PER_S, tz=UTC).isoformat()


@dataclass(frozen=True, slots=True)
class PauseState:
    paused: bool
    paused_at_ns: int
    accumulated_pause_ns: int

    @property
    def resumed_at_ns(self) -> int:
        return self.paused_at_ns - self.accumulated_pause_ns


class LogicalClock(Clock):
    """Injected simulation time.

    Semantics that matter:

    * ``advance`` moves time forward in whole steps; deadlines are evaluated
      against this value so pausing genuinely freezes them.
    * ``speed_multiplier`` affects how much simulated time a given amount of real
      work advances, but never changes scenario semantics: a fault scheduled for
      simulation second 12.0 fires at simulation second 12.0 regardless of
      speed.
    * Time never runs backwards. A backwards jump is a bug, not a feature.
    """

    __slots__ = ("_accumulated_pause", "_lock", "_now_ns", "_paused_at", "_speed")

    def __init__(self, start_ns: int = 0, speed_multiplier: float = 1.0) -> None:
        if start_ns < 0:
            raise ValueError("logical clock cannot start before zero")
        if speed_multiplier <= 0.0:
            raise ValueError("speed multiplier must be positive")
        self._now_ns = int(start_ns)
        self._paused_at: int | None = None
        self._accumulated_pause = 0
        self._speed = float(speed_multiplier)
        self._lock = threading.Lock()

    @property
    def domain(self) -> TimeDomain:
        return TimeDomain.LOGICAL

    def now_ns(self) -> int:
        return self._now_ns

    @property
    def speed_multiplier(self) -> float:
        return self._speed

    def set_speed(self, multiplier: float) -> None:
        if multiplier <= 0.0:
            raise ValueError("speed multiplier must be positive")
        self._speed = float(multiplier)

    def pause(self) -> None:
        if self._paused_at is None:
            self._paused_at = self._now_ns

    def resume(self) -> None:
        if self._paused_at is not None:
            self._accumulated_pause += self._now_ns - self._paused_at
            self._paused_at = None

    @property
    def paused(self) -> bool:
        return self._paused_at is not None

    def pause_state(self) -> PauseState:
        return PauseState(
            paused=self.paused,
            paused_at_ns=self._paused_at if self._paused_at is not None else self._now_ns,
            accumulated_pause_ns=self._accumulated_pause,
        )

    def advance(self, delta_ns: int) -> int:
        """Advance logical time. No-op while paused. Returns the new time."""
        if delta_ns < 0:
            raise ValueError("the logical clock cannot move backwards")
        if self._paused_at is not None:
            return self._now_ns
        with self._lock:
            self._now_ns += int(delta_ns)
        return self._now_ns

    def advance_seconds(self, dt_s: float) -> int:
        return self.advance(int(dt_s * NS_PER_S))

    def real_time_for(self, sim_ns: int) -> float:
        """Real seconds needed to advance *sim_ns* at the current speed.

        Only used by the acceleration driver. It never changes scenario timing.
        """
        return (sim_ns / NS_PER_S) / self._speed


@dataclass(frozen=True, slots=True)
class ClockOffset:
    """A measured offset between two monotonic clocks.

    ``offset_ns`` is *local_now - remote_now*. ``uncertainty_ns`` is a bound on
    how wrong that estimate can be (derived from RTT samples). Freshness uses
    ``conservative_uncertainty_ns``: an age claim is only trusted when the
    uncertainty is small relative to the horizon.
    """

    peer_id: str
    offset_ns: int
    rtt_ns: int
    samples: int
    measured_at_ns: int

    @property
    def conservative_uncertainty_ns(self) -> int:
        """Worst-case error bound: half the round trip, plus measurement slack."""
        return (self.rtt_ns // 2) + 1_000_000  # +1 ms scheduling slack

    @property
    def reliable(self) -> bool:
        return self.samples >= 3


class SharedClockEstimator:
    """Best-offset estimator for one peer, following the classic NTP-style
    minimum-RTT selection.

    Freshness never uses a bare ``now - sent``. It computes
    ``age >= now_local - (sent_remote + offset - uncertainty)`` and additionally
    requires ``uncertainty < horizon / 2``; otherwise the message is UNKNOWN and
    is treated exactly like STALE for permissions.
    """

    __slots__ = ("_samples",)

    def __init__(self) -> None:
        self._samples: list[tuple[int, int, int]] = []  # (rtt, offset, measured_at)

    def observe(self, peer_id: str, t0_local: int, t1_remote: int, t2_local: int) -> None:
        rtt = t2_local - t0_local
        offset = t1_remote - (t0_local + rtt // 2)
        self._samples.append((rtt, offset, t2_local))
        # Bounded memory: only the recent window matters.
        if len(self._samples) > 16:
            del self._samples[:-16]

    def estimate(self, peer_id: str) -> ClockOffset | None:
        if not self._samples:
            return None
        rtt, offset, measured_at = min(self._samples, key=lambda s: s[0])
        return ClockOffset(
            peer_id=peer_id,
            offset_ns=offset,
            rtt_ns=rtt,
            samples=len(self._samples),
            measured_at_ns=measured_at,
        )

    def lower_bound_age_ns(
        self,
        peer_id: str,
        sent_remote_ns: int,
        now_local_ns: int,
    ) -> float | None:
        """Conservative lower bound on the age of a message, in nanoseconds.

        Returns ``None`` when no usable estimate exists, which callers must map
        to ``FreshnessClass.UNKNOWN``.
        """
        est = self.estimate(peer_id)
        if est is None:
            return None
        received_remote_equivalent = sent_remote_ns + est.offset_ns
        return float(now_local_ns - received_remote_equivalent) + float(
            est.conservative_uncertainty_ns
        )


class SeededStream(Protocol):
    def random(self) -> float: ...
    def uniform(self, a: float, b: float) -> float: ...
    def gauss(self, mu: float, sigma: float) -> float: ...
    def randint(self, a: int, b: int) -> int: ...


@dataclass(slots=True)
class SeededStreams:
    """Named independent random streams.

    Using one global stream would make a change in, say, sensor noise perturb
    the planner's draws and silently invalidate a benchmark. Each component
    gets its own named stream derived from ``base_seed``.
    """

    base_seed: int
    _streams: dict[str, random.Random] = field(default_factory=dict, init=False)

    def stream(self, name: str) -> random.Random:
        existing = self._streams.get(name)
        if existing is None:
            # Derive deterministically from the base seed and the name so a
            # stream's identity does not depend on creation order.
            digest = 0
            for ch in name.encode("utf-8"):
                digest = (digest * 131 + ch) & 0xFFFFFFFF
            existing = random.Random((self.base_seed * 1_000_003 + digest) & 0xFFFFFFFF)
            self._streams[name] = existing
        return existing

    def uniform(self, name: str, a: float, b: float) -> float:
        return self.stream(name).uniform(a, b)

    def gauss(self, name: str, mu: float, sigma: float) -> float:
        return self.stream(name).gauss(mu, sigma)

    def chance(self, name: str, probability: float) -> bool:
        return self.stream(name).random() < probability

    def randint(self, name: str, a: int, b: int) -> int:
        return self.stream(name).randint(a, b)

    def shuffle(self, name: str, items: list[object]) -> None:
        self.stream(name).shuffle(items)

    def reset(self) -> None:
        self._streams.clear()

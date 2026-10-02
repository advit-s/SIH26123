"""Deterministic fixed-step scheduler with a canonical event order.

Why an explicit order at all
----------------------------
Two events at the same simulated instant can only be processed in *some* order,
and if that order is left to insertion order, dict iteration or thread arrival,
the same scenario produces different runs on different machines. Every claim this
project makes about a coordination protocol has to be reproducible, so the order
is data, not an accident: ``(sim_time_ns, priority, source_id, sequence)``.

Priority encodes the invariant hierarchy from ``AGENTS.md``:

``SAFETY`` -> ``AUTHORITY`` -> ``EVALUATION`` -> ``TASK`` -> ``PLANNING`` -> ``TELEMETRY``

A zone grant must not wait behind a telemetry sample, and evaluation of what
happened must not wait behind the plan that caused it. ``source_id`` then breaks
ties between peers in a stable lexical order -- deliberately not the canonical
peer order, because grant sequencing is the coordination protocol's job and this
scheduler must not silently perform it. ``sequence`` is a per-source monotonic
counter for events the same source emits at the same instant.

Purity
------
Nothing here reads a wall clock, a random source or any global. The same
constructor arguments and the same :meth:`schedule` calls produce the same
executed-event sequence, and :meth:`executed_digest` is the cheap evidence of it.
"""

from __future__ import annotations

import hashlib
import heapq
import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

__all__ = ["DeterministicScheduler", "Priority", "ScheduledEvent"]

NS_PER_S: Final[int] = 1_000_000_000


class Priority(IntEnum):
    """Lower executes first. The order is the invariant hierarchy, top to bottom."""

    SAFETY = 0
    AUTHORITY = 1
    EVALUATION = 2
    TASK = 3
    PLANNING = 4
    TELEMETRY = 5


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    """One event placed on the logical timeline.

    ``payload`` is opaque to the scheduler: it is whatever the caller needs, and
    it is deliberately excluded from ordering and from the digest so that
    changing a payload never changes execution order.
    """

    sim_time_ns: int
    priority: Priority
    source_id: str
    sequence: int
    payload: object = None

    @property
    def order_key(self) -> tuple[int, int, str, int]:
        return (self.sim_time_ns, int(self.priority), self.source_id, self.sequence)

    def __repr__(self) -> str:
        pname = Priority(self.priority).name.lower()
        return (
            f"ScheduledEvent(t={self.sim_time_ns / NS_PER_S:.3f}s, {pname}, "
            f"{self.source_id!r}, seq={self.sequence})"
        )


class DeterministicScheduler:
    """Fixed-step logical clock plus an ordered event queue.

    Not thread-safe by design: the deterministic harness drives it from one
    thread. Adding a lock would let two threads interleave ``advance`` calls and
    reintroduce exactly the non-determinism this class exists to remove.
    """

    __slots__ = ("_counter", "_log", "_max_steps", "_now_ns", "_queue", "_step_ns", "_steps_done")

    def __init__(self, step_s: float, max_steps: int) -> None:
        if not math.isfinite(step_s) or step_s <= 0.0:
            raise ValueError("step_s must be a positive finite number")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._step_ns = round(step_s * NS_PER_S)
        if self._step_ns < 1:
            raise ValueError("step_s is below one nanosecond; not representable")
        self._max_steps = max_steps
        self._now_ns = 0
        self._steps_done = 0
        self._counter = 0
        self._queue: list[tuple[tuple[int, int, str, int], ScheduledEvent]] = []
        self._log: list[ScheduledEvent] = []

    # -- clock -------------------------------------------------------------- #

    @property
    def step_s(self) -> float:
        return self._step_ns / NS_PER_S

    @property
    def sim_time_ns(self) -> int:
        return self._now_ns

    @property
    def steps_done(self) -> int:
        return self._steps_done

    @property
    def max_steps(self) -> int:
        return self._max_steps

    @property
    def exhausted(self) -> bool:
        """True once ``max_steps`` steps have run. A run that ends here is a fact."""
        return self._steps_done >= self._max_steps

    @property
    def executed(self) -> tuple[ScheduledEvent, ...]:
        """Every event executed so far, in execution order."""
        return tuple(self._log)

    # -- queue -------------------------------------------------------------- #

    def schedule(
        self,
        priority: Priority,
        source_id: str,
        *,
        offset_s: float = 0.0,
        payload: object = None,
    ) -> ScheduledEvent:
        """Place an event ``offset_s`` from the current logical time.

        The returned event's ``sequence`` is a scheduler-assigned monotonic
        counter, so two events scheduled in the same call order never collide even
        when the caller does not track its own.
        """
        if not math.isfinite(offset_s):
            raise ValueError("offset_s must be finite")
        when = self._now_ns + round(offset_s * NS_PER_S)
        if when < self._now_ns:
            raise ValueError("an event cannot be scheduled in the logical past")
        event = ScheduledEvent(
            sim_time_ns=when,
            priority=priority,
            source_id=source_id,
            sequence=self._counter,
            payload=payload,
        )
        self._counter += 1
        heapq.heappush(self._queue, (event.order_key, event))
        return event

    def schedule_at(
        self, sim_time_ns: int, priority: Priority, source_id: str, *, payload: object = None
    ) -> ScheduledEvent:
        """Place an event at an absolute logical nanosecond stamp."""
        if sim_time_ns < self._now_ns:
            raise ValueError("an event cannot be scheduled in the logical past")
        return self.schedule(
            priority, source_id, offset_s=(sim_time_ns - self._now_ns) / NS_PER_S, payload=payload
        )

    def schedule_all(self, events: Iterable[ScheduledEvent]) -> None:
        """Register externally constructed events, preserving their declared keys."""
        for event in sorted(events, key=lambda e: e.order_key):
            if event.sim_time_ns < self._now_ns:
                raise ValueError("an event cannot be scheduled in the logical past")
            self._counter = max(self._counter, event.sequence + 1)
            heapq.heappush(self._queue, (event.order_key, event))

    def pending(self) -> tuple[ScheduledEvent, ...]:
        """Queued-but-unexecuted events, already in canonical order."""
        return tuple(event for _, event in sorted(self._queue, key=lambda item: item[0]))

    # -- execution ---------------------------------------------------------- #

    def advance(self, n_steps: int = 1) -> tuple[ScheduledEvent, ...]:
        """Run up to *n_steps* fixed steps and return the events executed, in order.

        Events land in the step whose half-open interval contains them:
        ``(t, t + step]``. That keeps a boundary event from executing twice at two
        different steps, which a closed interval would allow.
        """
        if n_steps < 0:
            raise ValueError("n_steps must be non-negative")
        executed: list[ScheduledEvent] = []
        budget = min(n_steps, self._max_steps - self._steps_done)
        for _ in range(max(0, budget)):
            step_end = self._now_ns + self._step_ns
            # Drain including events added during this step: a handler may schedule
            # a follow-up at the same instant and it must still run in this step.
            while self._queue and self._queue[0][0][0] <= step_end:
                _, event = heapq.heappop(self._queue)
                executed.append(event)
                self._log.append(event)
            self._now_ns = step_end
            self._steps_done += 1
        return tuple(executed)

    def advance_to(self, sim_time_ns: int) -> int:
        """Advance up to ``sim_time_ns``. Returns the number of steps executed.

        The clock stops at the last step boundary *at or before* the target; it
        never overshoots. A scheduler that advanced "a bit extra" to reach a
        target would silently change the scenario, so an unaligned target simply
        reports fewer steps executed and leaves the remainder to the caller.
        """
        if sim_time_ns < self._now_ns:
            raise ValueError("the logical clock cannot move backwards")
        wanted = (sim_time_ns - self._now_ns) // self._step_ns
        before = self._steps_done
        self.advance(int(wanted))
        return self._steps_done - before

    def executed_digest(self) -> str:
        """SHA-256 over the executed event keys. Identical runs produce equal digests."""
        hasher = hashlib.sha256()
        for event in self._log:
            hasher.update(f"{event.order_key!r}\x1f".encode())
        return hasher.hexdigest()[:32]

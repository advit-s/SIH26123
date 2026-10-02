"""Round-trip clock-offset estimation between peers.

Two processes' ``time.monotonic_ns()`` values are *not* comparable. This
module measures the offset with an NTP-style four-timestamp exchange and feeds
:class:`~niharamesh.clocks.SharedClockEstimator`, which keeps the best
(minimum-RTT) sample and carries an explicit uncertainty bound.

The exchange
------------
1. The requester stamps ``t0`` into the body of a ``peer_state`` message it is
   publishing anyway, and marks it with ``correlation_id = clockprobe:<id>``.
2. The responder records ``t1`` - its own monotonic clock at receipt - and
   answers with a ``heartbeat`` whose ``sent_at_ns`` *is* ``t1`` and whose
   ``correlation_id`` echoes ``clockprobe:<id>:reply``.
3. The requester records ``t2`` and calls ``estimator.observe(peer, t0, t1, t2)``.

Why a ``heartbeat`` for the reply: ``heartbeat`` is documented in
``domain/coordination.py`` as "liveness only, explicitly not usable intent and
not clearance". Using it to carry a clock stamp invents no pose, no zone state
and no task claim, so the responder never has to fabricate semantic content on
behalf of an agent.

Why the request needs a ``state_provider``: a probe is a real state
publication, so it must carry the agent's *own* pose. If the agent has not
installed a provider the probe is skipped and counted. The transport never
invents a pose to keep a clock warm.

Bounds
------
``SharedClockEstimator`` retains at most 16 samples per peer, and this module
retains at most 64 outstanding probe ids. :meth:`ClockSync.stop` cancels the
ping task and waits for it, so no task outlives the transport.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Final

from niharamesh.clocks import Clock, ClockOffset, MonotonicClock, SharedClockEstimator
from niharamesh.domain.coordination import Heartbeat, PeerEnvelope, PeerMessage, build_message

__all__ = [
    "CLOCK_PROBE_PREFIX",
    "ClockSync",
    "is_clock_probe",
    "probe_correlation",
    "probe_reply_correlation",
]

CLOCK_PROBE_PREFIX: Final[str] = "clockprobe:"

#: Outstanding probe ids retained per sync, i.e. bounded memory.
_MAX_PENDING: Final[int] = 64


def probe_correlation(probe_id: int) -> str:
    """Correlation id that marks a state publication as a clock probe."""
    return f"{CLOCK_PROBE_PREFIX}{probe_id}"


def probe_reply_correlation(probe_id: int) -> str:
    """Correlation id the responder echoes back."""
    return f"{CLOCK_PROBE_PREFIX}{probe_id}:reply"


def is_clock_probe(correlation_id: str) -> bool:
    return correlation_id.startswith(CLOCK_PROBE_PREFIX)


def _probe_id(correlation_id: str) -> int:
    tail = correlation_id[len(CLOCK_PROBE_PREFIX) :].removesuffix(":reply")
    try:
        return int(tail)
    except ValueError:
        return -1


SendFn = Callable[[str, PeerMessage], Awaitable[None]]
StateProvider = Callable[[], PeerMessage]


class ClockSync:
    """Keeps one :class:`SharedClockEstimator` fed with real round trips."""

    def __init__(
        self,
        *,
        robot_id: str,
        session_id: str,
        run_id: str,
        epoch: str,
        clock: Clock | None = None,
        estimator: SharedClockEstimator | None = None,
        interval_s: float = 0.25,
    ) -> None:
        if interval_s <= 0.0:
            raise ValueError("interval_s must be positive")
        self._robot_id = robot_id
        self._session_id = session_id
        self._run_id = run_id
        self._epoch = epoch
        self._clock: Clock = clock or MonotonicClock()
        self._estimator: SharedClockEstimator = estimator or SharedClockEstimator()
        self._interval_s = float(interval_s)
        self._pending: dict[int, int] = {}
        self._pending_order: deque[int] = deque()
        self._observed: set[str] = set()
        self._probes_sent = 0
        self._probes_skipped_no_state = 0
        self._replies_seen = 0
        self._probe_id = 0
        self._reply_seq = 0
        self._send_seq = 0
        self._stopping = False
        self._task: asyncio.Task[None] | None = None
        self._loop_error = ""
        self._state_provider: StateProvider | None = None

    # ------------------------------------------------------------- properties

    @property
    def estimator(self) -> SharedClockEstimator:
        return self._estimator

    @property
    def state_provider(self) -> StateProvider | None:
        """Agent-supplied builder for its own state publication."""
        return self._state_provider

    @state_provider.setter
    def state_provider(self, provider: StateProvider | None) -> None:
        self._state_provider = provider

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    # ----------------------------------------------------------------- probes

    def mark_probe(self, message: PeerMessage) -> PeerMessage:
        """Stamp a real state publication as this round's clock probe."""
        self._probe_id += 1
        envelope = message.envelope.model_copy(
            update={"correlation_id": probe_correlation(self._probe_id)}
        )
        self._pending[self._probe_id] = self._clock.now_ns()
        self._pending_order.append(self._probe_id)
        while len(self._pending_order) > _MAX_PENDING:
            self._pending.pop(self._pending_order.popleft(), None)
        self._probes_sent += 1
        return message.model_copy(update={"envelope": envelope})

    def reply_to(self, message: PeerMessage) -> PeerMessage | None:
        """Build the ``heartbeat`` clock reply, or ``None`` if not a probe.

        ``t1`` is the responder's own monotonic clock at receipt, which is the
        only thing the reply asserts.
        """
        correlation = message.envelope.correlation_id
        if not is_clock_probe(correlation) or correlation.endswith(":reply"):
            return None
        self._reply_seq += 1
        now_ns = self._clock.now_ns()
        self._send_seq += 1
        envelope = PeerEnvelope(
            kind="heartbeat",
            sender=self._robot_id,
            sender_session=self._session_id,
            run_id=self._run_id,
            epoch=self._epoch,
            seq=self._send_seq,
            sent_at_ns=now_ns,
            time_domain=self._clock.domain,
            correlation_id=probe_reply_correlation(_probe_id(correlation)),
        )
        body = Heartbeat(
            run_id=self._run_id,
            epoch=self._epoch,
            robot_id=self._robot_id,
            session_id=self._session_id,
            seq=self._send_seq,
            sent_at_ns=now_ns,
            time_domain=self._clock.domain,
        )
        return build_message(envelope, body)

    def observe_reply(self, message: PeerMessage, *, t2_local: int | None = None) -> bool:
        """Fold one clock reply into the estimator. Returns True if it was one."""
        correlation = message.envelope.correlation_id
        if not correlation.endswith(":reply") or not is_clock_probe(correlation):
            return False
        stamp = getattr(message.body, "sent_at_ns", None)
        if not isinstance(stamp, int):
            return False
        probe_id = _probe_id(correlation)
        t0 = self._pending.pop(probe_id, None)
        if t0 is None:
            return False
        self._replies_seen += 1
        t2 = self._clock.now_ns() if t2_local is None else t2_local
        self.sample(message.envelope.sender, t0, stamp, t2)
        self._observed.add(message.envelope.sender)
        return True

    def sample(self, peer_id: str, t0_local: int, t1_remote: int, t2_local: int) -> None:
        """Record one four-timestamp sample. Bounded to 16 by the estimator."""
        if t2_local < t0_local:
            raise ValueError("clock sample cannot have t2 before t0 in the local domain")
        self._estimator.observe(peer_id, t0_local, t1_remote, t2_local)

    def offset(self, peer_id: str) -> ClockOffset | None:
        """Best offset estimate for *peer_id*, or ``None`` if unmeasured."""
        return self._estimator.estimate(peer_id)

    def remote_time_ns(self, peer_id: str, now_local_ns: int) -> int | None:
        """Conservative lower bound on a peer's clock at *now_local_ns*."""
        estimate = self.offset(peer_id)
        if estimate is None:
            return None
        return now_local_ns + estimate.offset_ns - estimate.conservative_uncertainty_ns

    # ------------------------------------------------------------------- loop

    async def ping_loop(self, send: SendFn, peer_ids: tuple[str, ...]) -> None:
        """Publish a clock probe to every peer until stopped.

        Cancelling the coroutine is supported and leaves no task behind.
        """
        self._stopping = False
        while not self._stop_requested():
            for peer_id in peer_ids:
                if self._stop_requested():
                    break
                message = self._next_probe(peer_id)
                if message is None:
                    continue
                try:
                    await send(peer_id, message)
                except (OSError, ConnectionError):
                    # A probe that cannot go out is a link problem, not a reason
                    # to invent an offset. The estimator simply has fewer samples.
                    break
            await asyncio.sleep(self._interval_s)

    def _stop_requested(self) -> bool:
        return self._stopping

    def start(self, send: SendFn, peer_ids: tuple[str, ...]) -> None:
        """Spawn :meth:`ping_loop` as a task owned (and cancelled) by this object."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self.ping_loop(send, peer_ids), name="clocksync")

    async def stop(self) -> None:
        """Stop the ping loop and wait for it. Idempotent.

        A loop that died for any other reason is recorded in ``health()`` under
        ``loop_error`` rather than being swallowed here.
        """
        self._stopping = True
        task = self._task
        self._task = None
        self._stopping = False
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        failure = None if task.cancelled() else task.exception()
        if failure is not None:
            self._loop_error = repr(failure)

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, object]:
        """Liveness report. Silence here is ``unavailable``, not "no traffic"."""
        pending = len(self._pending)
        offsets: dict[str, object] = {}
        for peer in sorted(self._observed):
            estimate = self.offset(peer)
            if estimate is None:  # pragma: no cover - observed implies estimated
                continue
            offsets[peer] = {
                "offset_ns": estimate.offset_ns,
                "rtt_ns": estimate.rtt_ns,
                "samples": estimate.samples,
                "uncertainty_ns": estimate.conservative_uncertainty_ns,
                "reliable": estimate.reliable,
            }
        return {
            "running": self.running,
            "interval_s": self._interval_s,
            "loop_error": self._loop_error,
            "probes_sent": self._probes_sent,
            "replies_seen": self._replies_seen,
            "probes_skipped_no_state": self._probes_skipped_no_state,
            "outstanding_probes": pending,
            "state_provider_installed": self._state_provider is not None,
            "availability": (
                "available" if self._replies_seen and pending < _MAX_PENDING else "unavailable"
            ),
            "offsets": offsets,
        }

    def _next_probe(self, peer_id: str) -> PeerMessage | None:
        """Return this round's probe, or ``None`` when the agent has no state."""
        if self._state_provider is None:
            self._probes_skipped_no_state += 1
            return None
        message = self._state_provider()
        if message.envelope.sender != self._robot_id:
            raise ValueError(
                "state_provider must build a message from this robot's own identity, "
                f"got sender={message.envelope.sender!r}"
            )
        return self.mark_probe(message)

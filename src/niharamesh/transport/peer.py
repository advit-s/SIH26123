"""Direct robot-to-robot framed messaging over asyncio TCP sockets.

Each robot process binds one loopback port and dials its declared peers' ports.
There is no broker, no coordinator service and no dashboard in this path: a
message from A to B travels A -> B's socket. The dependency graph is
``agent -> transport -> sockets``; this module imports neither the API nor the
simulator, which is what makes that claim checkable by reading imports.

Inbound pipeline, in this order, each step counted
--------------------------------------------------
1. frame       - length validated against ``max_bytes`` before the body is read
2. decode      - strict, names the offending field, all-or-nothing
3. admission   - ``domain.identity.admission_outcome``, the *one* shared rule, so
                 the launcher and the transport cannot disagree
4. replay window - bounded per-sender set of seen ``seq`` values
5. fault layer - delay / drop / duplicate / reorder / partition
6. inbox       - bounded; replaceable kinds are shed first

Bounds
------
``inbox_capacity``, ``replay_window`` and the per-peer outbox are finite by
construction and their pressures are visible in :meth:`PeerTransportServer.health`.
An unbounded queue is a defect, not a tuning choice.

Connected but silent
--------------------
``docs/RESEARCH.md`` records that an incompatible ROS 2 QoS request/offer pair
yields *no messages and no error* - "no communication", silently. Liveness here
is therefore not "the socket is open": every peer is expected to publish
periodic clock probes, and a peer whose socket is open while nothing arrives for
longer than ``silence_threshold_ns`` is reported ``connected_silent`` with
``availability == "unavailable"``. It is never rendered as "no traffic".

Absent evidence is ``None``, not ``0``
--------------------------------------
``last_rx_ns``, ``last_tx_ns`` and ``silence_ms`` report ``None`` when the event
they describe has not happened. They do not report ``0``: ``MonotonicClock`` wraps
``time.monotonic``, which resolves to a millisecond on Windows, so the first real
measurement on a fresh link can legitimately *be* ``0`` - and a zero sentinel
turns a received message into a reported silence.

Diagnosis is not health
-----------------------
:meth:`PeerTransportServer.health` answers "what is true now".
:meth:`PeerTransportServer.link_trace` answers "what happened, and why": every
link attach, detach, clean EOF, refused dial, escaped exception and abnormally
finished worker, in a bounded ring. The counters alone cannot tell a link that is
between reconnect attempts from one whose reconnect loop is dead, and a worker
that dies on an unhandled exception used to leave no trace at all.
"""

from __future__ import annotations

import asyncio
import traceback
from collections import deque
from collections.abc import AsyncIterator, Callable, Coroutine, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import StrEnum
from functools import partial
from typing import Any, Final

from niharamesh.clocks import Clock, MonotonicClock, SeededStreams
from niharamesh.domain.coordination import PeerMessage
from niharamesh.domain.identity import (
    Membership,
    PeerEndpoint,
    RobotIdentity,
    RobotSession,
    admission_outcome,
)
from niharamesh.transport import clocksync as cs
from niharamesh.transport.codec import (
    MAX_FRAME_BYTES,
    MAX_MESSAGE_BYTES,
    ProtocolDecodeError,
    decode_message,
    encode_message,
)
from niharamesh.transport.faults import DecisionKind, FaultLayer
from niharamesh.transport.framing import (
    ConnectionClosedError,
    FrameError,
    FrameStats,
    FrameTooLargeError,
    TruncatedFrameError,
    read_frame,
)

__all__ = [
    "DEFAULT_INBOX_CAPACITY",
    "DEFAULT_OUTBOX_CAPACITY",
    "DEFAULT_REPLAY_WINDOW",
    "DEFAULT_SILENCE_THRESHOLD_NS",
    "REPLACEABLE_KINDS",
    "BoundedInbox",
    "LinkEvent",
    "LinkTrace",
    "PeerClient",
    "PeerDeclaration",
    "PeerStatus",
    "PeerTransportServer",
    "ReplayWindow",
]

DEFAULT_INBOX_CAPACITY: Final[int] = 512
DEFAULT_REPLAY_WINDOW: Final[int] = 256
DEFAULT_SILENCE_THRESHOLD_NS: Final[int] = 2_000_000_000
DEFAULT_OUTBOX_CAPACITY: Final[int] = 64

_BACKOFF_MIN_NS: Final[int] = 50_000_000
_BACKOFF_CAP_NS: Final[int] = 1_000_000_000
_DRAIN_INTERVAL_S: Final[float] = 0.005

#: Kinds the inbox is allowed to shed when it is full. ``zone_grant``,
#: ``zone_cancel`` and ``zone_release`` are absent by construction.
REPLACEABLE_KINDS: Final[frozenset[str]] = frozenset(
    {"peer_state", "peer_intent", "heartbeat", "obstruction"}
)

_LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "::1", "localhost"})


def _latest(*stamps: int | None) -> int | None:
    """The most recent of the timestamps that exist, or ``None`` if none do.

    Timestamps here come from :class:`~niharamesh.clocks.MonotonicClock`, whose
    resolution on Windows is one millisecond, so ``0`` is a legal measurement and
    must not double as the "absent" marker.
    """
    present = [stamp for stamp in stamps if stamp is not None]
    return max(present) if present else None


#: Diagnostic ring capacity. Bounded on purpose: an unbounded event log inside
#: the transport would be the very defect this module is written against.
_TRACE_CAPACITY: Final[int] = 128
#: Per-failure traceback text retained, so a health report can name the bug.
_TRACEBACK_CHARS: Final[int] = 2000


@dataclass(frozen=True, slots=True)
class LinkEvent:
    """One observed peer-link lifecycle fact, in the local monotonic domain."""

    seq: int
    at_ns: int
    scope: str
    peer_id: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "seq": self.seq,
            "at_ns": self.at_ns,
            "scope": self.scope,
            "peer_id": self.peer_id,
            "detail": self.detail,
        }


class LinkTrace:
    """Bounded, in-memory record of peer-link lifecycle events.

    This exists because the counters in :meth:`PeerClient.health` answer "what
    is true now" but not "why". A link that reports ``disconnected`` with
    ``connect_attempts == 1`` is indistinguishable from a link whose reconnect
    loop is inside its first backoff sleep, a link retrying against a dead
    listener, and a link whose worker died on an unhandled exception - and those
    three have three different fixes.

    It is a ring: the newest ``capacity`` events survive, older ones are counted
    in :attr:`evicted`. Memory is bounded by construction and nothing here blocks
    or allocates per frame.
    """

    __slots__ = ("_capacity", "_events", "_failures", "_seq")

    def __init__(self, capacity: int = _TRACE_CAPACITY) -> None:
        self._capacity = max(1, capacity)
        self._events: deque[LinkEvent] = deque(maxlen=self._capacity)
        self._failures: list[dict[str, object]] = []
        self._seq = 0

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def recorded(self) -> int:
        return self._seq

    @property
    def evicted(self) -> int:
        """Events dropped from the ring. Non-zero means the log is not complete."""
        return max(0, self._seq - len(self._events))

    @property
    def events(self) -> tuple[LinkEvent, ...]:
        return tuple(self._events)

    @property
    def failures(self) -> tuple[dict[str, object], ...]:
        """Worker tasks that ended abnormally, and what ended them."""
        return tuple(self._failures)

    def record(self, *, at_ns: int, scope: str, peer_id: str = "", detail: str = "") -> None:
        self._seq += 1
        self._events.append(
            LinkEvent(seq=self._seq, at_ns=at_ns, scope=scope, peer_id=peer_id, detail=detail)
        )

    def record_exception(self, *, at_ns: int, scope: str, peer_id: str, exc: BaseException) -> None:
        """Record an escaping exception *with* its traceback, then keep it bounded."""
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self.record(
            at_ns=at_ns,
            scope=scope,
            peer_id=peer_id,
            detail=f"{type(exc).__name__}: {exc}\n{text[-_TRACEBACK_CHARS:]}",
        )

    def record_failure(self, *, at_ns: int, scope: str, peer_id: str, summary: str) -> None:
        """Record a worker task that ended abnormally. Bounded, like the ring."""
        self.record(at_ns=at_ns, scope=scope, peer_id=peer_id, detail=summary)
        if len(self._failures) >= _TRACE_CAPACITY:
            del self._failures[0]
        self._failures.append({"at_ns": at_ns, "scope": scope, "peer_id": peer_id, "summary": summary})


class PeerStatus(StrEnum):
    """One honest state per peer link. No "probably fine"."""

    HEALTHY = "healthy"
    CONNECTED_SILENT = "connected_silent"
    """Socket open, nothing received within the silence bound. QoS-style silence."""
    DISCONNECTED = "disconnected"


@dataclass(frozen=True, slots=True)
class PeerDeclaration:
    """What this robot was told about one peer at launch.

    Immutable run-plan data. The transport never invents any of it, and it never
    contacts a robot that was not declared.
    """

    identity: RobotIdentity
    session: RobotSession
    endpoint: PeerEndpoint


@dataclass(slots=True)
class ReplayWindow:
    """Bounded per-sender sequence window.

    Rejects a repeated ``seq`` and any ``seq`` below the window floor. A *new*
    out-of-order ``seq`` inside the window is admitted: reordering is legal
    network behaviour, and refusing it would invent a delivery guarantee this
    protocol does not claim.
    """

    capacity: int = DEFAULT_REPLAY_WINDOW
    admitted: int = 0
    rejected_repeat: int = 0
    rejected_stale: int = 0
    _seen: set[int] = field(default_factory=set)
    _order: list[int] = field(default_factory=list)
    _floor: int = 0

    def admit(self, seq: int) -> bool:
        if seq in self._seen:
            self.rejected_repeat += 1
            return False
        if self._order and seq < self._floor:
            self.rejected_stale += 1
            return False
        self._seen.add(seq)
        self._order.append(seq)
        if len(self._order) > self.capacity:
            self._seen.discard(self._order.pop(0))
            self._floor = self._order[0]
        self.admitted += 1
        return True

    @property
    def depth(self) -> int:
        return len(self._order)

    def as_dict(self) -> dict[str, int]:
        return {
            "capacity": self.capacity,
            "depth": self.depth,
            "floor": self._floor,
            "admitted": self.admitted,
            "rejected_repeat": self.rejected_repeat,
            "rejected_stale": self.rejected_stale,
        }


class BoundedInbox:
    """A finite inbox with an explicit shed order.

    ``put`` never blocks and never grows past ``capacity``. When full it evicts
    the oldest *replaceable* message; if the queue holds nothing shed-able it
    refuses the new message and says so. An unbounded queue would be a defect.
    """

    __slots__ = ("_capacity", "_closed", "_event", "_items", "refused", "shed_replaceable")

    def __init__(self, capacity: int) -> None:
        self._capacity = capacity
        self._items: deque[PeerMessage] = deque()
        self._event = asyncio.Event()
        self._closed = False
        self.shed_replaceable = 0
        self.refused = 0

    def __len__(self) -> int:
        return len(self._items)

    @property
    def capacity(self) -> int:
        return self._capacity

    def put(self, message: PeerMessage) -> bool:
        """Enqueue *message*. Returns False when it had to be refused."""
        if self._closed:
            self.refused += 1
            return False
        if len(self._items) >= self._capacity and not self._shed():
            self.refused += 1
            return False
        self._items.append(message)
        self._event.set()
        return True

    async def get(self) -> PeerMessage | None:
        """Await the next message. Returns None once closed and drained."""
        while not self._items:
            if self._closed:
                return None
            self._event.clear()
            await self._event.wait()
        message = self._items.popleft()
        if self._items:
            self._event.set()
        return message

    def close(self) -> None:
        self._closed = True
        self._event.set()

    def _shed(self) -> bool:
        for index, queued in enumerate(self._items):
            if queued.envelope.kind in REPLACEABLE_KINDS:
                del self._items[index]
                self.shed_replaceable += 1
                return True
        return False


class PeerClient:
    """One outbound TCP link to one peer, with capped reconnect backoff.

    Owns no authority and makes no scheduling decision: it frames bytes,
    reconnects, and reports silence.
    """

    def __init__(
        self,
        peer_id: str,
        endpoint: PeerEndpoint,
        *,
        clock: Clock,
        frames: FrameStats,
        streams: SeededStreams,
        outbox_capacity: int = DEFAULT_OUTBOX_CAPACITY,
        trace: LinkTrace | None = None,
    ) -> None:
        self._peer_id = peer_id
        host, port = endpoint.address()
        self._host = host
        self._port = port
        self._clock = clock
        self._frames = frames
        self._streams = streams
        self._trace: LinkTrace = trace if trace is not None else LinkTrace()
        self._outbox_capacity = max(1, outbox_capacity)
        self._outbox: deque[bytes] = deque()
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        #: ``None`` means "no such event yet", never ``0``. ``MonotonicClock`` is
        #: backed by ``time.monotonic``, which on Windows has millisecond
        #: resolution, so a first measurement can legitimately be ``0``. A ``0``
        #: sentinel would report that as "nothing was ever received".
        self._connected_at_ns: int | None = None
        self._local_port = 0
        self._last_rx_ns: int | None = None
        self._last_tx_ns: int | None = None
        self.dropped = 0
        self._tx_failures = 0
        self._connect_attempts = 0
        self._reconnects = 0
        self._stopping = False
        self._write_lock = asyncio.Lock()

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def connected(self) -> bool:
        return self._connected

    def note_drop(self) -> None:
        self.dropped += 1

    async def run(self, on_frame: Callable[[bytes], bool]) -> None:
        """Connect, flush, read, reconnect - until cancelled or stopped."""
        backoff_ns = _BACKOFF_MIN_NS
        while not self._stop_requested():
            self._connect_attempts += 1
            attempt = self._connect_attempts
            try:
                reader, writer = await asyncio.open_connection(self._host, self._port)
            except (OSError, ConnectionError) as exc:
                self._trace.record(
                    at_ns=self._clock.now_ns(),
                    scope="dial_refused",
                    peer_id=self._peer_id,
                    detail=f"attempt={attempt} {type(exc).__name__}: {exc}",
                )
                if self._stop_requested():
                    return
                await asyncio.sleep(self._backoff_s(backoff_ns))
                backoff_ns = min(backoff_ns * 2, _BACKOFF_CAP_NS)
                continue

            self._attach(writer)
            self._reconnects += 1
            backoff_ns = _BACKOFF_MIN_NS
            self._trace.record(
                at_ns=self._clock.now_ns(),
                scope="attached",
                peer_id=self._peer_id,
                detail=f"attempt={attempt} from_port={self._local_port}",
            )
            pump = asyncio.ensure_future(self._pump())
            reason = "read_loop_returned"
            try:
                await self._read_loop(reader, on_frame)
            except asyncio.CancelledError:
                self._trace.record(
                    at_ns=self._clock.now_ns(),
                    scope="run_cancelled",
                    peer_id=self._peer_id,
                    detail=f"attempt={attempt}",
                )
                raise
            except (OSError, ConnectionError, FrameError) as exc:
                reason = f"link_died:{type(exc).__name__}"
            except BaseException as exc:
                self._trace.record_exception(
                    at_ns=self._clock.now_ns(),
                    scope="run_escaped",
                    peer_id=self._peer_id,
                    exc=exc,
                )
                raise
            finally:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)
                self._detach()
            self._trace.record(
                at_ns=self._clock.now_ns(),
                scope="detached",
                peer_id=self._peer_id,
                detail=f"attempt={attempt} reason={reason} outbox={len(self._outbox)}",
            )
            if self._stop_requested():
                return
            await asyncio.sleep(self._backoff_s(backoff_ns))
            backoff_ns = min(backoff_ns * 2, _BACKOFF_CAP_NS)

    def _stop_requested(self) -> bool:
        return self._stopping

    async def stop(self) -> None:
        """Close the link and discard buffered frames.

        The outbox is deliberately *not* flushed: replaying a stale promise onto
        a session that has since changed would be a safety bug, not resilience.
        """
        self._stopping = True
        self._trace.record(
            at_ns=self._clock.now_ns(),
            scope="client_stop",
            peer_id=self._peer_id,
            detail=f"outbox={len(self._outbox)}",
        )
        writer = self._writer
        self._detach()
        self.dropped += len(self._outbox)
        self._outbox.clear()
        if writer is not None:
            with suppress(OSError, ConnectionError):
                writer.close()
                await writer.wait_closed()

    def transmit(self, frame: bytes) -> bool:
        """Queue one framed payload for this peer. Never blocks.

        Returns False when the bounded outbox is full. Callers must count that
        as a drop: the coordinator treats a lost grant as *no grant*
        (``AGENTS.md`` rule 4), never as a permission.
        """
        if len(self._outbox) >= self._outbox_capacity:
            self.dropped += 1
            return False
        self._outbox.append(frame)
        return True

    def health(
        self,
        *,
        now_ns: int,
        silence_threshold_ns: int,
        inbound_connected: bool,
        inbound_rx_ns: int | None,
    ) -> dict[str, object]:
        """Per-peer state, including the connected-but-silent distinction.

        "No evidence yet" is reported as ``None``, never as ``0``: the monotonic
        clock has millisecond resolution on Windows, so the first real measurement
        on a link can *be* ``0``, and a zero sentinel would report that as silence
        that never happened (``AGENTS.md`` rule 10 - a missing metric is
        unavailable, not zero).
        """
        connected = self._connected or inbound_connected
        last_rx = _latest(self._last_rx_ns, inbound_rx_ns)
        last_activity_ns = _latest(last_rx, self._last_tx_ns, self._connected_at_ns)
        silence_ns = None if last_activity_ns is None else max(0, now_ns - last_activity_ns)
        if not connected:
            status = PeerStatus.DISCONNECTED
        elif silence_ns is not None and silence_ns > silence_threshold_ns:
            status = PeerStatus.CONNECTED_SILENT
        else:
            status = PeerStatus.HEALTHY
        return {
            "peer_id": self._peer_id,
            "status": status.value,
            "availability": ("available" if status is PeerStatus.HEALTHY else "unavailable"),
            "connected": connected,
            "outbound_connected": self._connected,
            "inbound_connected": inbound_connected,
            #: Ephemeral source port this process dialled the peer from. A peer's
            #: `observed_inbound_peers` entry must equal exactly this, which is
            #: what makes "no relay" a checkable fact rather than a claim.
            "dialed_from_port": self._local_port,
            "last_rx_ns": last_rx,
            "last_tx_ns": self._last_tx_ns,
            "silence_ms": None if silence_ns is None else round(silence_ns / 1e6, 3),
            "dropped": self.dropped,
            "connect_attempts": self._connect_attempts,
            "reconnects": self._reconnects,
            "tx_failures": self._tx_failures,
            "outbox_depth": len(self._outbox),
            "outbox_capacity": self._outbox_capacity,
        }

    # --------------------------------------------------------------- internals

    def _backoff_s(self, backoff_ns: int) -> float:
        jitter = self._streams.uniform(f"peer:{self._peer_id}:backoff", 0.85, 1.15)
        return backoff_ns * jitter / 1_000_000_000

    def _attach(self, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        self._connected = True
        self._connected_at_ns = self._clock.now_ns()
        sockname = writer.get_extra_info("sockname")
        if isinstance(sockname, tuple) and len(sockname) >= 2:
            self._local_port = int(sockname[1])

    def _detach(self) -> None:
        writer = self._writer
        self._writer = None
        self._connected = False
        self._connected_at_ns = None
        self._local_port = 0
        if writer is not None:
            with suppress(OSError, ConnectionError):
                writer.close()

    async def _pump(self) -> None:
        """Drain the outbox in order. One writer at a time, so ordering holds."""
        try:
            while not self._stop_requested():
                if not self._outbox:
                    await asyncio.sleep(_DRAIN_INTERVAL_S)
                    continue
                if not self._connected:
                    await asyncio.sleep(_BACKOFF_MIN_NS / 1_000_000_000)
                    continue
                if not await self.write(self._outbox[0]):
                    self._trace.record(
                        at_ns=self._clock.now_ns(),
                        scope="pump_stopped",
                        peer_id=self._peer_id,
                        detail=f"write_failed outbox={len(self._outbox)}",
                    )
                    return
                self._outbox.popleft()
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._trace.record_exception(
                at_ns=self._clock.now_ns(),
                scope="pump_escaped",
                peer_id=self._peer_id,
                exc=exc,
            )
            raise

    async def write(self, frame: bytes) -> bool:
        """Write one framed payload, preserving per-peer ordering."""
        writer = self._writer
        if writer is None or not self._connected:
            return False
        async with self._write_lock:
            try:
                writer.write(frame)
                await writer.drain()
            except (OSError, ConnectionError):
                self._tx_failures += 1
                self._detach()
                self.dropped += 1
                return False
        self._last_tx_ns = self._clock.now_ns()
        self._frames.record_out(frame)
        return True

    async def _read_loop(self, reader: asyncio.StreamReader, on_frame: Callable[[bytes], bool]) -> None:
        while True:
            payload = await read_frame(reader, max_bytes=MAX_FRAME_BYTES, stats=self._frames)
            self._last_rx_ns = self._clock.now_ns()
            if not on_frame(payload):
                return


class PeerTransportServer:
    """The listening and dialling half of one robot's peer link.

    Implements :class:`niharamesh.ports.PeerTransport`. ``send`` never fabricates
    a message and never reorders the pipeline: the fault layer decides, this
    class executes.
    """

    def __init__(
        self,
        *,
        identity: RobotIdentity,
        session: RobotSession,
        membership: Membership,
        peers: Mapping[str, PeerDeclaration],
        fault_layer: FaultLayer | None = None,
        clock: Clock | None = None,
        bind_host: str = "127.0.0.1",
        bind_port: int = 0,
        inbox_capacity: int = DEFAULT_INBOX_CAPACITY,
        replay_window: int = DEFAULT_REPLAY_WINDOW,
        silence_threshold_ns: int = DEFAULT_SILENCE_THRESHOLD_NS,
        max_message_bytes: int = MAX_MESSAGE_BYTES,
        seed: int = 0,
    ) -> None:
        _require_loopback(bind_host)
        if inbox_capacity < 1:
            raise ValueError("inbox_capacity must be at least 1")
        if replay_window < 1:
            raise ValueError("replay_window must be at least 1")
        self._identity = identity
        self._session = session
        self._membership = membership
        self._peers: dict[str, PeerDeclaration] = dict(peers)
        self._fault = fault_layer or FaultLayer(local_robot_id=identity.robot_id)
        self._clock: Clock = clock or MonotonicClock()
        self._bind_host = bind_host
        self._bind_port = bind_port
        self._silence_threshold_ns = silence_threshold_ns
        self._max_message_bytes = max_message_bytes
        self._streams = SeededStreams(base_seed=seed)
        self._frames = FrameStats()
        self._windows: dict[str, ReplayWindow] = {
            pid: ReplayWindow(capacity=replay_window) for pid in self._peers
        }
        self._inbox = BoundedInbox(inbox_capacity)
        self._clients: dict[str, PeerClient] = {}
        self._inbound_live: dict[str, int] = {}
        self._inbound_rx_ns: dict[str, int] = {}
        self._observed_inbound: dict[str, set[tuple[str, int]]] = {}
        self._tasks: set[asyncio.Task[None]] = set()
        self._server: asyncio.Server | None = None
        self._started = False
        self._stopping = False
        self._dropped_by_kind: dict[str, int] = {}
        self._rejected_by_reason: dict[str, int] = {}
        self._clock_sync: cs.ClockSync | None = None
        self._listening_port = 0
        self._outbound_seq = 0
        self._trace = LinkTrace()

    # ------------------------------------------------------------- properties

    @property
    def peers(self) -> tuple[str, ...]:
        return tuple(sorted(self._clients))

    @property
    def robot_id(self) -> str:
        return self._identity.robot_id

    @property
    def session_id(self) -> str:
        return self._session.session_id

    @property
    def pid(self) -> int:
        return self._session.pid

    @property
    def listening_port(self) -> int:
        return self._listening_port

    @property
    def inbox_depth(self) -> int:
        return len(self._inbox)

    @property
    def inbox_capacity(self) -> int:
        return self._inbox.capacity

    @property
    def dropped_by_kind(self) -> dict[str, int]:
        return dict(self._dropped_by_kind)

    @property
    def frames(self) -> FrameStats:
        return self._frames

    @property
    def fault_layer(self) -> FaultLayer:
        return self._fault

    def attach_clock_sync(self, sync: cs.ClockSync) -> None:
        """Install the clock estimator. With no state provider, probes are skipped."""
        self._clock_sync = sync

    # ------------------------------------------------------------------ ports

    async def start(self) -> None:
        """Bind the loopback listener, dial every declared peer, start workers."""
        if self._started:
            return
        self._stopping = False
        self._server = await asyncio.start_server(self._on_connection, self._bind_host, self._bind_port)
        sockets = self._server.sockets or ()
        if sockets:
            self._listening_port = int(sockets[0].getsockname()[1])
        for peer_id, declaration in sorted(self._peers.items()):
            self._clients[peer_id] = PeerClient(
                peer_id,
                declaration.endpoint,
                clock=self._clock,
                frames=self._frames,
                streams=self._streams,
                trace=self._trace,
            )
        for client in self._clients.values():
            self._spawn(client.run(self._accept_inbound_frame), scope=f"link:{client.peer_id}")
        self._spawn(self._drain_reorder(), scope="reorder_drain")
        self._started = True
        if self._clock_sync is not None:
            self._clock_sync.start(self.send, self.peers)

    async def stop(self) -> None:
        """Close every link and wait for every task. Idempotent."""
        if self._stopping:
            return
        self._stopping = True
        if self._clock_sync is not None:
            await self._clock_sync.stop()
        for client in self._clients.values():
            await client.stop()
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        self._inbox.close()
        self._started = False

    async def send(self, peer_robot_id: str, message: PeerMessage) -> None:
        """Offer one message to one peer, subject to the fault layer."""
        client = self._clients.get(peer_robot_id)
        if client is None:
            raise KeyError(f"{peer_robot_id!r} is not a declared peer of {self.robot_id!r}")
        decision = self._fault.apply_outbound(peer_robot_id, message, self._clock.now_ns())
        if decision.dropped:
            client.note_drop()
            self._count_drop(message, f"outbound_{decision.fault_id or 'dropped'}")
            return
        if decision.kind is DecisionKind.HOLD:
            return  # the drain worker sends it once the reorder hold elapses
        self._emit_outbound(peer_robot_id, message, decision.deliver_at_ns, decision.copies)

    async def inbox(self) -> AsyncIterator[PeerMessage]:
        """Yield accepted peer messages until :meth:`stop` is called."""
        while True:
            message = await self._inbox.get()
            if message is None:
                return
            yield message

    # ----------------------------------------------------------------- health

    def health(self) -> dict[str, object]:
        """Everything a doctor needs, including honest per-peer silence."""
        now_ns = self._clock.now_ns()
        peers: dict[str, dict[str, object]] = {}
        for peer_id, client in self._clients.items():
            peers[peer_id] = client.health(
                now_ns=now_ns,
                silence_threshold_ns=self._silence_threshold_ns,
                inbound_connected=self._inbound_live.get(peer_id, 0) > 0,
                inbound_rx_ns=self._inbound_rx_ns.get(peer_id),
            )
        silent = [pid for pid, p in peers.items() if p["status"] == PeerStatus.CONNECTED_SILENT]
        offline = [pid for pid, p in peers.items() if p["status"] == PeerStatus.DISCONNECTED]
        return {
            "robot_id": self._identity.robot_id,
            "session_id": self._session.session_id,
            "pid": self._session.pid,
            "bind_host": self._bind_host,
            "listening_port": self._listening_port,
            "run_id": self._membership.run_id,
            "epoch": self._membership.epoch,
            "outbound_seq": self._outbound_seq,
            "inbox_depth": self.inbox_depth,
            "inbox_capacity": self.inbox_capacity,
            "inbox_shed_replaceable": self._inbox.shed_replaceable,
            "inbox_refused": self._inbox.refused,
            "dropped_by_kind": dict(self._dropped_by_kind),
            "rejected_by_reason": dict(self._rejected_by_reason),
            "frames": self._frames.as_dict(),
            "replay_windows": {pid: w.as_dict() for pid, w in self._windows.items()},
            "observed_inbound_peers": {
                pid: [list(addr) for addr in sorted(addrs)]
                for pid, addrs in sorted(self._observed_inbound.items())
            },
            "peers": peers,
            "silent_peers": silent,
            "disconnected_peers": offline,
            "faults": self._fault.health(now_ns),
            "clock_sync": self._clock_sync.health() if self._clock_sync is not None else {},
            "stopped": self._stopping,
        }

    def link_trace(self) -> dict[str, object]:
        """Why each peer link is in the state :meth:`health` reports.

        Separate from :meth:`health` on purpose. ``health`` answers "what is true
        now"; this answers "what happened", and only a diagnosis needs it. A peer
        reporting ``disconnected`` with ``connect_attempts == 1`` looks identical
        whether the reconnect loop is mid-backoff, mid-retry, or dead - and those
        three have three different fixes.
        """
        return {
            "recorded": self._trace.recorded,
            "evicted": self._trace.evicted,
            "capacity": self._trace.capacity,
            "inbound_live": dict(sorted(self._inbound_live.items())),
            "inbound_rx_ns": dict(sorted(self._inbound_rx_ns.items())),
            "live_tasks": len([task for task in self._tasks if not task.done()]),
            "worker_failures": self._trace.failures,
            "events": [event.as_dict() for event in self._trace.events],
        }

    # --------------------------------------------------------------- internals

    def _on_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Accept callback. Tracks the handler so :meth:`stop` leaves no task."""
        self._spawn(self._serve_connection(reader, writer), scope="serve")

    async def _serve_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_id = ""
        sockname = writer.get_extra_info("peername")
        origin = f"{sockname}" if sockname is not None else "?"
        try:
            while True:
                try:
                    payload = await read_frame(reader, max_bytes=MAX_FRAME_BYTES, stats=self._frames)
                except ConnectionClosedError:
                    self._trace.record(
                        at_ns=self._clock.now_ns(),
                        scope="serve_clean_eof",
                        peer_id=peer_id,
                        detail=f"from {origin} frames_in={self._frames.frames_in}",
                    )
                    return  # peer hung up at a frame boundary; nothing is wrong
                except TruncatedFrameError:
                    self._bump("frame:truncated")
                    return
                except FrameTooLargeError:
                    self._bump("frame:too_large")
                    return
                message = decode_message(payload, max_bytes=self._max_message_bytes)
                if not peer_id:
                    peer_id = message.envelope.sender
                    self._inbound_live[peer_id] = self._inbound_live.get(peer_id, 0) + 1
                    self._note_inbound_socket(peer_id, writer)
                self._inbound_rx_ns[peer_id] = self._clock.now_ns()
                # Only answer a clock probe that actually reached the application.
                # A partitioned or replayed probe gets neither state nor reply.
                if self._on_message(message):
                    self._answer_clock_probe(message)
        except ProtocolDecodeError as exc:
            self._bump(f"decode:{exc.code}")
            self._trace.record(
                at_ns=self._clock.now_ns(),
                scope="serve_decode_error",
                peer_id=peer_id,
                detail=f"{exc.code} at {exc.field} from {origin}",
            )
        except (OSError, ConnectionError) as exc:
            self._trace.record(
                at_ns=self._clock.now_ns(),
                scope="serve_link_died",
                peer_id=peer_id,
                detail=f"{type(exc).__name__}: {exc} from {origin}",
            )
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._trace.record_exception(
                at_ns=self._clock.now_ns(),
                scope="serve_escaped",
                peer_id=peer_id,
                exc=exc,
            )
            raise
        finally:
            if peer_id:
                self._inbound_live[peer_id] = max(0, self._inbound_live.get(peer_id, 1) - 1)
                self._trace.record(
                    at_ns=self._clock.now_ns(),
                    scope="serve_closed",
                    peer_id=peer_id,
                    detail=(
                        f"from {origin} live={self._inbound_live[peer_id]} frames_in={self._frames.frames_in}"
                    ),
                )
            with suppress(OSError, ConnectionError):
                writer.close()
                await writer.wait_closed()

    def _accept_inbound_frame(self, payload: bytes) -> bool:
        """Decode one frame arriving on a link we dialled. ``False`` closes it."""
        try:
            message = decode_message(payload, max_bytes=self._max_message_bytes)
        except ProtocolDecodeError as exc:
            self._bump(f"decode:{exc.code}")
            return False
        self._on_message(message)
        return True

    def _on_message(self, message: PeerMessage) -> bool:
        """Fold a clock reply into the estimator, then run the pipeline.

        Returns True when the message reached the inbox, so the caller can decide
        whether transport-level bookkeeping (a clock reply) is warranted.
        """
        sync = self._clock_sync
        if sync is not None:
            try:
                sync.observe_reply(message)
            except BaseException as exc:
                self._trace.record_exception(
                    at_ns=self._clock.now_ns(),
                    scope="clock_sync_escaped",
                    peer_id=message.envelope.sender,
                    exc=exc,
                )
                raise
        return self._ingest(message)

    def _note_inbound_socket(self, peer_id: str, writer: asyncio.StreamWriter) -> None:
        """Record the socket address a peer's bytes actually arrived from.

        This is observed evidence, not configuration: it is what a reviewer reads
        to confirm a message travelled from a peer rather than from a relay.
        """
        info = writer.get_extra_info("peername")
        if isinstance(info, tuple) and len(info) >= 2:
            host, port = str(info[0]), int(info[1])
            self._observed_inbound.setdefault(peer_id, set()).add((host, port))

    def _answer_clock_probe(self, message: PeerMessage) -> None:
        """Reply to a peer's clock probe through the normal outbound path.

        Routing the reply through :meth:`_write_peer` (rather than straight onto
        the inbound socket) keeps one per-sender sequence counter: the agent's
        publications and this reply share it, so the peer never sees two
        counters colliding inside its replay window.
        """
        sync = self._clock_sync
        if sync is None or message.envelope.kind != "peer_state":
            return
        reply = sync.reply_to(message)
        if reply is not None:
            self._write_peer(message.envelope.sender, reply)

    def _ingest(self, message: PeerMessage) -> bool:
        """Admission, replay window, fault layer, bounded inbox.

        Returns True when at least one copy reached the inbox.
        """
        sender = message.envelope.sender
        try:
            outcome = self._admit(message)
            if outcome not in ("admitted", "probationary"):
                self._reject(message, f"admission:{outcome}")
                return False
            window = self._windows.get(sender)
            if window is not None and not window.admit(message.envelope.seq):
                self._reject(message, "replay_window")
                return False
            decision = self._fault.apply_inbound(message, self._clock.now_ns())
            if decision.dropped:
                self._count_drop(message, f"inbound_{decision.fault_id or 'dropped'}")
                return False
            if decision.kind is DecisionKind.HOLD:
                return False  # the drain worker delivers it when the hold elapses
            delivered = False
            for _ in range(decision.copies):
                if self._inbox.put(message):
                    delivered = True
                else:
                    self._count_drop(message, "inbox_refused")
            return delivered
        except BaseException as exc:
            self._trace.record_exception(
                at_ns=self._clock.now_ns(),
                scope="ingest_escaped",
                peer_id=sender,
                exc=exc,
            )
            raise

    def _admit(self, message: PeerMessage) -> str:
        """Run the one shared admission rule. Undeclared senders are refused."""
        declaration = self._peers.get(message.envelope.sender)
        if declaration is None:
            return "undeclared"
        if declaration.session.session_id != message.envelope.sender_session:
            # A rebooted robot is a different incarnation. Never merge it into
            # current state, and never accept it as the old session either.
            return "stale_session"
        return str(
            admission_outcome(
                declaration.identity,
                declaration.session,
                self._membership,
                observed_protocol=message.envelope.protocol_version,
            )
        )

    def _emit_outbound(self, peer_id: str, message: PeerMessage, deliver_at_ns: int, copies: int) -> None:
        delay_ns = max(0, deliver_at_ns - self._clock.now_ns())
        if delay_ns > 0:
            self._spawn(self._delayed_emit(peer_id, message, delay_ns, copies))
            return
        self._write_peer(peer_id, message, copies)

    async def _delayed_emit(self, peer_id: str, message: PeerMessage, delay_ns: int, copies: int) -> None:
        await asyncio.sleep(delay_ns / 1_000_000_000)
        if not self._stopping:
            self._write_peer(peer_id, message, copies)

    def _write_peer(self, peer_id: str, message: PeerMessage, copies: int = 1) -> None:
        """Stamp the outbound sequence, encode and queue. Never blocks, never grows."""
        client = self._clients.get(peer_id)
        if client is None:
            return
        try:
            frame = encode_message(self._stamped(message), max_bytes=self._max_message_bytes)
        except ProtocolDecodeError as exc:
            self._bump(f"encode:{exc.code}")
            return
        except ValueError as exc:
            self._bump(f"encode:{type(exc).__name__}")
            return
        for _ in range(copies):
            if not client.transmit(frame):
                self._count_drop(message, "outbox_full")

    def _stamped(self, message: PeerMessage) -> PeerMessage:
        """Apply the next outbound sequence number.

        ``PeerEnvelope.seq`` is *per sender*, and the sender is this process, so
        the transport owns the counter. The agent's publications and this
        transport's own clock replies share it; two independent counters would
        collide inside the peer's replay window and a clock reply would be (quite
        correctly) rejected as a replayed message.
        """
        seq = self._outbound_seq
        self._outbound_seq += 1
        body = message.body
        if isinstance(getattr(body, "seq", None), int):
            body = body.model_copy(update={"seq": seq})
        return message.model_copy(
            update={"envelope": message.envelope.model_copy(update={"seq": seq}), "body": body}
        )

    async def _drain_reorder(self) -> None:
        """Release messages a reorder fault parked, once their hold elapses."""
        while not self._stopping:
            await asyncio.sleep(_DRAIN_INTERVAL_S)
            for pending in self._fault.drain(self._clock.now_ns()):
                if pending.direction == "inbound":
                    if not self._inbox.put(pending.message):
                        self._count_drop(pending.message, "inbox_refused")
                else:
                    self._write_peer(pending.peer_id, pending.message)

    def _bump(self, key: str) -> None:
        self._rejected_by_reason[key] = self._rejected_by_reason.get(key, 0) + 1

    def _reject(self, message: PeerMessage, reason: str) -> None:
        self._bump(f"{reason}:{message.envelope.kind}")
        kind = message.envelope.kind
        self._dropped_by_kind[kind] = self._dropped_by_kind.get(kind, 0) + 1

    def _count_drop(self, message: PeerMessage, reason: str) -> None:
        kind = message.envelope.kind
        self._dropped_by_kind[kind] = self._dropped_by_kind.get(kind, 0) + 1
        self._bump(f"drop:{reason}")

    def _spawn(self, coro: Coroutine[Any, Any, None], *, scope: str = "worker") -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(partial(self._reap, scope=scope))

    def _reap(self, task: asyncio.Task[None], /, *, scope: str) -> None:
        """Discard a finished worker, recording *why* it finished.

        Without this the transport's own failure modes are invisible. A worker
        that dies on an unhandled exception used to leave nothing behind but a
        silently shrinking worker set and a peer link that never recovers, which
        is exactly how a link that will never reconnect becomes indistinguishable
        from a link that is merely between attempts.
        """
        self._tasks.discard(task)
        now_ns = self._clock.now_ns()
        if task.cancelled():
            self._trace.record(
                at_ns=now_ns,
                scope=f"{scope}.cancelled",
                detail="worker cancelled; a cancelled worker never reconnects",
            )
            return
        exc = task.exception()
        if exc is None:
            return
        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._trace.record_failure(
            at_ns=now_ns,
            scope=f"{scope}.failed",
            peer_id="",
            summary=f"{type(exc).__name__}: {exc}\n{text[-_TRACEBACK_CHARS:]}",
        )


def _require_loopback(host: str) -> str:
    if host not in _LOOPBACK_HOSTS:
        raise ValueError(f"refusing to bind {host!r}: peer sockets are loopback-only by default")
    return host

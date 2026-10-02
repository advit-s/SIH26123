"""Observer recorder. Reads state and events; holds no authority.

Implements :class:`niharamesh.ports.ObservationSink`.

Two clock domains, never mixed
------------------------------
:class:`~niharamesh.domain.telemetry.DomainEvent` carries four clock fields for
a reason: ``event_time_ns``/``time_domain`` come from the *source* (the robot
that observed the thing), while ``receive_time_ns``/``receive_time_domain`` come
from the *observer* (this process). They are different domains and are never
subtracted here. A caller cannot supply ``receive_*`` at all - attempting to is
an error, because a source-supplied receive stamp is exactly how a display-UTC
number sneaks into a monotonic deadline.

Losing the observer changes nothing
------------------------------------
The recorder holds no reference to the world, no simulator clock and no agent.
Its failure path is a counted no-op: :meth:`Recorder.emit` never raises, so a
broken store, a full disk or a dead API cannot stop the simulation clock or take
away any robot's decision authority (``AGENTS.md`` rule 1, ports
``ObservationSink``). The counters that prove this are in :meth:`Recorder.health`.
"""

from __future__ import annotations

from typing import Any, Final, Protocol

from niharamesh.clocks import Clock, MonotonicClock
from niharamesh.domain.telemetry import (
    DomainEvent,
    EventCategory,
    EventSeverity,
    RecordingGap,
    TelemetrySample,
)
from niharamesh.telemetry.gaps import RecordingGapTracker

__all__ = ["DEFAULT_SPOOL_CAPACITY", "Recorder", "RecorderSink"]

#: Reported by :meth:`Recorder.health` when the sink does not know its own bound.
DEFAULT_SPOOL_CAPACITY: Final[int] = 4096

#: Keyword arguments a caller may supply to :meth:`Recorder.emit`. ``receive_*``
#: is absent on purpose: the observer owns those.
_CALLER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "category",
        "severity",
        "event_time_ns",
        "time_domain",
        "sim_time_s",
        "reason",
        "correlation_id",
        "robot_id",
        "task_id",
        "zone_id",
        "fault_id",
        "source_session",
    }
)

_RESERVED_KEYS: Final[frozenset[str]] = frozenset({"receive_time_ns", "receive_time_domain"})


class RecorderSink(Protocol):
    """The subset of the event store a recorder needs.

    Narrow on purpose: the recorder must be constructible against a sink that
    raises on every call, which is how "losing the observer" is tested, and it
    keeps :mod:`niharamesh.telemetry` free of any concrete persistence import.
    """

    def append_event(self, event: DomainEvent) -> int: ...

    def write_telemetry(self, sample: TelemetrySample) -> bool: ...

    def health(self) -> dict[str, object]: ...

    def gaps(self, category: EventCategory | None = None) -> tuple[RecordingGap, ...]: ...


class Recorder:
    """Turns agent observations into durable :class:`DomainEvent` records."""

    def __init__(
        self,
        sink: RecorderSink,
        *,
        run_id: str,
        robot_id: str,
        session_id: str,
        source_clock: Clock | None = None,
        observer_clock: Clock | None = None,
        tracker: RecordingGapTracker | None = None,
    ) -> None:
        self._sink = sink
        self._run_id = run_id
        self._robot_id = robot_id
        self._session_id = session_id
        self._source_clock: Clock = source_clock or MonotonicClock()
        self._observer_clock: Clock = observer_clock or MonotonicClock()
        # An empty tracker is falsy (it defines __len__), so test `is not None`.
        self._tracker = tracker if tracker is not None else RecordingGapTracker()
        self._recorded = 0
        self._dropped = 0
        self._telemetry_seen = 0
        self._telemetry_dropped = 0
        self._last_error = ""

    # ------------------------------------------------------------------ ports

    def emit(self, event_type: str, source: str, payload: dict[str, object], **kw: Any) -> None:
        """Record one event. Never raises.

        ``event_time_ns``/``time_domain`` default to the *source* clock;
        ``receive_time_ns``/``receive_time_domain`` are always the *observer*
        clock and cannot be overridden.
        """
        try:
            event = self._build(event_type, source, payload, kw)
            self._sink.append_event(event)
            self._recorded += 1
        except Exception as exc:
            self._dropped += 1
            self._last_error = f"{type(exc).__name__}: {exc}"

    def record_telemetry(self, sample: TelemetrySample) -> None:
        """Record one replaceable sample. Never raises."""
        self._telemetry_seen += 1
        try:
            if not self._sink.write_telemetry(sample):
                self._telemetry_dropped += 1
        except Exception as exc:
            self._telemetry_dropped += 1
            self._last_error = f"{type(exc).__name__}: {exc}"

    def health(self) -> dict[str, object]:
        """``recorded``, ``dropped``, ``spool_depth``, ``spool_capacity``, ``gaps``.

        ``durable_complete`` is False whenever a durable hole was recorded. It is
        reported as False, never as a metric of zero.
        """
        sink_health = self._safe_sink_health()
        summary = self._tracker.summary()
        return {
            "run_id": self._run_id,
            "robot_id": self._robot_id,
            "session_id": self._session_id,
            "recorded": self._recorded,
            "dropped": self._dropped,
            "telemetry_seen": self._telemetry_seen,
            "telemetry_dropped": self._telemetry_dropped,
            "spool_depth": sink_health.get("spool_depth"),
            "spool_capacity": sink_health.get("spool_capacity", DEFAULT_SPOOL_CAPACITY),
            "gaps": summary.total,
            "unrecovered_durable_gaps": summary.durable_unrecovered,
            "durable_complete": summary.durable_complete,
            "excluded_metrics": list(summary.excluded_metrics),
            "last_error": self._last_error,
            "sink": sink_health,
        }

    @property
    def gaps(self) -> RecordingGapTracker:
        return self._tracker

    # --------------------------------------------------------------- internals

    def _build(
        self, event_type: str, source: str, payload: dict[str, object], kw: dict[str, Any]
    ) -> DomainEvent:
        offending = _RESERVED_KEYS.intersection(kw)
        if offending:
            raise ValueError(
                "receive_time_ns/receive_time_domain are owned by the observer; "
                f"a source may not supply {sorted(offending)}"
            )
        unknown = set(kw).difference(_CALLER_KEYS)
        if unknown:
            raise ValueError(f"emit() received unknown keyword(s): {sorted(unknown)}")
        event_time_ns = int(kw.get("event_time_ns", self._source_clock.now_ns()))
        return DomainEvent(
            run_id=self._run_id,
            seq=0,  # the store owns the total order
            source=str(source)[:64] or self._robot_id,
            source_session=str(kw.get("source_session", self._session_id))[:40],
            event_time_ns=max(0, event_time_ns),
            time_domain=kw.get("time_domain", self._source_clock.domain),
            receive_time_ns=max(0, self._observer_clock.now_ns()),
            receive_time_domain=self._observer_clock.domain,
            sim_time_s=float(kw.get("sim_time_s", 0.0)),
            type=str(event_type)[:64],
            category=kw.get("category", EventCategory.LIFECYCLE),
            severity=kw.get("severity", EventSeverity.INFO),
            reason=str(kw.get("reason", ""))[:240],
            correlation_id=str(kw.get("correlation_id", ""))[:64],
            robot_id=kw.get("robot_id"),
            task_id=kw.get("task_id"),
            zone_id=kw.get("zone_id"),
            fault_id=kw.get("fault_id"),
            payload=dict(payload),
        )

    def _safe_sink_health(self) -> dict[str, object]:
        try:
            return dict(self._sink.health())
        except Exception as exc:
            self._last_error = f"{type(exc).__name__}: {exc}"
            return {"spool_depth": 0, "spool_capacity": 0, "unavailable": True}

    def ingest_gap_tracker(self, sink: RecorderSink) -> RecordingGapTracker:
        """Adopt the gaps already persisted by *sink*. Pure bookkeeping."""
        for gap in sink.gaps():
            self._tracker.record(gap)
        return self._tracker

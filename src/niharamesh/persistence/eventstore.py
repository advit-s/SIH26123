"""Observer store: run metadata, the durable event log, and telemetry.

Two artifacts, two jobs:

``run.sqlite3``
    Queryable run metadata, the event rows, replaceable telemetry samples and
    the recording-gap table. Restarting the API opens this and replays.
``events.jsonl``
    The append-only artifact that :mod:`niharamesh.replay` reads. One canonical
    JSON object per line, in ``seq`` order, fsynced on flush.

The store holds **no authority**. It cannot award a task, grant a zone or move a
robot. :meth:`EventStore.open_or_create` is idempotent precisely so restarting
the observer cannot reset the fleet or re-run an auction: the read model is
rebuilt by *replaying stored events*, and :func:`rebuild_read_model` is a pure
function of what is on disk.

Gaps are explicit
-----------------
A bounded in-memory spool (:class:`EventSpool`) sits in front of the durable
write. When it overflows:

* a durable category (``AUTHORITY``, ``EVALUATION``, ``TASK``, ``SAFETY``,
  ``FAULT``, ``COMMAND``) produces a :class:`RecordingGap` naming the exact
  ``seq`` that was lost. There is no code path that discards a durable event
  without writing that down;
* telemetry may additionally be decimated, and every decimation is recorded as a
  gap in ``EventCategory.TELEMETRY`` so the hole is visible rather than inferred
  from a suspiciously smooth trace.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from niharamesh.clocks import Clock, MonotonicClock
from niharamesh.domain.telemetry import (
    DURABLE_CATEGORIES,
    DomainEvent,
    EventCategory,
    RecordingGap,
    TelemetrySample,
    compute_digest,
)
from niharamesh.persistence.migrations import MigrationError, current_version, migrate

__all__ = [
    "DEFAULT_SPOOL_CAPACITY",
    "EventSpool",
    "EventStore",
    "ReadModel",
    "rebuild_read_model",
]

DEFAULT_SPOOL_CAPACITY: Final[int] = 4096
_READ_ALL_LIMIT: Final[int] = 10_000_000
_EVENTS_FILE = "events.jsonl"
_DB_FILE = "run.sqlite3"

_EVENT_COLUMNS = (
    "run_id, seq, category, severity, event_type, source, source_session, event_time_ns, "
    "time_domain, receive_time_ns, receive_time_domain, sim_time_s, correlation_id, robot_id, "
    "task_id, zone_id, fault_id, reason, payload"
)


@dataclass(frozen=True, slots=True)
class ReadModel:
    """Everything the cockpit needs, derived purely from stored events.

    Rebuilt by :func:`rebuild_read_model`. It contains no inference: if an event
    was never recorded, the corresponding state is simply absent here.
    """

    run_id: str
    events_replayed: int
    last_seq: int
    robot_positions: dict[str, tuple[float, float, float]]
    zone_holders: dict[str, str]
    fenced_zones: dict[str, str]
    task_owners: dict[str, str]
    authority_transitions: int
    category_counts: dict[str, int]
    gaps: tuple[RecordingGap, ...]
    digest: str

    @property
    def durable_complete(self) -> bool:
        return not any(not g.recovered and g.category in DURABLE_CATEGORIES for g in self.gaps)

    def as_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "events_replayed": self.events_replayed,
            "last_seq": self.last_seq,
            "robot_positions": {k: list(v) for k, v in self.robot_positions.items()},
            "zone_holders": dict(self.zone_holders),
            "fenced_zones": dict(self.fenced_zones),
            "task_owners": dict(self.task_owners),
            "authority_transitions": self.authority_transitions,
            "category_counts": dict(self.category_counts),
            "gaps": [g.model_dump(mode="json") for g in self.gaps],
            "durable_complete": self.durable_complete,
            "digest": self.digest,
        }


@dataclass(slots=True)
class EventSpool:
    """A bounded in-memory staging buffer with explicit overflow accounting.

    Overflow is never silent: a durable category increments ``durable_overflow``
    (the caller records a :class:`RecordingGap`), a replaceable one increments
    ``replaceable_overflow``. An unbounded spool would be a defect.
    """

    capacity: int = DEFAULT_SPOOL_CAPACITY
    durable_overflow: int = 0
    replaceable_overflow: int = 0
    _items: deque[DomainEvent] = field(default_factory=deque)

    def __len__(self) -> int:
        return len(self._items)

    @property
    def depth(self) -> int:
        return len(self._items)

    def put(self, event: DomainEvent) -> bool:
        """Buffer *event*. Returns False when it overflowed."""
        if len(self._items) >= self.capacity:
            if event.category in DURABLE_CATEGORIES:
                self.durable_overflow += 1
            else:
                self.replaceable_overflow += 1
            return False
        self._items.append(event)
        return True

    def drain(self) -> Iterator[DomainEvent]:
        while self._items:
            yield self._items.popleft()


class EventStore:
    """Append-only observer store for one run."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        run_id: str,
        clock: Clock | None = None,
        spool_capacity: int = DEFAULT_SPOOL_CAPACITY,
        telemetry_decimation: int = 1,
        auto_flush: bool = True,
    ) -> None:
        if spool_capacity < 1:
            raise ValueError("spool_capacity must be at least 1")
        if telemetry_decimation < 1:
            raise ValueError("telemetry_decimation must be at least 1")
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._run_id = run_id
        self._clock: Clock = clock or MonotonicClock()
        self._decimation = telemetry_decimation
        self._auto_flush = auto_flush
        self._spool = EventSpool(capacity=spool_capacity)
        self._conn = sqlite3.connect(str(self._root / _DB_FILE), isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        try:
            migrate(self._conn)
        except MigrationError as exc:  # pragma: no cover - the schema is ours
            raise RuntimeError(f"event store schema could not be prepared: {exc}") from exc
        now_ns = self._clock.now_ns()
        self._conn.execute(
            "INSERT INTO run_registry (run_id, created_at_ns, scenario_digest, state, "
            "updated_at_ns) VALUES (?, ?, '', 'running', ?) "
            "ON CONFLICT(run_id) DO NOTHING",
            (run_id, now_ns, now_ns),
        )
        self._next_seq = self._highest_seq() + 1
        self._jsonl = (self._root / _EVENTS_FILE).open("a", encoding="utf-8", newline="\n")
        self._telemetry_seen = 0
        self._telemetry_written = 0
        self._telemetry_decimated = 0

    # ------------------------------------------------------------ construction

    @classmethod
    def open_or_create(
        cls,
        root: str | os.PathLike[str],
        run_id: str,
        **kwargs: object,
    ) -> EventStore:
        """Open the run's store, creating it only when absent.

        Idempotent: reopening an existing run neither clears events nor resets
        the sequence, which is what lets the API restart without disturbing the
        fleet it is observing.
        """
        store = cls(root, run_id=run_id, **kwargs)  # type: ignore[arg-type]
        return store

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def events_path(self) -> Path:
        return self._root / _EVENTS_FILE

    # ------------------------------------------------------------------ writes

    def append_event(self, event: DomainEvent) -> int:
        """Append one event. Returns the assigned global ``seq``.

        The sequence is monotonic and gap-free within a process. A durable event
        that cannot be buffered produces an explicit :class:`RecordingGap` naming
        that exact ``seq`` - there is no silent discard.
        """
        seq = self._next_seq
        self._next_seq += 1
        stored = event.model_copy(update={"seq": seq, "run_id": self._run_id})
        if not self._spool.put(stored) and stored.category in DURABLE_CATEGORIES:
            self._record_gap(
                RecordingGap(
                    run_id=self._run_id,
                    category=stored.category,
                    from_seq=seq,
                    to_seq=seq,
                    sim_time_from_s=stored.sim_time_s,
                    sim_time_to_s=stored.sim_time_s,
                    cause="durable event lost to spool exhaustion",
                )
            )
        if self._auto_flush:
            self.flush()
        return seq

    def write_telemetry(self, sample: TelemetrySample) -> bool:
        """Record one replaceable sample. Returns False when it was decimated.

        Decimation is *recorded* as a gap, and durability categories never route
        through this method at all.
        """
        self._telemetry_seen += 1
        if self._decimation > 1 and sample.sample_index % self._decimation != 0:
            self._telemetry_decimated += 1
            self._record_gap(
                RecordingGap(
                    run_id=self._run_id,
                    category=EventCategory.TELEMETRY,
                    from_seq=sample.sample_index,
                    to_seq=sample.sample_index,
                    sim_time_from_s=sample.sim_time_s,
                    sim_time_to_s=sample.sim_time_s,
                    cause=f"telemetry decimated 1/{self._decimation}",
                )
            )
            return False
        self._conn.execute(
            "INSERT OR REPLACE INTO telemetry_samples (run_id, sample_index, robot_id, "
            "sim_time_s, payload, recorded_at_ns) VALUES (?, ?, ?, ?, ?, ?)",
            (
                self._run_id,
                sample.sample_index,
                sample.robot_id,
                sample.sim_time_s,
                sample.model_dump_json(),
                self._clock.now_ns(),
            ),
        )
        self._telemetry_written += 1
        return True

    def record_gap(self, gap: RecordingGap) -> None:
        """Record an explicit hole in the evidence."""
        self._record_gap(gap)

    def flush(self) -> int:
        """Drain the spool to SQLite and the JSONL artifact. Returns rows written."""
        written = 0
        for event in self._spool.drain():
            payload = event.model_dump(mode="json")
            self._conn.execute(
                "INSERT OR REPLACE INTO domain_events (run_id, seq, category, severity, "
                "event_type, source, source_session, event_time_ns, time_domain, "
                "receive_time_ns, receive_time_domain, sim_time_s, correlation_id, robot_id, "
                "task_id, zone_id, fault_id, reason, payload, digest) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    self._run_id,
                    event.seq,
                    event.category.value,
                    event.severity.value,
                    event.type,
                    event.source,
                    event.source_session,
                    event.event_time_ns,
                    event.time_domain.value,
                    event.receive_time_ns,
                    event.receive_time_domain.value,
                    event.sim_time_s,
                    event.correlation_id,
                    event.robot_id,
                    event.task_id,
                    event.zone_id,
                    event.fault_id,
                    event.reason,
                    json.dumps(payload["payload"], sort_keys=True, separators=(",", ":")),
                    event.digest(),
                ),
            )
            self._jsonl.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str) + "\n")
            written += 1
        if written:
            self._conn.commit()
            self._jsonl.flush()
            os.fsync(self._jsonl.fileno())
            self._conn.execute(
                "UPDATE run_registry SET updated_at_ns = ? WHERE run_id = ?",
                (self._clock.now_ns(), self._run_id),
            )
        return written

    def close(self) -> None:
        try:
            self.flush()
        finally:
            self._jsonl.close()
            self._conn.close()

    def __enter__(self) -> EventStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------- reads

    def event_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM domain_events WHERE run_id = ?", (self._run_id,)
        ).fetchone()
        return 0 if row is None or row[0] is None else int(row[0])

    def read_events(self, from_seq: int = 0, limit: int = 1000) -> list[DomainEvent]:
        """Read events from ``from_seq`` in ``seq`` order. Never fabricates a row."""
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM domain_events "  # noqa: S608 - fixed column list
            "WHERE run_id = ? AND seq >= ? ORDER BY seq LIMIT ?",
            (self._run_id, int(from_seq), int(limit)),
        ).fetchall()
        return [_event_from_row(row) for row in rows]

    def read_all_events(self, from_seq: int = 0) -> list[DomainEvent]:
        """Every event from ``from_seq`` onwards, in order."""
        return self.read_events(from_seq, limit=_READ_ALL_LIMIT)

    def read_telemetry(self, run_id: str, from_index: int = 0, limit: int = 1000) -> list[TelemetrySample]:
        """Read replaceable telemetry samples for *run_id*."""
        rows = self._conn.execute(
            "SELECT payload FROM telemetry_samples WHERE run_id = ? AND sample_index >= ? "
            "ORDER BY sample_index LIMIT ?",
            (run_id, int(from_index), int(limit)),
        ).fetchall()
        return [TelemetrySample.model_validate_json(str(row[0])) for row in rows]

    def gaps(self, category: EventCategory | None = None) -> tuple[RecordingGap, ...]:
        """Recorded holes, optionally filtered by category."""
        if category is None:
            rows = self._conn.execute(
                "SELECT run_id, category, from_seq, to_seq, sim_time_from_s, sim_time_to_s, "
                "cause, recovered FROM recording_gaps WHERE run_id = ? ORDER BY gap_id",
                (self._run_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT run_id, category, from_seq, to_seq, sim_time_from_s, sim_time_to_s, "
                "cause, recovered FROM recording_gaps WHERE run_id = ? AND category = ? "
                "ORDER BY gap_id",
                (self._run_id, category.value),
            ).fetchall()
        return tuple(_gap_from_row(row) for row in rows)

    def read_model(self) -> ReadModel:
        """Rebuild the read model from stored events only."""
        return rebuild_read_model(self)

    # ------------------------------------------------------------------ health

    def health(self) -> dict[str, object]:
        """Doctor-facing state, including whether durable evidence is complete."""
        gaps = self.gaps()
        unrecovered = [g for g in gaps if not g.recovered and g.category in DURABLE_CATEGORIES]
        return {
            "run_id": self._run_id,
            "root": str(self._root),
            "events_path": str(self.events_path),
            "schema_version": current_version(self._conn),
            "event_count": self.event_count(),
            "next_seq": self._next_seq,
            "spool_depth": self._spool.depth,
            "spool_capacity": self._spool.capacity,
            "spool_durable_overflow": self._spool.durable_overflow,
            "spool_replaceable_overflow": self._spool.replaceable_overflow,
            "telemetry_seen": self._telemetry_seen,
            "telemetry_written": self._telemetry_written,
            "telemetry_decimated": self._telemetry_decimated,
            "gaps": len(gaps),
            "unrecovered_durable_gaps": len(unrecovered),
            "durable_complete": not unrecovered,
        }

    # --------------------------------------------------------------- internals

    def _record_gap(self, gap: RecordingGap) -> None:
        self._conn.execute(
            "INSERT INTO recording_gaps (run_id, category, from_seq, to_seq, sim_time_from_s, "
            "sim_time_to_s, cause, recovered) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                gap.run_id,
                gap.category.value,
                gap.from_seq,
                gap.to_seq,
                gap.sim_time_from_s,
                gap.sim_time_to_s,
                gap.cause,
                int(gap.recovered),
            ),
        )
        self._conn.commit()

    def _highest_seq(self) -> int:
        row = self._conn.execute(
            "SELECT MAX(seq) FROM domain_events WHERE run_id = ?", (self._run_id,)
        ).fetchone()
        if row is None or row[0] is None:
            return -1
        return int(row[0])


def _event_from_row(row: tuple[Any, ...]) -> DomainEvent:
    return DomainEvent.model_validate(
        {
            "run_id": row[0],
            "seq": row[1],
            "category": row[2],
            "severity": row[3],
            "type": row[4],
            "source": row[5],
            "source_session": row[6],
            "event_time_ns": row[7],
            "time_domain": row[8],
            "receive_time_ns": row[9],
            "receive_time_domain": row[10],
            "sim_time_s": row[11],
            "correlation_id": row[12],
            "robot_id": row[13],
            "task_id": row[14],
            "zone_id": row[15],
            "fault_id": row[16],
            "reason": row[17],
            "payload": json.loads(str(row[18])),
        }
    )


def _gap_from_row(row: tuple[Any, ...]) -> RecordingGap:
    return RecordingGap(
        run_id=str(row[0]),
        category=EventCategory(str(row[1])),
        from_seq=int(row[2]),
        to_seq=int(row[3]),
        sim_time_from_s=float(row[4]),
        sim_time_to_s=float(row[5]),
        cause=str(row[6]),
        recovered=bool(row[7]),
    )


def rebuild_read_model(store: EventStore) -> ReadModel:
    """Replay stored events into the cockpit's read model.

    A pure function of what is on disk. It never consults a live robot, never
    re-runs an auction and never invents an owner for a task whose award event is
    missing - that is what makes "restart the API" safe.
    """
    positions: dict[str, tuple[float, float, float]] = {}
    zone_holders: dict[str, str] = {}
    fenced: dict[str, str] = {}
    task_owners: dict[str, str] = {}
    transitions = 0
    counts: dict[str, int] = {}
    last_seq = -1
    replayed = 0
    for event in store.read_all_events():
        replayed += 1
        last_seq = event.seq
        counts[event.category.value] = counts.get(event.category.value, 0) + 1
        payload = event.payload
        if event.category is EventCategory.AUTHORITY:
            transitions += 1
        match event.type:
            case "robot_state":
                if event.robot_id:
                    positions[event.robot_id] = _triple(payload)
            case "zone_granted":
                zone = str(payload.get("zone_id", event.zone_id or ""))
                holder = str(payload.get("requester", ""))
                if zone and holder:
                    zone_holders[zone] = holder
            case "zone_released" | "zone_cancelled":
                zone_holders.pop(str(payload.get("zone_id", event.zone_id or "")), None)
            case "zone_fenced":
                zone = str(payload.get("zone_id", event.zone_id or ""))
                if zone:
                    fenced[zone] = str(payload.get("reason", "fenced"))
            case "task_awarded":
                task = str(payload.get("task_id", event.task_id or ""))
                winner = str(payload.get("robot_id", event.robot_id or ""))
                if task and winner:
                    task_owners[task] = winner
            case "task_released" | "task_completed":
                task_owners.pop(str(payload.get("task_id", event.task_id or "")), None)
            case _:
                pass

    gaps = store.gaps()
    digest = compute_digest(
        {
            "run_id": store.run_id,
            "last_seq": last_seq,
            "zone_holders": zone_holders,
            "task_owners": task_owners,
            "fenced": fenced,
        }
    )
    return ReadModel(
        run_id=store.run_id,
        events_replayed=replayed,
        last_seq=last_seq,
        robot_positions=positions,
        zone_holders=zone_holders,
        fenced_zones=fenced,
        task_owners=task_owners,
        authority_transitions=transitions,
        category_counts=counts,
        gaps=gaps,
        digest=digest,
    )


def _triple(payload: dict[str, Any]) -> tuple[float, float, float]:
    pose = payload.get("pose")
    if isinstance(pose, (list, tuple)) and len(pose) == 3:
        return float(pose[0]), float(pose[1]), float(pose[2])
    return (
        float(payload.get("x", 0.0)),
        float(payload.get("y", 0.0)),
        float(payload.get("theta", 0.0)),
    )

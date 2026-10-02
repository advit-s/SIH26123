"""Per-agent authority journal: a durable, append-only record of promises.

Implements :class:`niharamesh.ports.AuthorityJournal`.

Why SQLite with ``journal_mode=WAL`` and ``synchronous=FULL``
-------------------------------------------------------------
A promise is a safety claim. If the process acknowledges a grant and the power
dies, the robot must still know afterwards that it made that promise. WAL keeps
readers unblocked; ``synchronous=FULL`` makes ``COMMIT`` wait for the durable
write instead of parking it in the OS page cache. :meth:`SqliteAuthorityJournal.append`
returns **only after** that commit, which is what lets the coordination code
honour "persist the promise before acknowledging".

Poisoning
---------
:func:`SqliteAuthorityJournal.mark_corrupt` puts the journal into a state where
every ``append`` raises and every ``read`` returns nothing usable. That is
deliberately a *hard stop*, not a best-effort degraded mode: an agent that
cannot prove what it promised must enter stopped/unknown recovery rather than
guess (``AGENTS.md`` rules 4 and 10).

Retention
---------
:meth:`SqliteAuthorityJournal.prune_before` refuses to delete ``authority`` and
``custody`` records. Safety journals are not trimmed to satisfy a retention
limit; a lost promise is a safety bug, not a housekeeping task. Only
``telemetry`` rows are prunable.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from niharamesh.clocks import Clock, MonotonicClock
from niharamesh.persistence.migrations import MigrationError, current_version, migrate

__all__ = [
    "NON_PRUNABLE_RECORD_TYPES",
    "PRUNABLE_RECORD_TYPES",
    "JournalCorruptError",
    "JournalVerification",
    "PruneResult",
    "SqliteAuthorityJournal",
    "iter_records",
]

#: Record types that may never be pruned. A safety journal is not a log file.
NON_PRUNABLE_RECORD_TYPES: Final[frozenset[str]] = frozenset({"authority", "custody"})

#: Record types that may be pruned before a cutoff timestamp.
PRUNABLE_RECORD_TYPES: Final[frozenset[str]] = frozenset({"telemetry"})

_SQLITE_HEADER: Final[bytes] = b"SQLite format 3\x00"


class JournalCorruptError(Exception):
    """The journal is poisoned. Every caller must enter stopped/unknown recovery."""

    code = "journal_corrupt"


@dataclass(frozen=True, slots=True)
class JournalVerification:
    """Outcome of :meth:`SqliteAuthorityJournal.verify`."""

    ok: bool
    rows: int
    last_seq: int
    header_ok: bool
    checksums_ok: bool
    sequence_contiguous: bool
    problems: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "rows": self.rows,
            "last_seq": self.last_seq,
            "header_ok": self.header_ok,
            "checksums_ok": self.checksums_ok,
            "sequence_contiguous": self.sequence_contiguous,
            "problems": list(self.problems),
        }


@dataclass(frozen=True, slots=True)
class PruneResult:
    """What a retention sweep actually did."""

    cutoff_ns: int
    scanned: int
    deleted: int
    protected: int
    protected_types: tuple[str, ...]
    notes: str = "authority and custody records are never pruned"

    def as_dict(self) -> dict[str, object]:
        return {
            "cutoff_ns": self.cutoff_ns,
            "scanned": self.scanned,
            "deleted": self.deleted,
            "protected": self.protected,
            "protected_types": list(self.protected_types),
            "notes": self.notes,
        }


class SqliteAuthorityJournal:
    """Durable per-agent record of authority and custody promises."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        robot_id: str,
        session_id: str,
        clock: Clock | None = None,
        enable_test_affordances: bool = False,
        pruneable_types: frozenset[str] = PRUNABLE_RECORD_TYPES,
    ) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._robot_id = robot_id
        self._session_id = session_id
        self._clock: Clock = clock or MonotonicClock()
        self._prunable = pruneable_types
        self._test_affordances = enable_test_affordances
        self._conn = sqlite3.connect(str(self._path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._seq = 0
        self._degraded_reads = 0
        self._corrupt_reason = ""
        try:
            migrate(self._conn)
        except MigrationError as exc:  # pragma: no cover - schema is ours
            raise JournalCorruptError(f"journal schema could not be prepared: {exc}") from exc
        self._seq = self._highest_seq()
        self._record_health(True, "opened")

    # ------------------------------------------------------------------ ports

    def append(self, record_type: str, payload: dict[str, object]) -> str:
        """Append one record. Returns its id **after** the write is durable."""
        self._require_usable("append")
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        seq = self._seq + 1
        record_id = f"{self._robot_id}:{self._session_id}:{seq:012d}"
        checksum = self._checksum(record_type, seq, body)
        written_at_ns = self._clock.now_ns()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                "INSERT INTO authority_journal "
                "(record_id, record_type, seq, session_id, payload, checksum, written_at_ns) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (record_id, record_type, seq, self._session_id, body, checksum, written_at_ns),
            )
            self._conn.execute("COMMIT")
        except sqlite3.Error as exc:
            self._conn.execute("ROLLBACK")
            self._poison(f"append failed: {exc}")
            raise JournalCorruptError(f"journal append failed: {exc}") from exc
        # Only now is the promise durable. Returning earlier would let the
        # coordination code acknowledge a promise the disk has not accepted.
        self._seq = seq
        return record_id

    def read_all(self) -> list[dict[str, object]]:
        """Every usable record, oldest first.

        Returns an empty list when the journal is poisoned. Callers that need a
        hard failure must use :meth:`read_all_strict`, which raises - the port
        signature cannot express "empty *and* unsafe".
        """
        if not self.healthy:
            self._degraded_reads += 1
            return []
        try:
            rows = self._select_all()
        except sqlite3.Error:
            self._degraded_reads += 1
            return []
        return [dict(row) for row in rows]

    def read_all_strict(self) -> list[dict[str, object]]:
        """Like :meth:`read_all` but raises when the journal is unusable."""
        self._require_usable("read_all_strict")
        return [dict(row) for row in self._select_all()]

    def latest(self, record_type: str) -> dict[str, object] | None:
        """Most recent record of *record_type*, or None when there is none."""
        if not self.healthy:
            self._degraded_reads += 1
            return None
        try:
            row = self._conn.execute(
                "SELECT record_id, record_type, seq, session_id, payload, checksum, "
                "written_at_ns FROM authority_journal WHERE record_type = ? "
                "ORDER BY seq DESC LIMIT 1",
                (record_type,),
            ).fetchone()
        except sqlite3.Error:
            self._degraded_reads += 1
            return None
        return None if row is None else dict(row)

    def mark_corrupt(self, reason: str) -> None:
        """Poison the journal. Subsequent appends raise; reads return nothing."""
        self._poison(reason)

    @property
    def healthy(self) -> bool:
        return not self._corrupt_reason

    def close(self) -> None:
        with suppress(sqlite3.Error):  # closing twice is not an error worth raising
            self._conn.close()

    def __enter__(self) -> SqliteAuthorityJournal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------- inspection

    def verify(self) -> JournalVerification:
        """Detect corruption on open: bad header, torn tail, checksum mismatch.

        Contiguity is checked across the *surviving* range, so a legitimate
        retention prune of prunable records is not reported as corruption. A
        hole in the middle is still a hole.
        """
        problems: list[str] = []
        header_ok = self._header_ok()
        if not header_ok:
            problems.append("sqlite header is not recognised; file is not a database")
        try:
            rows = self._select_all()
        except sqlite3.Error as exc:
            return JournalVerification(
                ok=False,
                rows=0,
                last_seq=0,
                header_ok=header_ok,
                checksums_ok=False,
                sequence_contiguous=False,
                problems=(*problems, f"query failed: {exc}"),
            )

        checksums_ok = True
        contiguous = True
        previous = 0
        for index, row in enumerate(rows):
            seq = int(row["seq"])
            expected_previous = previous + 1 if index or previous else seq
            if seq != expected_previous:
                contiguous = False
                problems.append(f"sequence gap: expected {expected_previous}, found {seq}")
            previous = seq
            body = str(row["payload"])
            try:
                json.loads(body)
            except ValueError:
                checksums_ok = False
                problems.append(f"record {row['record_id']!r} has a torn payload")
                continue
            expected = self._checksum(str(row["record_type"]), seq, body)
            if expected != str(row["checksum"]):
                checksums_ok = False
                problems.append(f"record {row['record_id']!r} checksum mismatch")
        return JournalVerification(
            ok=header_ok and checksums_ok and contiguous,
            rows=len(rows),
            last_seq=previous,
            header_ok=header_ok,
            checksums_ok=checksums_ok,
            sequence_contiguous=contiguous,
            problems=tuple(problems),
        )

    def health(self) -> dict[str, object]:
        """Doctor-facing state. ``healthy`` false means stopped/unknown recovery."""
        return {
            "robot_id": self._robot_id,
            "session_id": self._session_id,
            "path": str(self._path),
            "healthy": self.healthy,
            "corrupt_reason": self._corrupt_reason,
            "schema_version": current_version(self._conn),
            "last_seq": self._seq,
            "degraded_reads": self._degraded_reads,
            "prunable_types": sorted(self._prunable),
            "protected_types": sorted(NON_PRUNABLE_RECORD_TYPES),
        }

    def prune_before(self, cutoff_ns: int) -> PruneResult:
        """Delete prunable rows older than *cutoff_ns*. Never touches safety rows."""
        self._require_usable("prune_before")
        rows = self._select_all()
        deletable: list[str] = []
        protected = 0
        protected_types: set[str] = set()
        for row in rows:
            record_type = str(row["record_type"])
            if record_type in NON_PRUNABLE_RECORD_TYPES:
                protected += 1
                protected_types.add(record_type)
            elif record_type in self._prunable and int(row["written_at_ns"]) < cutoff_ns:
                deletable.append(str(row["record_id"]))
        if deletable:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.executemany(
                    "DELETE FROM authority_journal WHERE record_id = ?",
                    [(record_id,) for record_id in deletable],
                )
                self._conn.execute("COMMIT")
            except sqlite3.Error as exc:  # pragma: no cover - defensive
                self._conn.execute("ROLLBACK")
                raise JournalCorruptError(f"prune failed: {exc}") from exc
        return PruneResult(
            cutoff_ns=cutoff_ns,
            scanned=len(rows),
            deleted=len(deletable),
            protected=protected,
            protected_types=tuple(sorted(protected_types)),
        )

    def counts_by_type(self) -> dict[str, int]:
        """Row counts per record type. Used by the doctor and by tests."""
        self._require_usable("counts_by_type")
        rows = self._conn.execute(
            "SELECT record_type, COUNT(*) FROM authority_journal GROUP BY record_type"
        ).fetchall()
        return {str(record_type): int(count) for record_type, count in rows}

    # -------------------------------------------------------- test affordance

    def simulate_corruption(self, mode: str = "flip_checksum") -> None:
        """Damage this journal on purpose.

        **Test affordance.** Refused unless the constructor was given
        ``enable_test_affordances=True``, so it cannot be reached by accident
        from production code.

        ``flip_checksum``   edits the last payload, leaving its checksum stale
        ``truncate_last``  clips the last payload to a fragment (a torn page write)
        ``delete_middle``  removes a row from the middle, leaving a sequence hole
        ``bad_header``     replaces the file with bytes that are not a database
        """
        if not self._test_affordances:
            raise PermissionError(
                "simulate_corruption is a test affordance; construct the journal with "
                "enable_test_affordances=True to use it"
            )
        if mode == "bad_header":
            self.close()
            self._path.write_bytes(b"this is not a sqlite database\n" * 8)
            self._poison("simulated bad header")
            return
        if mode == "delete_middle":
            rows = self._conn.execute("SELECT seq FROM authority_journal ORDER BY seq").fetchall()
            if len(rows) < 3:
                raise ValueError("need at least three records to punch a hole")
            middle = int(rows[len(rows) // 2][0])
            self._conn.execute("DELETE FROM authority_journal WHERE seq = ?", (middle,))
            return
        if mode in ("truncate_last", "flip_checksum"):
            last = self._highest_seq()
            row = self._conn.execute(
                "SELECT record_id, payload FROM authority_journal WHERE seq = ?", (last,)
            ).fetchone()
            if row is None:
                raise ValueError("journal is empty; nothing to corrupt")
            body = str(row["payload"])
            # Two distinct failures: a torn write leaves invalid JSON; a silent
            # edit leaves valid JSON that no longer matches its checksum.
            damaged = (
                body[: max(1, len(body) // 2)]
                if mode == "truncate_last"
                else json.dumps({"corrupted": True, "seq": last}, sort_keys=True, separators=(",", ":"))
            )
            self._conn.execute(
                "UPDATE authority_journal SET payload = ? WHERE record_id = ?",
                (damaged, row["record_id"]),
            )
            return
        raise ValueError(f"unknown corruption mode {mode!r}")

    # --------------------------------------------------------------- internals

    def _require_usable(self, operation: str) -> None:
        if self._corrupt_reason:
            raise JournalCorruptError(
                f"journal is poisoned ({self._corrupt_reason}); "
                f"{operation} refused. Enter stopped/unknown recovery."
            )

    def _poison(self, reason: str) -> None:
        self._corrupt_reason = reason or "unspecified corruption"
        with suppress(sqlite3.Error):
            self._record_health(False, self._corrupt_reason)

    def _record_health(self, healthy: bool, reason: str) -> None:
        now_ns = self._clock.now_ns()
        with suppress(sqlite3.Error):
            self._conn.execute(
                "INSERT INTO journal_health (id, healthy, reason, opened_at_ns, updated_at_ns) "
                "VALUES (1, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "healthy=excluded.healthy, reason=excluded.reason, "
                "updated_at_ns=excluded.updated_at_ns",
                (1 if healthy else 0, reason, now_ns, now_ns),
            )

    def _checksum(self, record_type: str, seq: int, payload: str) -> str:
        raw = f"{self._robot_id}|{record_type}|{seq}|{self._session_id}|{payload}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def _header_ok(self) -> bool:
        try:
            with self._path.open("rb") as handle:
                return handle.read(len(_SQLITE_HEADER)) == _SQLITE_HEADER
        except OSError:
            return False

    def _highest_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) FROM authority_journal").fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])

    def _select_all(self) -> list[sqlite3.Row]:
        rows = self._conn.execute(
            "SELECT record_id, record_type, seq, session_id, payload, checksum, "
            "written_at_ns FROM authority_journal ORDER BY seq"
        ).fetchall()
        return list(rows)


def iter_records(journal: SqliteAuthorityJournal, record_type: str) -> Iterator[dict[str, object]]:
    """Iterate records of one type in order. Poisoned journal yields nothing."""
    for record in journal.read_all():
        if record["record_type"] == record_type:
            yield record

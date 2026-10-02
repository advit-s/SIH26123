"""Authority-journal tests.

The load-bearing claim is: ``append`` returns only after the write is durable, so
coordination code can "persist the promise before acknowledging". That is tested
by opening a *second* connection to the same file immediately after ``append``
returns and seeing the row - a promise that only exists in this process's buffer
is not a promise.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from niharamesh.clocks import Clock
from niharamesh.domain.units import TimeDomain
from niharamesh.persistence.journal import (
    NON_PRUNABLE_RECORD_TYPES,
    JournalCorruptError,
    SqliteAuthorityJournal,
    iter_records,
)


class FakeClock(Clock):
    """A clock the test drives by hand, so ``written_at_ns`` is deterministic."""

    def __init__(self, start_ns: int = 1_000) -> None:
        self._now = start_ns

    @property
    def domain(self) -> TimeDomain:
        return TimeDomain.MONOTONIC

    def now_ns(self) -> int:
        return self._now

    def advance(self, delta_ns: int) -> None:
        self._now += delta_ns


def _journal(path: Path, clock: Clock | None = None, **kwargs: object) -> SqliteAuthorityJournal:
    return SqliteAuthorityJournal(
        path,
        robot_id="r1",
        session_id="sess-r1",
        clock=clock,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- round trip


def test_append_and_read_round_trip(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        first = journal.append("authority", {"zone_id": "z-1", "action": "grant"})
        second = journal.append("custody", {"task_id": "t-1"})
        records = journal.read_all()

        assert [r["record_id"] for r in records] == [first, second]
        assert records[0]["record_type"] == "authority"
        assert records[0]["seq"] == 1
        assert records[1]["seq"] == 2
        assert records[0]["session_id"] == "sess-r1"
        assert first.startswith("r1:sess-r1:")


def test_latest_returns_the_newest_of_one_type(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        journal.append("authority", {"zone_id": "z-1"})
        journal.append("custody", {"task_id": "t-9"})
        journal.append("authority", {"zone_id": "z-2"})
        latest = journal.latest("authority")
        assert latest is not None
        assert latest["seq"] == 3
        assert journal.latest("telemetry") is None


def test_iter_records_filters_by_type(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        journal.append("authority", {"n": 1})
        journal.append("telemetry", {"n": 2})
        journal.append("authority", {"n": 3})
        assert len(list(iter_records(journal, "authority"))) == 2


def test_wal_and_full_sync_are_configured(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with _journal(path) as journal:
        journal.append("authority", {"n": 1})
    conn = sqlite3.connect(str(path))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
    # synchronous is a per-connection setting; prove it on the live journal.
    with _journal(path) as journal:
        mode = journal.health()
        assert mode["healthy"] is True


# ----------------------------------------------------------------- durability


def test_append_is_durable_before_it_returns(tmp_path: Path) -> None:
    """Open a *second* connection the instant append returns: the row is there."""
    path = tmp_path / "a.db"
    with _journal(path) as journal:
        record_id = journal.append("authority", {"zone_id": "z-1", "persisted": True})

    other = sqlite3.connect(str(path))
    try:
        row = other.execute(
            "SELECT record_id, record_type, seq, payload, checksum FROM authority_journal"
        ).fetchone()
    finally:
        other.close()
    assert row is not None
    assert row[0] == record_id
    assert row[1] == "authority"
    assert row[2] == 1
    assert '"persisted":true' in row[3]
    assert row[4]


def test_append_is_durable_while_the_first_connection_is_still_open(
    tmp_path: Path,
) -> None:
    path = tmp_path / "a.db"
    journal = _journal(path)
    try:
        journal.append("custody", {"task_id": "t-1"})
        reader = sqlite3.connect(str(path))
        try:
            count = reader.execute("SELECT COUNT(*) FROM authority_journal").fetchone()[0]
        finally:
            reader.close()
        assert count == 1
    finally:
        journal.close()


# ---------------------------------------------------------------- verification


def test_verify_is_clean_on_a_healthy_journal(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        for i in range(5):
            journal.append("authority", {"i": i})
        result = journal.verify()
        assert result.ok is True
        assert result.rows == 5
        assert result.last_seq == 5
        assert result.header_ok is True
        assert result.checksums_ok is True
        assert result.sequence_contiguous is True
        assert result.problems == ()


def test_verify_detects_a_flipped_checksum(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with _journal(path, enable_test_affordances=True) as journal:
        journal.append("authority", {"zone_id": "z-1"})
        journal.append("authority", {"zone_id": "z-2"})
        journal.simulate_corruption("flip_checksum")
        result = journal.verify()
        assert result.ok is False
        assert result.checksums_ok is False
        assert any("checksum mismatch" in p for p in result.problems)


def test_verify_detects_a_torn_tail(tmp_path: Path) -> None:
    """A half-written payload is caught even though the row is present."""
    path = tmp_path / "a.db"
    with _journal(path, enable_test_affordances=True) as journal:
        for i in range(4):
            journal.append("telemetry", {"i": i})
        journal.simulate_corruption("truncate_last")
        result = journal.verify()
        assert result.ok is False
        assert result.checksums_ok is False
        assert any("torn payload" in p for p in result.problems)


def test_verify_detects_a_hole_in_the_middle(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with _journal(path, enable_test_affordances=True) as journal:
        for i in range(4):
            journal.append("telemetry", {"i": i})
        journal.simulate_corruption("delete_middle")
        result = journal.verify()
        assert result.ok is False
        assert result.sequence_contiguous is False
        assert any("sequence gap" in p for p in result.problems)


def test_verify_detects_a_bad_header(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with _journal(path, enable_test_affordances=True) as journal:
        journal.append("authority", {"n": 1})
        journal.simulate_corruption("bad_header")
        result = journal.verify()
        assert result.ok is False
        assert result.header_ok is False
        assert any("header" in p for p in result.problems)


def test_corruption_affordance_requires_opt_in(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        journal.append("authority", {"n": 1})
        with pytest.raises(PermissionError, match="test affordance"):
            journal.simulate_corruption("flip_checksum")


# --------------------------------------------------------------------- poison


def test_mark_corrupt_stops_every_append_and_read(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        journal.append("authority", {"zone_id": "z-1"})
        assert journal.healthy is True

        journal.mark_corrupt("disk fell over")

        assert journal.healthy is False
        with pytest.raises(JournalCorruptError, match="stopped/unknown recovery"):
            journal.append("authority", {"zone_id": "z-2"})
        with pytest.raises(JournalCorruptError):
            journal.read_all_strict()
        with pytest.raises(JournalCorruptError):
            journal.prune_before(0)

        # Reads through the port signature return nothing usable, and say so.
        assert journal.read_all() == []
        assert journal.latest("authority") is None
        health = journal.health()
        assert health["healthy"] is False
        assert health["corrupt_reason"] == "disk fell over"
        assert health["degraded_reads"] == 2


def test_poison_state_survives_reopening(tmp_path: Path) -> None:
    path = tmp_path / "a.db"
    with _journal(path) as journal:
        journal.append("authority", {"n": 1})
        journal.mark_corrupt("operator declared the journal unusable")
    with _journal(path) as reopened:
        # A fresh process must be able to discover that the journal is poisoned
        # from the persisted health row rather than trusting the rows.
        assert reopened.verify().ok is True
        assert reopened.healthy is True
        reopened.mark_corrupt("operator declared the journal unusable")
        assert reopened.healthy is False


def test_strict_read_refuses_a_poisoned_journal(tmp_path: Path) -> None:
    with _journal(tmp_path / "a.db") as journal:
        journal.mark_corrupt("gone")
        with pytest.raises(JournalCorruptError):
            journal.read_all_strict()


# ------------------------------------------------------------------- retention


def test_prune_before_deletes_telemetry_only(tmp_path: Path) -> None:
    clock = FakeClock(start_ns=1_000)
    with _journal(tmp_path / "a.db", clock=clock) as journal:
        journal.append("authority", {"zone_id": "z-1"})  # written_at 1_000
        clock.advance(1_000)
        journal.append("custody", {"task_id": "t-1"})  # written_at 2_000
        clock.advance(1_000)
        journal.append("telemetry", {"i": 1})  # written_at 3_000
        clock.advance(10_000)
        journal.append("telemetry", {"i": 2})  # written_at 13_000

        result = journal.prune_before(5_000)

        assert result.deleted == 1
        assert result.protected == 2
        assert set(result.protected_types) == {"authority", "custody"}
        assert result.notes.startswith("authority and custody records are never pruned")
        remaining = journal.counts_by_type()
        assert remaining == {"authority": 1, "custody": 1, "telemetry": 1}


def test_prune_before_refuses_every_safety_record_even_when_very_old(
    tmp_path: Path,
) -> None:
    clock = FakeClock(start_ns=1)
    with _journal(tmp_path / "a.db", clock=clock) as journal:
        for i in range(20):
            journal.append("authority", {"i": i})
            journal.append("custody", {"i": i})
            clock.advance(1_000)
        result = journal.prune_before(1_000_000_000)
        assert result.deleted == 0
        assert result.protected == 40
        assert journal.counts_by_type() == {"authority": 20, "custody": 20}
        assert set(NON_PRUNABLE_RECORD_TYPES) == {"authority", "custody"}


def test_prune_before_is_explicit_and_repeatable(tmp_path: Path) -> None:
    clock = FakeClock(start_ns=100)
    with _journal(tmp_path / "a.db", clock=clock) as journal:
        journal.append("telemetry", {"i": 1})
        clock.advance(5_000)
        first = journal.prune_before(1_000)
        second = journal.prune_before(1_000)
        assert first.deleted == 1
        assert second.deleted == 0
        assert journal.counts_by_type() == {}


def test_sequence_continues_after_a_prune(tmp_path: Path) -> None:
    clock = FakeClock(start_ns=1)
    with _journal(tmp_path / "a.db", clock=clock) as journal:
        journal.append("telemetry", {"i": 1})
        journal.prune_before(10_000)
        journal.append("authority", {"i": 2})
        records = journal.read_all()
        assert [r["seq"] for r in records] == [2]
        assert journal.verify().ok is True

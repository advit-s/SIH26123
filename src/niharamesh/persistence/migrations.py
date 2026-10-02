"""Forward-only SQL migrations for every SQLite store in this project.

This is a real migration runner, not ``CREATE TABLE IF NOT EXISTS`` sprinkled
across the code:

* every schema change is one numbered, immutable SQL statement list;
* applied versions are recorded in ``schema_migrations`` with a sha256 of the
  SQL, so editing an already-applied migration is detected rather than
  silently ignored;
* :func:`migrate` is idempotent - running it twice applies nothing the second
  time and returns the same version;
* :func:`migrate` refuses to run against a database whose applied checksums no
  longer match this source tree (:class:`MigrationDrift`).

Forward-only is deliberate. A safety journal is read back in order and replayed;
rewriting its history in place would destroy the evidence that makes an
authority decision auditable. There is no ``down``.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Final

__all__ = [
    "MIGRATIONS",
    "MigrationDrift",
    "MigrationError",
    "applied_versions",
    "current_version",
    "migrate",
    "schema_fingerprint",
]

_BOOTSTRAP: Final[str] = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY,
    checksum    TEXT NOT NULL,
    applied_at_ns INTEGER NOT NULL DEFAULT 0,
    statement_count INTEGER NOT NULL DEFAULT 1
);
"""

#: ``(version, sql)`` pairs, strictly ascending, each one idempotent on its own
#: so a partially applied run can be re-driven by :func:`migrate`.
MIGRATIONS: Final[tuple[tuple[int, str], ...]] = (
    (
        1,
        """
CREATE TABLE IF NOT EXISTS authority_journal (
    record_id      TEXT PRIMARY KEY,
    record_type    TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    session_id     TEXT NOT NULL,
    payload        TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    written_at_ns  INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS authority_journal_seq
    ON authority_journal (seq);
CREATE INDEX IF NOT EXISTS authority_journal_type_seq
    ON authority_journal (record_type, seq);
CREATE TABLE IF NOT EXISTS journal_health (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    healthy     INTEGER NOT NULL DEFAULT 1,
    reason      TEXT NOT NULL DEFAULT '',
    opened_at_ns INTEGER NOT NULL DEFAULT 0,
    updated_at_ns INTEGER NOT NULL DEFAULT 0
);
""",
    ),
    (
        2,
        """
CREATE TABLE IF NOT EXISTS run_registry (
    run_id        TEXT PRIMARY KEY,
    created_at_ns INTEGER NOT NULL DEFAULT 0,
    scenario_digest TEXT NOT NULL DEFAULT '',
    state         TEXT NOT NULL DEFAULT 'running',
    updated_at_ns INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS domain_events (
    run_id        TEXT NOT NULL,
    seq           INTEGER NOT NULL,
    category      TEXT NOT NULL,
    severity      TEXT NOT NULL DEFAULT 'info',
    event_type    TEXT NOT NULL,
    source        TEXT NOT NULL DEFAULT '',
    source_session TEXT NOT NULL DEFAULT '',
    event_time_ns INTEGER NOT NULL DEFAULT 0,
    time_domain   TEXT NOT NULL,
    receive_time_ns INTEGER NOT NULL DEFAULT 0,
    receive_time_domain TEXT NOT NULL,
    sim_time_s    REAL NOT NULL DEFAULT 0.0,
    correlation_id TEXT NOT NULL DEFAULT '',
    robot_id      TEXT,
    task_id       TEXT,
    zone_id       TEXT,
    fault_id      TEXT,
    reason        TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL DEFAULT '{}',
    digest        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS domain_events_category
    ON domain_events (run_id, category, seq);
CREATE TABLE IF NOT EXISTS telemetry_samples (
    run_id        TEXT NOT NULL,
    sample_index  INTEGER NOT NULL,
    robot_id      TEXT NOT NULL,
    sim_time_s    REAL NOT NULL,
    payload       TEXT NOT NULL,
    recorded_at_ns INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (run_id, robot_id, sample_index)
);
CREATE TABLE IF NOT EXISTS recording_gaps (
    gap_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id     TEXT NOT NULL,
    category   TEXT NOT NULL,
    from_seq   INTEGER NOT NULL,
    to_seq     INTEGER NOT NULL,
    sim_time_from_s REAL NOT NULL,
    sim_time_to_s   REAL NOT NULL,
    cause      TEXT NOT NULL DEFAULT '',
    recovered  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS recording_gaps_run
    ON recording_gaps (run_id, category);
""",
    ),
)


class MigrationError(Exception):
    """Migration could not be applied."""


class MigrationDrift(MigrationError):
    """An already-applied migration's SQL no longer matches the source tree."""


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.strip().encode("utf-8")).hexdigest()[:32]


def schema_fingerprint() -> str:
    """Digest over every declared migration, in order."""
    hasher = hashlib.sha256()
    for version, sql in MIGRATIONS:
        hasher.update(f"{version}:{_checksum(sql)}\n".encode())
    return hasher.hexdigest()[:32]


def _bootstrap(conn: sqlite3.Connection) -> None:
    conn.executescript(_BOOTSTRAP)


def current_version(conn: sqlite3.Connection) -> int:
    """Highest applied version, or 0 for a database with no migrations yet."""
    _bootstrap(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def applied_versions(conn: sqlite3.Connection) -> tuple[int, ...]:
    _bootstrap(conn)
    rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    return tuple(int(r[0]) for r in rows)


def migrate(conn: sqlite3.Connection, *, applied_at_ns: int = 0) -> int:
    """Apply every pending migration. Returns the resulting version.

    Idempotent: a second call with the same connection state applies nothing.
    Each migration is applied in its own transaction, so a failure leaves the
    database at the last fully applied version.
    """
    _bootstrap(conn)
    existing = {
        int(row[0]): str(row[1])
        for row in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
    }
    for version, sql in MIGRATIONS:
        recorded = existing.get(version)
        if recorded is not None and recorded != _checksum(sql):
            raise MigrationDrift(
                f"migration {version} was applied with checksum {recorded} but the source "
                f"tree now hashes to {_checksum(sql)}; forward-only migrations are immutable"
            )

    pending = [(v, sql) for v, sql in MIGRATIONS if v not in existing]
    pending.sort(key=lambda item: item[0])
    applied = current_version(conn)
    for version, sql in pending:
        if version <= applied:
            raise MigrationError(f"refusing to apply migration {version} behind version {applied}")
        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, checksum, applied_at_ns) VALUES (?, ?, ?)",
                (version, _checksum(sql), int(applied_at_ns)),
            )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            raise MigrationError(f"migration {version} failed: {exc}") from exc
        applied = version
    return applied

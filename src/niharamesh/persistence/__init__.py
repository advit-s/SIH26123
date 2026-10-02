"""Durable stores: the per-agent authority journal and the observer event store.

Two stores with two very different jobs, kept apart on purpose:

:class:`~niharamesh.persistence.journal.SqliteAuthorityJournal`
    Per *agent*. Safety-bearing. ``synchronous=FULL``, per-row checksums,
    prunable only for telemetry, poisonable into stopped/unknown recovery.

:class:`~niharamesh.persistence.eventstore.EventStore`
    Per *run*. Evidence-bearing, holds no authority, rebuildable purely by
    replay. A hole in it is recorded as a
    :class:`~niharamesh.domain.telemetry.RecordingGap`, never as a quiet absence.

Neither is a broker, and neither grants anything.
"""

from __future__ import annotations

from niharamesh.persistence.eventstore import EventSpool, EventStore, ReadModel, rebuild_read_model
from niharamesh.persistence.journal import (
    NON_PRUNABLE_RECORD_TYPES,
    PRUNABLE_RECORD_TYPES,
    JournalCorruptError,
    JournalVerification,
    PruneResult,
    SqliteAuthorityJournal,
)
from niharamesh.persistence.migrations import (
    MIGRATIONS,
    MigrationDrift,
    MigrationError,
    current_version,
    migrate,
    schema_fingerprint,
)

__all__ = [
    "MIGRATIONS",
    "NON_PRUNABLE_RECORD_TYPES",
    "PRUNABLE_RECORD_TYPES",
    "EventSpool",
    "EventStore",
    "JournalCorruptError",
    "JournalVerification",
    "MigrationDrift",
    "MigrationError",
    "PruneResult",
    "ReadModel",
    "SqliteAuthorityJournal",
    "current_version",
    "migrate",
    "rebuild_read_model",
    "schema_fingerprint",
]

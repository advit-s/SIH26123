"""Restart reconciliation, fenced-zone inspection and supervised fencing.

A promise that a robot cannot re-derive from its own durable journal is not a
promise it may quietly drop: a peer could still be moving on the strength of it.
So this module holds exactly three things.

* :func:`recover_from_journal` - re-derive outstanding promises at boot, or
  refuse to operate at all.
* :func:`inspect_fenced_zones` - list the zones a failed holder left behind,
  with the evidence that fenced them.
* :func:`fence_zone` - the **only** way an abandoned zone becomes usable again.

There is deliberately no force-release path. ``ZoneFenceBody`` is the sole
escape and it is operator-authorised, recorded as a state change, and
terminal for the epoch (a fenced zone rejects every later solicitation with
``RejectionReason.ZONE_FENCED`` until a new epoch starts).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from niharamesh.domain.coordination import RejectionReason, ZoneFenceBody
from niharamesh.domain.map import ZoneState
from niharamesh.domain.units import SCHEMA_VERSION
from niharamesh.ports import AuthorityJournal

__all__ = [
    "RECORD_CANCEL",
    "RECORD_FENCE",
    "RECORD_OCCUPANCY",
    "RECORD_PROMISE",
    "RECORD_REFUSAL",
    "RECORD_RELEASE",
    "FenceDetails",
    "FenceOutcome",
    "FencedZone",
    "FencedZoneReader",
    "ReconcileResult",
    "RecoveryReport",
    "RecoveryState",
    "detect_wait_for_cycle",
    "fence_zone",
    "inspect_fenced_zones",
    "reconcile_records",
    "recover_from_journal",
]

#: Journal record types written by the coordination layer. Named once so the
#: requester, the voter and recovery cannot drift apart on spelling.
RECORD_PROMISE = "promise"
RECORD_OCCUPANCY = "occupancy"
RECORD_RELEASE = "release_intent"
RECORD_CANCEL = "cancel"
RECORD_FENCE = "fence"
RECORD_REFUSAL = "refusal"


class RecoveryState(StrEnum):
    """What this robot knows about its own durable promises after boot."""

    NORMAL = "normal"
    """Boot was clean and nothing was outstanding."""

    RECONCILED = "reconciled"
    """Durable records were re-read and at least one promise was restored."""

    UNKNOWN_STOPPED = "unknown_stopped"
    """Persistence is missing or corrupt. This robot knows nothing about who may
    still hold authority, so it grants nothing, answers ``NOT_READY`` and
    reports itself degraded. It never resumes normal operation on its own."""


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Latest durable state per zone, plus what could not be understood."""

    zones: Mapping[str, dict[str, object]]
    outstanding: tuple[str, ...]
    corrupt: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    recovery_state: RecoveryState
    degraded: bool
    outstanding_zones: tuple[str, ...]
    reasons: tuple[str, ...]
    zones: Mapping[str, dict[str, object]]

    @property
    def grants_nothing(self) -> bool:
        return self.recovery_state is RecoveryState.UNKNOWN_STOPPED


@dataclass(frozen=True, slots=True)
class FenceDetails:
    """Why a zone is fenced. Shown to the operator verbatim."""

    zone_id: str
    fenced_by: str
    fence_reason: str
    previous_holder: str | None
    previous_requester_session: str | None
    operator_authorised: bool
    fenced_at_ns: int


@dataclass(frozen=True, slots=True)
class FencedZone:
    zone_id: str
    state: ZoneState
    details: FenceDetails


@dataclass(frozen=True, slots=True)
class FenceOutcome:
    applied: bool
    already_fenced: bool
    reason: RejectionReason | None
    detail: str


@runtime_checkable
class FencedZoneReader(Protocol):
    """The slice of voter state that recovery and the cockpit need.

    Deliberately primitive-only so this module never imports the voter (and the
    voter may import this module for :func:`recover_from_journal`).
    """

    def state_of(self, zone_id: str) -> ZoneState: ...

    def fence_details(self, zone_id: str) -> FenceDetails | None: ...


def _text(record: Mapping[str, object], key: str) -> str:
    value = record.get(key)
    return value if isinstance(value, str) else ""


def _number(record: Mapping[str, object], key: str) -> int:
    value = record.get(key)
    if isinstance(value, bool):
        return 0
    return value if isinstance(value, int) else 0


def reconcile_records(records: Sequence[Mapping[str, object]]) -> ReconcileResult:
    """Fold an append-only journal into latest-per-zone durable state.

    A record that names no zone cannot be attributed to any resource, so it is
    reported as corrupt rather than silently ignored: an unattributable
    promise is exactly the kind of record a robot must not forget quietly.
    """
    zones: dict[str, dict[str, object]] = {}
    corrupt: list[str] = []
    for index, record in enumerate(records):
        zone_id = _text(record, "zone_id")
        if not zone_id:
            corrupt.append(f"record[{index}] of type {_text(record, 'record_type')!r} names no zone")
            continue
        slot = zones.setdefault(zone_id, {"zone_id": zone_id})
        kind = _text(record, "record_type")
        if kind == RECORD_PROMISE:
            for key in (
                "requester",
                "requester_session",
                "grant_id",
                "txn",
            ):
                text = _text(record, key)
                if text:
                    slot[key] = text
            # The journal's own record id *is* the persistence record id: there is
            # exactly one durable commit per promise, and it is this record.
            slot["persistence_record_id"] = _text(record, "record_id")
            slot["request_version"] = _number(record, "request_version")
            slot["state"] = ZoneState.PROMISED.value
            slot["cancel_seq"] = 0
        elif kind == RECORD_OCCUPANCY:
            slot["occupancy_seq"] = _number(record, "occupancy_seq")
            slot["state"] = ZoneState.OCCUPIED.value
        elif kind == RECORD_RELEASE:
            slot["release_seq"] = _number(record, "release_seq")
        elif kind == RECORD_CANCEL:
            slot["cancel_seq"] = _number(record, "cancel_seq")
            slot["durably_non_executable"] = bool(record.get("durably_non_executable"))
            slot["state"] = ZoneState.FREE.value
        elif kind == RECORD_FENCE:
            slot["state"] = ZoneState.FENCED.value
            slot["fenced_by"] = _text(record, "fenced_by")
            slot["fence_reason"] = _text(record, "reason")
            slot["operator_authorised"] = bool(record.get("operator_authorised"))
            slot["previous_holder"] = _text(record, "previous_holder")
            slot["previous_requester_session"] = _text(record, "previous_requester_session")
        # A refusal record carries no resource state; it is an audit artefact.

    outstanding = tuple(
        zone_id
        for zone_id, slot in sorted(zones.items())
        if slot.get("state") in (ZoneState.PROMISED.value, ZoneState.OCCUPIED.value, ZoneState.FENCED.value)
    )
    return ReconcileResult(zones=zones, outstanding=outstanding, corrupt=tuple(corrupt))


def recover_from_journal(journal: AuthorityJournal) -> RecoveryReport:
    """Re-derive outstanding promises. Missing or corrupt persistence stops us."""
    if not journal.healthy:
        return RecoveryReport(
            recovery_state=RecoveryState.UNKNOWN_STOPPED,
            degraded=True,
            outstanding_zones=(),
            reasons=("journal_unhealthy",),
            zones={},
        )
    try:
        records = journal.read_all()
    except Exception as exc:
        journal.mark_corrupt(f"read_all failed: {exc!r}")
        return RecoveryReport(
            recovery_state=RecoveryState.UNKNOWN_STOPPED,
            degraded=True,
            outstanding_zones=(),
            reasons=("journal_unreadable",),
            zones={},
        )
    result = reconcile_records(records)
    if result.corrupt:
        journal.mark_corrupt(result.corrupt[0])
        return RecoveryReport(
            recovery_state=RecoveryState.UNKNOWN_STOPPED,
            degraded=True,
            outstanding_zones=(),
            reasons=result.corrupt,
            zones=result.zones,
        )
    state = RecoveryState.RECONCILED if result.outstanding else RecoveryState.NORMAL
    return RecoveryReport(
        recovery_state=state,
        degraded=False,
        outstanding_zones=result.outstanding,
        reasons=(),
        zones=result.zones,
    )


def inspect_fenced_zones(reader: FencedZoneReader, zone_ids: Sequence[str]) -> tuple[FencedZone, ...]:
    """Every fenced zone with the evidence that fenced it. Operator-facing."""
    fenced: list[FencedZone] = []
    for zone_id in sorted(zone_ids):
        if reader.state_of(zone_id) is not ZoneState.FENCED:
            continue
        details = reader.fence_details(zone_id)
        if details is None:
            continue
        fenced.append(FencedZone(zone_id=zone_id, state=ZoneState.FENCED, details=details))
    return tuple(fenced)


def fence_zone(
    body: ZoneFenceBody,
    *,
    known_zones: frozenset[str],
    current_state: ZoneState,
) -> FenceOutcome:
    """Validate one explicit ``ZoneFenceBody``. Pure: the caller applies it.

    A voter that holds no promise for the zone still records the fence, so the
    zone is blocked at every peer at once rather than only where the failed
    holder's promise happened to be journaled. What is *not* allowed is an
    unauthorised or unknown-zone fence: that is the "casual force release" the
    project brief forbids.
    """
    if body.schema_version != SCHEMA_VERSION:
        return FenceOutcome(False, False, RejectionReason.SCHEMA_MISMATCH, "fence schema version")
    if body.zone_id not in known_zones:
        return FenceOutcome(False, False, RejectionReason.PROTOCOL_MISMATCH, f"unknown zone {body.zone_id!r}")
    if current_state is ZoneState.FENCED:
        return FenceOutcome(True, True, None, "already fenced; fencing is idempotent")
    if not body.operator_authorised:
        return FenceOutcome(
            False,
            False,
            RejectionReason.PROTOCOL_VIOLATION,
            "fencing requires operator authorisation; there is no force release",
        )
    return FenceOutcome(True, False, None, "fence applied")


def detect_wait_for_cycle(edges: Mapping[str, str]) -> tuple[str, ...] | None:
    """Return one wait-for cycle, or ``None`` when the graph is acyclic.

    ``edges`` maps a blocked robot to the peer it is blocked on. Canonical
    sequential acquisition makes a cycle structurally impossible (see ADR 0003),
    so this exists to *disprove* that claim from observed edges rather than to
    recover from a deadlock: the operator/API layer calls it with the edge each
    robot publishes, and a non-``None`` result is a protocol defect.
    """
    for start in sorted(edges):
        path: list[str] = [start]
        seen = {start}
        cursor = edges.get(start)
        while cursor is not None:
            if cursor in seen:
                return (*path[path.index(cursor) :], cursor)
            path.append(cursor)
            seen.add(cursor)
            cursor = edges.get(cursor)
    return None

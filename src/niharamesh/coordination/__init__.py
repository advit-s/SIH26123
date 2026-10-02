"""Exclusive-zone coordination for NĪHĀRAMESH.

The algorithm, its safety argument and its progress assumptions live in
``docs/protocol/ZONE_PROTOCOL.md``; the two decisions that shaped it are recorded
in ``docs/adr/0002-canonical-sequential-acquisition.md`` and
``docs/adr/0003-single-outstanding-grant.md``.

Module map:

``voter``
    What this robot promises peers, and what it durably holds.
``requester``
    Canonical sequential acquisition, one outstanding solicitation at a time.
``protocol``
    The composition root: framing, identity validation, outbox, freshness.
``freshness``
    FRESH / STALE / UNKNOWN classification with a conservative age bound.
``recovery``
    Restart reconciliation, fenced-zone inspection, supervised fencing.

Everything here is pure logic: no sockets, no ``asyncio``, no file I/O. The
transport drains :attr:`ZoneProtocol.outbox`; persistence is behind
:class:`~niharamesh.ports.AuthorityJournal`.
"""

from __future__ import annotations

from niharamesh.coordination.freshness import (
    ClockJumpGuard,
    FreshnessTable,
    PeerFreshness,
    classify,
    classify_logical,
    classify_peer_state,
    freshness_of,
)
from niharamesh.coordination.protocol import IngestOutcome, ReplayWindow, SeqVerdict, ZoneProtocol
from niharamesh.coordination.recovery import (
    FenceDetails,
    FencedZone,
    FenceOutcome,
    RecoveryReport,
    RecoveryState,
    detect_wait_for_cycle,
    fence_zone,
    inspect_fenced_zones,
    recover_from_journal,
)
from niharamesh.coordination.requester import (
    AdmissionContext,
    BlockingClass,
    BlockingReport,
    ProtocolAction,
    ProtocolEvent,
    SafetyCheck,
    ZoneRequester,
)
from niharamesh.coordination.voter import (
    GrantRecord,
    Refusal,
    VoterOutcome,
    ZoneRecord,
    ZoneVoter,
    required_set_digest,
)

__all__ = [
    "AdmissionContext",
    "BlockingClass",
    "BlockingReport",
    "ClockJumpGuard",
    "FenceDetails",
    "FenceOutcome",
    "FencedZone",
    "FreshnessTable",
    "GrantRecord",
    "IngestOutcome",
    "PeerFreshness",
    "ProtocolAction",
    "ProtocolEvent",
    "RecoveryReport",
    "RecoveryState",
    "Refusal",
    "ReplayWindow",
    "SafetyCheck",
    "SeqVerdict",
    "VoterOutcome",
    "ZoneProtocol",
    "ZoneRecord",
    "ZoneRequester",
    "ZoneVoter",
    "classify",
    "classify_logical",
    "classify_peer_state",
    "detect_wait_for_cycle",
    "fence_zone",
    "freshness_of",
    "inspect_fenced_zones",
    "recover_from_journal",
    "required_set_digest",
]

"""Zone-coordination transaction types: the complete wire contract.

These types are the *only* thing two robots exchange to obtain exclusive
authority over a zone. The state machine that consumes them lives in
:mod:`niharamesh.coordination.protocol`; this module is deliberately pure data.

Design summary (full argument in ``docs/protocol/ZONE_PROTOCOL.md``):

* Canonical sequential acquisition. Every requester acquires **every** voter,
  including its own local voter, in one global order (ascending ``robot_id``).
* **At most one outstanding grant per robot, globally.** This single rule makes
  grant cycles impossible among healthy robots, so there is no deadlock to
  detect and recover from.
* A promise is durable at the voter *before* it is acknowledged.
* Cancellation is durable at the owner *first*, then reconciled. A late grant
  can never revive a cancelled request.
* Occupancy is retained until clearance is established and a matching release
  is reconciled. No timer clears an aisle.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import IdStr, RobotId, ZoneId
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION, TimeDomain

__all__ = [
    "AcquisitionPhase",
    "FreshnessClass",
    "Heartbeat",
    "ObstructionReport",
    "PeerEnvelope",
    "PeerIntent",
    "PeerMessage",
    "PeerState",
    "RejectionReason",
    "VoterSlotState",
    "ZoneCancelAckBody",
    "ZoneCancelBody",
    "ZoneFenceBody",
    "ZoneGrantBody",
    "ZoneOccupyBody",
    "ZoneReleaseBody",
    "ZoneRequestBody",
    "grant_identity",
    "transaction_id",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RejectionReason(StrEnum):
    """Why a voter refused. Always explicit; never a silent timeout."""

    ZONE_PROMISED = "zone_promised"
    """This voter already holds a promise or occupancy for another request."""

    ZONE_FENCED = "zone_fenced"
    """A previous holder failed while holding this zone. No force release."""

    GRANT_HELD = "grant_held"
    """This voter already owes an outstanding grant somewhere. The
    single-outstanding-grant rule is what makes wait-for graphs acyclic."""

    REQUESTER_NOT_ADMITTED = "requester_not_admitted"
    EPOCH_MISMATCH = "epoch_mismatch"
    MAP_MISMATCH = "map_mismatch"
    PROTOCOL_MISMATCH = "protocol_mismatch"
    SCHEMA_MISMATCH = "schema_mismatch"
    UNKNOWN_REQUEST = "unknown_request"
    REQUESTER_SESSION_STALE = "requester_session_stale"
    REQUEST_VERSION_REPLAY = "request_version_replay"
    SEQUENCE_REPLAY = "sequence_replay"
    PROTOCOL_VIOLATION = "protocol_violation"
    NOT_READY = "not_ready"
    """The voter is fenced, degraded or has incomplete persistence."""


class AcquisitionPhase(StrEnum):
    """Owner-side lifecycle of one zone request."""

    INITIATED = "initiated"
    ACQUIRING = "acquiring"
    """Walking the canonical voter order, one outstanding solicitation at a time."""

    GRANTED = "granted"
    """Every voter in the required set has granted, and the grant set digest
    matches. This is the only state from which entry is permitted."""

    CANCELLING = "cancelling"
    """Durably non-executable at the owner; reconciling peer records."""

    CANCELLED = "cancelled"
    OCCUPYING = "occupying"
    OCCUPIED = "occupied"
    RELEASING = "releasing"
    RELEASED = "released"
    REJECTED = "rejected"
    FAILED = "failed"
    """Abandoned after unrecoverable protocol/transport error. Fenced."""


class VoterSlotState(StrEnum):
    PENDING = "pending"
    GRANTED = "granted"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    """Owner has durably cancelled; peer record not yet reconciled."""

    RELEASED = "released"


def transaction_id(run_id: str, request_version: int, zone_id: str, requester: str) -> str:
    """Total order over transactions - the deterministic tie-break rule."""
    raw = f"{run_id}|{request_version}|{zone_id}|{requester}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


def grant_identity(
    run_id: str,
    epoch: str,
    zone_id: str,
    requester: RobotId,
    requester_session: str,
    request_version: int,
) -> str:
    """Identity of a grant. Any mismatch means the grant is for a *different*
    transaction and must be refused, never coalesced."""
    raw = f"{run_id}|{epoch}|{zone_id}|{requester}|{requester_session}|{request_version}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]


class ZoneRequestBody(_Frozen):
    """Request to acquire ``zone_id`` for protected movement ``movement``."""

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    #: Monotonic per (requester, zone). A repeat of the same version with a
    #: different body is a protocol violation, not an update.
    request_version: int = Field(ge=1)
    movement: str = Field(min_length=1, max_length=24)
    entry_pose: tuple[float, float, float]
    exit_pose: tuple[float, float, float]
    #: Remaining traversal deadline in the *requester's* domain. Used only for
    #: queue fairness among not-yet-served requests, never to revoke authority.
    expires_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    #: Peer-set digest the requester believes is current.
    membership_digest: str = Field(max_length=64)

    @property
    def txn(self) -> str:
        return transaction_id(self.run_id, self.request_version, self.zone_id, self.requester)

    @property
    def grant_id(self) -> str:
        return grant_identity(
            self.run_id,
            self.epoch,
            self.zone_id,
            self.requester,
            self.requester_session,
            self.request_version,
        )


class ZoneGrantBody(_Frozen):
    """A durable promise. The voter has persisted this before sending it."""

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    request_version: int = Field(ge=1)
    #: The grant the voter is answering. Echoed so a mismatched reply is
    #: detectable rather than silently accepted.
    grant_id: str = Field(max_length=24)
    #: Hash over the exact grant set the voter believes is required. The owner
    #: may not enter until its own computed digest equals this one.
    required_set_digest: str = Field(max_length=64)
    #: True for the requester's own local voter. Never pre-acquired: every
    #: requester acquires its own voter in canonical position like any other.
    is_self_voter: bool = False
    persistence_record_id: str = Field(min_length=1, max_length=96)


class ZoneCancelBody(_Frozen):
    """Owner-initiated, durable cancellation.

    Sent only *after* the owner has persisted ``non_executable = true``. The
    ``cancel_seq`` makes cancellation idempotent and makes late grants
    identifiable.
    """

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    request_version: int = Field(ge=1)
    grant_id: str = Field(max_length=24)
    cancel_seq: int = Field(ge=1)
    #: False for a pre-entry cancellation, true only after the requester has
    #: durably made the grant non-executable.
    durably_non_executable: bool
    reason: str = Field(min_length=1, max_length=64)
    time_domain: TimeDomain


class ZoneCancelAckBody(_Frozen):
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    request_version: int = Field(ge=1)
    cancel_seq: int = Field(ge=1)
    voter: RobotId
    voter_session: str = Field(max_length=40)
    #: True when the voter had no record and simply recorded the cancellation.
    no_record: bool = False


class ZoneOccupyBody(_Frozen):
    """Owner declares physical entry into the zone."""

    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    request_version: int = Field(ge=1)
    grant_id: str = Field(max_length=24)
    #: Monotonic per (requester, zone) enter/exit counter. A duplicate enter is
    #: idempotent; a *stale* exit is refused.
    occupancy_seq: int = Field(ge=1)


class ZoneReleaseBody(_Frozen):
    """Owner declares exit and requests the authority be handed back.

    Release is **not** effective on send. It becomes effective only after every
    voter has reconciled the release (a matching release message, never a
    timeout).
    """

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    requester: RobotId
    requester_session: str = Field(max_length=40)
    request_version: int = Field(ge=1)
    grant_id: str = Field(max_length=24)
    occupancy_seq: int = Field(ge=1)
    release_seq: int = Field(ge=1)
    #: The owner asserts full inflated-body clearance. Peers do not trust this
    #: assertion alone; they record it as evidence, not as clearance.
    asserts_full_clearance: bool = True
    time_domain: TimeDomain


class ZoneFenceBody(_Frozen):
    """Supervised, explicit fencing of a zone whose holder failed.

    There is deliberately no "force release" message. Fencing makes the zone
    unavailable and is logged as an explicit, operator-visible state change.
    """

    schema_version: str = SCHEMA_VERSION
    run_id: IdStr
    epoch: IdStr
    zone_id: ZoneId
    fenced_by: RobotId
    reason: str = Field(min_length=1, max_length=120)
    previous_holder: RobotId | None = None
    previous_requester_session: str | None = Field(default=None, max_length=40)
    operator_authorised: bool = False


class FreshnessClass(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    UNKNOWN = "unknown"
    """Clock relationship or provenance is not established well enough to make
    an age claim. Treated conservatively exactly like STALE for permissions,
    while being reported distinctly."""


class PeerState(_Frozen):
    """Published robot state. A claim, never ground truth."""

    robot_id: RobotId
    session_id: str = Field(max_length=40)
    seq: int = Field(ge=0)
    pose: tuple[float, float, float]
    velocity: tuple[float, float]
    uncertainty_m: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    uncertainty_rad: Annotated[float, Field(ge=0.0, allow_inf_nan=False)]
    battery_fraction: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] | None = None
    battery_source: str = Field(default="unavailable", max_length=16)
    carrying_task_id: str | None = Field(default=None, max_length=40)
    stop_reason: str = Field(default="none", max_length=32)
    sent_at_ns: int = Field(ge=0)
    time_domain: TimeDomain


class PeerIntent(_Frozen):
    """Predicted path and the resources the sender expects to need.

    An intent is a *prediction*, never an authorization. Receiving one grants
    nothing.
    """

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    run_id: IdStr
    epoch: IdStr
    map_id: str = Field(max_length=40)
    map_digest: str = Field(max_length=64)
    robot_id: RobotId
    session_id: str = Field(max_length=40)
    seq: int = Field(ge=0)
    plan_version: int = Field(ge=0)
    #: Sampled projected footprint centreline, metres. Bounded length.
    projected_path: tuple[tuple[float, float, float], ...] = ()
    expected_zones: tuple[ZoneId, ...] = ()
    #: How long this intent remains a fair claim.
    validity_horizon_ns: int = Field(ge=0)
    sent_at_ns: int = Field(ge=0)
    time_domain: TimeDomain

    @model_validator(mode="after")
    def _bounded(self) -> Self:
        if len(self.projected_path) > 512:
            raise ValueError("projected_path exceeds 512 samples")
        if len(self.expected_zones) > 8:
            raise ValueError("expected_zones exceeds 8 entries")
        return self


class ObstructionReport(_Frozen):
    """Shared observation of an obstruction, with provenance and age."""

    robot_id: RobotId
    session_id: str = Field(max_length=40)
    zone_id: ZoneId | None = None
    position: tuple[float, float]
    kind: str = Field(min_length=1, max_length=32)
    #: Age of the underlying observation at send time, in the sender's domain.
    observation_age_ns: int = Field(ge=0)
    observed_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    confidence: Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)] = 0.8


class Heartbeat(_Frozen):
    """Liveness only. Explicitly *not* usable intent and *not* clearance."""

    schema_version: str = SCHEMA_VERSION
    run_id: IdStr
    epoch: IdStr
    robot_id: RobotId
    session_id: str = Field(max_length=40)
    seq: int = Field(ge=0)
    sent_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    degraded: bool = False
    degraded_reason: str = Field(default="", max_length=64)


class PeerEnvelope(BaseModel):
    """Transport framing metadata. Present on every message, checked on receipt."""

    model_config = ConfigDict(extra="forbid")
    kind: str = Field(min_length=1, max_length=32)
    protocol_version: str = PROTOCOL_VERSION
    sender: RobotId
    sender_session: str = Field(max_length=40)
    run_id: IdStr
    epoch: IdStr
    #: Per-sender monotonic sequence. Bounded replay window enforced on receipt.
    seq: int = Field(ge=0)
    sent_at_ns: int = Field(ge=0)
    time_domain: TimeDomain
    correlation_id: str = Field(default="", max_length=64)


class PeerMessage(_Frozen):
    """A peer message: envelope plus exactly one typed body.

    Dispatch on ``envelope.kind``. Bodies are stored as validated models (not
    raw dicts) so an unknown critical field is a validation error rather than a
    silently dropped key.
    """

    envelope: PeerEnvelope
    body: (
        ZoneRequestBody
        | ZoneGrantBody
        | ZoneCancelBody
        | ZoneCancelAckBody
        | ZoneOccupyBody
        | ZoneReleaseBody
        | ZoneFenceBody
        | PeerState
        | PeerIntent
        | ObstructionReport
        | Heartbeat
    )
    body_kind: str = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def _kind_matches(self) -> Self:
        expected = _KIND_BY_TYPE.get(type(self.body))
        if expected is None:
            raise ValueError(f"unsupported peer body type {type(self.body).__name__}")
        if expected != self.body_kind:
            raise ValueError(f"body_kind {self.body_kind!r} does not match body type {expected!r}")
        return self

    @property
    def sender(self) -> str:
        return self.envelope.sender

    @property
    def sender_session(self) -> str:
        return self.envelope.sender_session


_KIND_BY_TYPE: dict[type, str] = {
    ZoneRequestBody: "zone_request",
    ZoneGrantBody: "zone_grant",
    ZoneCancelBody: "zone_cancel",
    ZoneCancelAckBody: "zone_cancel_ack",
    ZoneOccupyBody: "zone_occupy",
    ZoneReleaseBody: "zone_release",
    ZoneFenceBody: "zone_fence",
    PeerState: "peer_state",
    PeerIntent: "peer_intent",
    ObstructionReport: "obstruction",
    Heartbeat: "heartbeat",
}


KIND_BY_TYPE: dict[str, type] = {v: k for k, v in _KIND_BY_TYPE.items()}


def build_message(envelope: PeerEnvelope, body: PeerMessageBodyT) -> PeerMessage:
    """Construct a :class:`PeerMessage`, deriving ``body_kind`` from the body."""
    kind = _KIND_BY_TYPE.get(type(body))
    if kind is None:
        raise ValueError(f"no wire kind registered for {type(body).__name__}")
    return PeerMessage(envelope=envelope, body=body, body_kind=kind)


PeerMessageBodyT = (
    ZoneRequestBody
    | ZoneGrantBody
    | ZoneCancelBody
    | ZoneCancelAckBody
    | ZoneOccupyBody
    | ZoneReleaseBody
    | ZoneFenceBody
    | PeerState
    | PeerIntent
    | ObstructionReport
    | Heartbeat
)

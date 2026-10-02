"""Robot identity, session (boot) identity and the admitted peer membership.

The three questions "which robot?", "which incarnation of that robot?" and
"who is admitted to this run/epoch?" are kept as three separate types so that a
message from a rebooted robot can never be mistaken for a message from the
previous incarnation.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from niharamesh.domain.ids import RobotId, ShortIdStr
from niharamesh.domain.pose import Footprint
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION

__all__ = [
    "AdmissionState",
    "Capability",
    "Membership",
    "MembershipState",
    "PeerEndpoint",
    "RobotIdentity",
    "RobotSession",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Capability(StrEnum):
    CARRY_PAYLOAD = "carry_payload"
    TOW = "tow"
    SPOT_FILL = "spot_fill"
    DOCK = "dock"
    CLEAN = "clean"


class AdmissionState(StrEnum):
    """How a robot relates to the current run/epoch.

    ``ADMITTED``     - in the immutable peer set; may vote and be voted for.
    ``PROBATIONARY`` - observed but not yet in the epoch's peer set.
    ``QUARANTINED``  - rejected: bad schema, replay, or fenced failure.
    """

    ADMITTED = "admitted"
    PROBATIONARY = "probationary"
    QUARANTINED = "quarantined"


class RobotIdentity(_Frozen):
    """Persistent identity of a physical robot."""

    schema_version: str = SCHEMA_VERSION
    robot_id: RobotId
    model: str = Field(default="niharamesh-amr", max_length=64)
    capabilities: tuple[Capability, ...] = (Capability.CARRY_PAYLOAD,)
    footprint: Footprint
    max_linear_mps: Annotated[float, Field(gt=0.0, le=2.0, allow_inf_nan=False)] = 0.4
    max_angular_radps: Annotated[float, Field(gt=0.0, le=3.0, allow_inf_nan=False)] = 1.0

    @model_validator(mode="after")
    def _dedupe(self) -> Self:
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("duplicate capability entries")
        return self

    @property
    def can_carry(self) -> bool:
        return Capability.CARRY_PAYLOAD in self.capabilities


class RobotSession(_Frozen):
    """One incarnation (boot) of a robot.

    Every protocol message carries the session id of its sender. A message from
    a stale session is rejected, never merged into current state.
    """

    schema_version: str = SCHEMA_VERSION
    protocol_version: str = PROTOCOL_VERSION
    robot_id: RobotId
    session_id: ShortIdStr
    started_at_ns: int = Field(ge=0)
    #: Monotonic-only. Human-readable start time is a separate field so it can
    #: never be used for expiry maths.
    pid: int = Field(default=0, ge=0)
    host: str = Field(default="localhost", max_length=128)
    listening_port: int = Field(default=0, ge=0, le=65535)

    @property
    def incarnation(self) -> str:
        return f"{self.robot_id}@{self.session_id}"


class PeerEndpoint(_Frozen):
    robot_id: RobotId
    host: str = Field(default="127.0.0.1", max_length=128)
    port: int = Field(ge=1, le=65535)

    def address(self) -> tuple[str, int]:
        return (self.host, self.port)


class MembershipState(StrEnum):
    """Controlled reconciliation state of the peer set."""

    FROZEN = "frozen"
    """Immutable for the whole run. The default and the only state used for
    benchmark eligibility."""

    RECONCILING = "reconciling"
    """A supervised change is in flight. New authority is withheld while this
    holds, so no grant can be split across two different peer sets."""

    FENCED = "fenced"
    """No authority may be exercised until reconciliation completes."""


class Membership(_Frozen):
    """The immutable peer set for a run epoch, plus its reconciliation state."""

    run_id: ShortIdStr
    epoch: ShortIdStr
    members: tuple[RobotId, ...]
    state: MembershipState = MembershipState.FROZEN
    #: Canonical acquisition order. Sorted ascending by robot_id; every
    #: requester must acquire in exactly this order.
    canonical_order: tuple[RobotId, ...] = ()
    digest: str = Field(default="", max_length=64)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if len(set(self.members)) != len(self.members):
            raise ValueError("duplicate robot_id in membership")
        if not self.members:
            raise ValueError("membership must contain at least one robot")
        if self.canonical_order and tuple(sorted(self.members)) != self.canonical_order:
            raise ValueError("canonical_order must equal sorted(members)")
        return self

    def order(self) -> tuple[RobotId, ...]:
        """Canonical acquisition order (sorted by robot_id) - never implicit."""
        return self.canonical_order or tuple(sorted(self.members))

    def contains(self, robot_id: str) -> bool:
        return robot_id in self.members

    def index_of(self, robot_id: str) -> int:
        order = self.order()
        for i, member in enumerate(order):
            if member == robot_id:
                return i
        raise KeyError(f"{robot_id!r} is not an admitted member")

    @property
    def voter_count(self) -> int:
        return len(self.members)

    def quorum(self) -> int:
        """Required grant count. Canonical sequential acquisition needs *all*."""
        return len(self.members)


AdmissionOutcome = Literal["admitted", "probationary", "quarantined", "fenced"]


def admission_outcome(
    identity: RobotIdentity,
    session: RobotSession,
    membership: Membership,
    *,
    observed_protocol: str,
) -> AdmissionOutcome:
    """Decide whether an identity/session may participate in this epoch.

    Kept as a function (not a validator) so the launcher's admission check, the
    peer-transport admission check and the tests share exactly one rule.
    """
    if observed_protocol != PROTOCOL_VERSION:
        return "quarantined"
    if session.robot_id != identity.robot_id:
        return "quarantined"
    if not membership.contains(identity.robot_id):
        return "probationary"
    if membership.state is not MembershipState.FROZEN:
        return "fenced"
    return "admitted"

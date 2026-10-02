"""Stable identifiers and small value objects shared across every layer.

Identifiers are opaque strings. They are validated for shape (length, allowed
characters) but never interpreted. Nothing in the system may derive authority
from the *value* of an id, only from its membership in a validated set.
"""

from __future__ import annotations

import hashlib
import re
from typing import Annotated, Final

from pydantic import AfterValidator, StringConstraints

__all__ = [
    "MAX_ID_LENGTH",
    "Digested",
    "EventId",
    "IdStr",
    "RequestId",
    "RobotId",
    "RunId",
    "SessionId",
    "ShortIdStr",
    "TaskId",
    "ZoneId",
    "digest_of",
]

MAX_ID_LENGTH: Final[int] = 96

_ID_RE: re.Pattern[str] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#@\-]*$")


def _validate_id(value: str) -> str:
    if not value:
        raise ValueError("identifier must not be empty")
    if len(value) > MAX_ID_LENGTH:
        raise ValueError(f"identifier exceeds {MAX_ID_LENGTH} characters: {value[:24]!r}...")
    if not _ID_RE.match(value):
        raise ValueError(
            f"identifier must match [A-Za-z0-9][A-Za-z0-9._:#@-]* (rejected {value[:32]!r})"
        )
    return value


IdStr = Annotated[
    str, StringConstraints(min_length=1, max_length=MAX_ID_LENGTH), AfterValidator(_validate_id)
]
"""Any stable identifier."""

ShortIdStr = Annotated[
    str, StringConstraints(min_length=1, max_length=40), AfterValidator(_validate_id)
]

RobotId = ShortIdStr
ZoneId = ShortIdStr
TaskId = ShortIdStr
RequestId = IdStr
SessionId = ShortIdStr
EventId = IdStr
RunId = ShortIdStr


def digest_of(*parts: object, length: int = 32) -> str:
    """Deterministic content digest over ``parts``.

    Used for scenario snapshots, bid-set digests and canonical run hashes.
    ``repr`` is used for structural identity because it is stable for the plain
    dataclasses/tuples we hash; callers hashing domain models should pass
    ``model_dump_json`` explicitly instead.
    """
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(repr(part).encode("utf-8"))
        hasher.update(b"\x1f")
    return hasher.hexdigest()[:length]


Digested = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{16,64}$")]
"""A lowercase hex content digest."""

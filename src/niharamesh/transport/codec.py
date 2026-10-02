"""Strict, canonical codec for :class:`PeerMessage`.

Three properties are load-bearing:

*Canonical.* ``encode_message`` emits sorted-key, whitespace-free JSON. Two
robots that construct the same :class:`PeerMessage` produce byte-identical
frames, so a digest over the bytes is a digest over the message.

*Strict.* ``decode_message`` names the offending field. The envelope and the
body are validated against the *concrete* model implied by ``body_kind`` rather
than against the whole union, because a union reports every branch's missing
fields and hides the one that actually mattered.

*All-or-nothing.* A malformed message raises :class:`ProtocolDecodeError`
before a :class:`PeerMessage` object exists. There is no partially applied
message, because there is no partial object.

The envelope carries ``protocol_version`` and every versioned body carries
``schema_version``. An incompatible peer is rejected by name rather than being
silently interpreted under the wrong contract (AGENTS.md rule 10).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from niharamesh.domain.coordination import KIND_BY_TYPE, PeerEnvelope, PeerMessage
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION
from niharamesh.transport.framing import encode_frame, read_frame

__all__ = [
    "MAX_FRAME_BYTES",
    "MAX_MESSAGE_BYTES",
    "MessageTooLargeError",
    "ProtocolDecodeError",
    "ProtocolError",
    "canonical_payload",
    "decode_frame",
    "decode_message",
    "encode_message",
]

#: Hard ceiling on one encoded peer message. Anything larger is a bug or an
#: attack; either way it is rejected with a stable code, never truncated.
MAX_MESSAGE_BYTES: Final[int] = 256 * 1024

#: The frame ceiling implied by :data:`MAX_MESSAGE_BYTES`.
MAX_FRAME_BYTES: Final[int] = MAX_MESSAGE_BYTES + 64

_ENVELOPE_FIELDS: Final[frozenset[str]] = frozenset(PeerEnvelope.model_fields)
_TOP_LEVEL_FIELDS: Final[frozenset[str]] = frozenset({"envelope", "body", "body_kind"})


class ProtocolError(Exception):
    """Base class for wire-protocol failures. Always carries a stable code."""

    code = "protocol_error"


class ProtocolDecodeError(ProtocolError):
    """A received payload is not a valid peer message.

    ``field`` is the dotted path of the offending member, e.g.
    ``"envelope.sender"`` or ``"body.nope"``. It is part of the contract: an
    operator reading a log must be able to see *what* was wrong without
    reproducing the failure.
    """

    code = "protocol_decode_error"

    def __init__(self, message: str, *, field: str, code: str | None = None) -> None:
        super().__init__(message)
        self.field = field
        if code is not None:
            self.code = code


class MessageTooLargeError(ProtocolError):
    """The encoded message exceeds :data:`MAX_MESSAGE_BYTES`."""

    code = "message_too_large"

    def __init__(self, message: str, *, size: int, max_bytes: int) -> None:
        super().__init__(message)
        self.size = size
        self.max_bytes = max_bytes


def canonical_payload(msg: PeerMessage) -> bytes:
    """Canonical JSON for *msg*: sorted keys, no whitespace, UTF-8."""
    return json.dumps(
        msg.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def encode_message(msg: PeerMessage, *, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    """Encode *msg* into a single length-prefixed frame."""
    payload = canonical_payload(msg)
    if len(payload) > max_bytes:
        raise MessageTooLargeError(
            f"encoded message of {len(payload)} bytes exceeds {max_bytes}",
            size=len(payload),
            max_bytes=max_bytes,
        )
    return encode_frame(payload, max_bytes=MAX_FRAME_BYTES)


async def decode_frame(
    reader: asyncio.StreamReader,
    *,
    max_bytes: int = MAX_MESSAGE_BYTES,
) -> PeerMessage:
    """Read one framed message off *reader* and decode it strictly.

    Framing faults (too large, truncated, clean close) surface as the framing
    layer's own exceptions, before any JSON is parsed.
    """
    payload = await read_frame(reader, max_bytes=MAX_FRAME_BYTES)
    return decode_message(payload, max_bytes=max_bytes)


def decode_message(raw: bytes, *, max_bytes: int = MAX_MESSAGE_BYTES) -> PeerMessage:
    """Decode one canonical message payload. Never partially applied.

    ``raw`` is the *unframed* payload as returned by
    :func:`~niharamesh.transport.framing.read_frame`.
    """
    if len(raw) > max_bytes:
        raise MessageTooLargeError(
            f"message of {len(raw)} bytes exceeds {max_bytes}",
            size=len(raw),
            max_bytes=max_bytes,
        )
    return decode_payload(raw)


def decode_payload(payload: bytes) -> PeerMessage:
    """Decode an unframed canonical payload into a :class:`PeerMessage`."""
    try:
        document = json.loads(payload)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ProtocolDecodeError(
            f"payload is not valid JSON: {exc}", field="<json>", code="malformed_json"
        ) from exc
    if not isinstance(document, dict):
        raise ProtocolDecodeError(
            f"top-level JSON must be an object, got {type(document).__name__}",
            field="<root>",
            code="malformed_root",
        )

    _reject_unknown(document, _TOP_LEVEL_FIELDS, "")

    raw_kind = document.get("body_kind")
    if not isinstance(raw_kind, str) or raw_kind not in KIND_BY_TYPE:
        raise ProtocolDecodeError(
            f"unknown body_kind {raw_kind!r}",
            field="body_kind",
            code="unknown_body_kind",
        )
    body_cls: type[BaseModel] = KIND_BY_TYPE[raw_kind]

    envelope_doc = document.get("envelope")
    if not isinstance(envelope_doc, dict):
        raise ProtocolDecodeError(
            f"envelope must be a JSON object, got {type(envelope_doc).__name__}",
            field="envelope",
            code="malformed_object",
        )
    _reject_unknown(envelope_doc, _ENVELOPE_FIELDS, "envelope")
    envelope = _validate(PeerEnvelope, envelope_doc, "envelope")
    _check_protocol_version(envelope)

    body_doc = document.get("body")
    if not isinstance(body_doc, dict):
        raise ProtocolDecodeError(
            f"body must be a JSON object for kind {raw_kind!r}",
            field="body",
            code="malformed_body",
        )
    _reject_unknown(body_doc, frozenset(body_cls.model_fields), "body")
    body = _validate(body_cls, body_doc, "body")
    _check_body_versions(body)

    try:
        return PeerMessage(envelope=envelope, body=body, body_kind=raw_kind)
    except ValidationError as exc:
        raise _as_decode_error(exc, "peer_message") from exc


def _reject_unknown(document: dict[str, Any], allowed: frozenset[str], prefix: str) -> None:
    for key in document:
        if key not in allowed:
            path = f"{prefix}.{key}" if prefix else key
            raise ProtocolDecodeError(
                f"unknown field {path!r} is not part of the peer message contract",
                field=path,
                code="unknown_field",
            )


def _validate(model: type[BaseModel], document: object, path: str) -> Any:
    if not isinstance(document, dict):
        raise ProtocolDecodeError(
            f"{path} must be a JSON object, got {type(document).__name__}",
            field=path,
            code="malformed_object",
        )
    try:
        return model.model_validate(document)
    except ValidationError as exc:
        raise _as_decode_error(exc, path) from exc


def _as_decode_error(exc: ValidationError, path: str) -> ProtocolDecodeError:
    first = exc.errors()[0] if exc.errors() else None
    if first is None:  # pragma: no cover - pydantic always reports at least one
        return ProtocolDecodeError("message failed validation", field=path, code="schema_violation")
    location = ".".join(str(part) for part in first.get("loc", ())) or path
    return ProtocolDecodeError(
        f"{path}: {first.get('msg', 'validation failed')} (at {location})",
        field=f"{path}.{location}" if location != path else location,
        code=str(first.get("type", "schema_violation")),
    )


def _check_protocol_version(envelope: PeerEnvelope) -> None:
    if envelope.protocol_version != PROTOCOL_VERSION:
        raise ProtocolDecodeError(
            f"peer speaks protocol {envelope.protocol_version!r}; this robot speaks {PROTOCOL_VERSION!r}",
            field="envelope.protocol_version",
            code="protocol_mismatch",
        )


def _check_body_versions(body: Any) -> None:
    schema = getattr(body, "schema_version", None)
    if schema is not None and schema != SCHEMA_VERSION:
        raise ProtocolDecodeError(
            f"body declares schema {schema!r}; this robot speaks {SCHEMA_VERSION!r}",
            field="body.schema_version",
            code="schema_mismatch",
        )
    protocol = getattr(body, "protocol_version", None)
    if protocol is not None and protocol != PROTOCOL_VERSION:
        raise ProtocolDecodeError(
            f"body declares protocol {protocol!r}; this robot speaks {PROTOCOL_VERSION!r}",
            field="body.protocol_version",
            code="protocol_mismatch",
        )

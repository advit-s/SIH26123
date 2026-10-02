"""Codec tests. Strictness is a contract: a bad message must be named, not guessed at."""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from niharamesh.domain.coordination import (
    Heartbeat,
    PeerEnvelope,
    PeerMessage,
    PeerState,
    ZoneRequestBody,
    build_message,
)
from niharamesh.domain.units import PROTOCOL_VERSION, SCHEMA_VERSION, TimeDomain
from niharamesh.transport.codec import (
    MAX_MESSAGE_BYTES,
    MessageTooLargeError,
    ProtocolDecodeError,
    canonical_payload,
    decode_frame,
    decode_message,
    encode_message,
)
from niharamesh.transport.framing import (
    ConnectionClosedError,
    FrameTooLargeError,
    TruncatedFrameError,
    encode_frame,
)


def _envelope(**overrides: object) -> PeerEnvelope:
    fields: dict[str, object] = {
        "kind": "peer_state",
        "sender": "r1",
        "sender_session": "sess-r1",
        "run_id": "run-a",
        "epoch": "e1",
        "seq": 7,
        "sent_at_ns": 1_000,
        "time_domain": TimeDomain.MONOTONIC,
    }
    fields.update(overrides)
    return PeerEnvelope(**fields)  # type: ignore[arg-type]


def _state(**overrides: object) -> PeerState:
    fields: dict[str, object] = {
        "robot_id": "r1",
        "session_id": "sess-r1",
        "seq": 7,
        "pose": (1.0, 2.0, 0.5),
        "velocity": (0.2, 0.0),
        "uncertainty_m": 0.01,
        "uncertainty_rad": 0.02,
        "battery_fraction": 0.8,
        "battery_source": "measured",
        "carrying_task_id": "t-1",
        "stop_reason": "none",
        "sent_at_ns": 1_000,
        "time_domain": TimeDomain.MONOTONIC,
    }
    fields.update(overrides)
    return PeerState(**fields)  # type: ignore[arg-type]


def _request() -> PeerMessage:
    return build_message(
        _envelope(kind="zone_request"),
        ZoneRequestBody(
            run_id="run-a",
            epoch="e1",
            zone_id="z-1",
            requester="r1",
            requester_session="sess-r1",
            request_version=1,
            movement="aisle_1",
            entry_pose=(0.0, 0.0, 0.0),
            exit_pose=(4.0, 0.0, 0.0),
            expires_at_ns=5_000,
            time_domain=TimeDomain.MONOTONIC,
            membership_digest="d1",
        ),
    )


def _document(message: PeerMessage) -> dict[str, object]:
    return json.loads(canonical_payload(message))


def _encode_document(document: dict[str, object], *, max_bytes: int = MAX_MESSAGE_BYTES) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _frame(payload: bytes, *, max_bytes: int = 4096) -> bytes:
    return encode_frame(payload, max_bytes=max_bytes)


def test_round_trip_preserves_the_message() -> None:
    message = build_message(_envelope(), _state())
    assert decode_message(canonical_payload(message)) == message


def test_round_trip_preserves_a_zone_request() -> None:
    message = _request()
    assert decode_message(canonical_payload(message)) == message


def test_encoding_is_canonical_and_version_stamped() -> None:
    message = build_message(_envelope(), _state())
    raw = canonical_payload(message)
    assert b", " not in raw and b'": ' not in raw  # no whitespace
    document = json.loads(raw)
    envelope = document["envelope"]
    body = document["body"]
    assert isinstance(envelope, dict)
    assert isinstance(body, dict)
    assert envelope["protocol_version"] == PROTOCOL_VERSION
    keys = list(envelope)
    assert keys == sorted(keys)  # sorted keys, deterministically
    # A versioned body carries its own schema version, and both are checked.
    request_body = json.loads(canonical_payload(_request()))["body"]
    assert request_body["schema_version"] == SCHEMA_VERSION  # type: ignore[index]
    assert request_body["protocol_version"] == PROTOCOL_VERSION


def test_unknown_envelope_field_is_named() -> None:
    message = build_message(_envelope(), _state())
    document = _document(message)
    envelope = document["envelope"]
    assert isinstance(envelope, dict)
    envelope["bogus_field"] = 1  # type: ignore[index]
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "envelope.bogus_field"
    assert excinfo.value.code == "unknown_field"
    assert "bogus_field" in str(excinfo.value)


def test_unknown_body_field_is_named() -> None:
    message = _request()
    document = _document(message)
    body = document["body"]
    assert isinstance(body, dict)
    body["grant_id"] = "forged"  # type: ignore[index]
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "body.grant_id"
    assert "grant_id" in str(excinfo.value)


def test_unknown_top_level_field_is_named() -> None:
    document = _document(build_message(_envelope(), _state()))
    document["extra"] = True
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "extra"


def test_wrong_protocol_version_is_rejected() -> None:
    document = _document(build_message(_envelope(), _state()))
    envelope = document["envelope"]
    assert isinstance(envelope, dict)
    envelope["protocol_version"] = "9.9.9"  # type: ignore[index]
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "envelope.protocol_version"
    assert excinfo.value.code == "protocol_mismatch"


def test_wrong_body_schema_version_is_rejected() -> None:
    document = _document(_request())
    body = document["body"]
    assert isinstance(body, dict)
    body["schema_version"] = "0.0.1"  # type: ignore[index]
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "body.schema_version"
    assert excinfo.value.code == "schema_mismatch"


def test_body_kind_mismatch_is_rejected() -> None:
    document = _document(build_message(_envelope(), _state()))
    document["body_kind"] = "zone_grant"
    with pytest.raises(ProtocolDecodeError):
        decode_message(_encode_document(document))


def test_unknown_body_kind_is_rejected() -> None:
    document = _document(build_message(_envelope(), _state()))
    document["body_kind"] = "not_a_kind"
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert excinfo.value.field == "body_kind"
    assert excinfo.value.code == "unknown_body_kind"


def test_missing_envelope_field_is_named() -> None:
    document = _document(build_message(_envelope(), _state()))
    envelope = document["envelope"]
    assert isinstance(envelope, dict)
    del envelope["epoch"]  # type: ignore[attr-defined]
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(_encode_document(document))
    assert "epoch" in excinfo.value.field


def test_malformed_json_is_rejected_without_partial_application() -> None:
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(b"{not json")
    assert excinfo.value.code == "malformed_json"


def test_non_object_root_is_rejected() -> None:
    with pytest.raises(ProtocolDecodeError) as excinfo:
        decode_message(b"[1,2,3]")
    assert excinfo.value.code == "malformed_root"


def test_oversized_message_is_rejected_with_a_stable_code() -> None:
    message = build_message(_envelope(), _state(carrying_task_id="t" * 40))
    with pytest.raises(MessageTooLargeError) as excinfo:
        encode_message(message, max_bytes=64)
    assert excinfo.value.code == "message_too_large"
    assert excinfo.value.max_bytes == 64


def test_oversized_inbound_payload_is_rejected() -> None:
    with pytest.raises(MessageTooLargeError) as excinfo:
        decode_message(b"x" * 500, max_bytes=128)
    assert excinfo.value.code == "message_too_large"
    assert excinfo.value.size == 500


async def _decode_frame(payloads: list[bytes]) -> PeerMessage:
    reader = asyncio.StreamReader()
    for chunk in payloads:
        reader.feed_data(chunk)
    reader.feed_eof()
    return await decode_frame(reader)


async def test_decode_frame_round_trips() -> None:
    message = build_message(_envelope(), _state())
    assert await _decode_frame([encode_message(message)]) == message


async def test_decode_frame_surfaces_framing_faults_before_parsing() -> None:
    with pytest.raises(ProtocolDecodeError) as excinfo:
        await _decode_frame([_frame(b"junk")])
    assert excinfo.value.code == "malformed_json"

    with pytest.raises(TruncatedFrameError):
        await _decode_frame([struct.pack(">I", 99) + b"junk"])

    with pytest.raises(ConnectionClosedError):
        await _decode_frame([])


async def test_decode_frame_rejects_an_oversized_declaration() -> None:
    with pytest.raises(FrameTooLargeError):
        await _decode_frame([struct.pack(">I", 4_000_000_000) + b"junk"])


def test_heartbeat_round_trips() -> None:
    message = build_message(
        _envelope(kind="heartbeat", sender="r2"),
        Heartbeat(
            run_id="run-a",
            epoch="e1",
            robot_id="r2",
            session_id="sess-r2",
            seq=1,
            sent_at_ns=42,
            time_domain=TimeDomain.MONOTONIC,
        ),
    )
    assert decode_message(canonical_payload(message)) == message

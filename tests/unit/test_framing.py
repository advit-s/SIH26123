"""Framing tests. Behaviour, not implementation: what a peer can make us allocate."""

from __future__ import annotations

import asyncio
import struct

import pytest

from niharamesh.transport.framing import (
    FRAME_PREFIX_BYTES,
    ConnectionClosedError,
    FrameStats,
    FrameTooLargeError,
    TruncatedFrameError,
    encode_frame,
    read_frame,
)


def _reader(data: bytes) -> asyncio.StreamReader:
    reader = asyncio.StreamReader(limit=4096)
    reader.feed_data(data)
    reader.feed_eof()
    return reader


async def _read(data: bytes, max_bytes: int = 1024) -> bytes:
    return await read_frame(_reader(data), max_bytes=max_bytes)


async def test_round_trip_preserves_payload() -> None:
    payload = b'{"kind":"peer_state","n":1}'
    assert await _read(encode_frame(payload)) == payload


async def test_prefix_is_big_endian_uint32() -> None:
    frame = encode_frame(b"abcd", max_bytes=64)
    assert frame[:FRAME_PREFIX_BYTES] == b"\x00\x00\x00\x04"
    assert struct.unpack(">I", frame[:FRAME_PREFIX_BYTES])[0] == 4
    assert frame[FRAME_PREFIX_BYTES:] == b"abcd"


async def test_two_frames_decode_back_to_back() -> None:
    stream = encode_frame(b"one", max_bytes=64) + encode_frame(b"two", max_bytes=64)
    reader = _reader(stream)
    assert await read_frame(reader, max_bytes=64) == b"one"
    assert await read_frame(reader, max_bytes=64) == b"two"


async def test_empty_frame_is_valid_and_yields_empty_payload() -> None:
    frame = encode_frame(b"", max_bytes=64)
    assert frame == b"\x00\x00\x00\x00"
    assert await _read(frame) == b""


async def test_encode_rejects_oversize_before_allocating() -> None:
    with pytest.raises(FrameTooLargeError) as excinfo:
        encode_frame(b"x" * 100, max_bytes=8)
    assert excinfo.value.declared == 100
    assert excinfo.value.max_bytes == 8
    assert excinfo.value.code == "frame_too_large"


async def test_read_rejects_huge_declared_length_before_reading_body() -> None:
    """A peer claiming 4 GiB must cost us four bytes and one exception.

    The body is never consumed, which is the observable proof that no
    body-sized buffer was ever allocated.
    """
    header = struct.pack(">I", 4_000_000_000)
    body = b"\xaa" * 4096
    reader = _reader(header + body)
    stats = FrameStats()

    with pytest.raises(FrameTooLargeError) as excinfo:
        await read_frame(reader, max_bytes=1024, stats=stats)

    assert excinfo.value.declared == 4_000_000_000
    assert excinfo.value.max_bytes == 1024
    # Untouched: the declared body is still in the reader, unbuffered.
    remaining = await reader.read(8192)
    assert remaining == body
    assert stats.too_large == 1
    assert stats.frames_in == 0
    assert stats.peak_frame_bytes == 0


async def test_max_bytes_boundary_is_inclusive() -> None:
    assert await _read(encode_frame(b"x" * 32, max_bytes=32), max_bytes=32) == b"x" * 32
    with pytest.raises(FrameTooLargeError):
        await _read(encode_frame(b"x" * 33, max_bytes=32), max_bytes=32)


async def test_truncated_header_raises_truncated() -> None:
    with pytest.raises(TruncatedFrameError) as excinfo:
        await _read(b"\x00\x00")
    assert excinfo.value.received == 2
    assert excinfo.value.expected == FRAME_PREFIX_BYTES


async def test_truncated_body_raises_truncated() -> None:
    frame = struct.pack(">I", 64) + b"short"
    with pytest.raises(TruncatedFrameError) as excinfo:
        await _read(frame)
    assert excinfo.value.expected == 64
    assert excinfo.value.received == 5


async def test_clean_close_is_connection_closed_not_truncation() -> None:
    stats = FrameStats()
    with pytest.raises(ConnectionClosedError) as excinfo:
        await read_frame(_reader(b""), max_bytes=64, stats=stats)
    assert excinfo.value.code == "connection_closed"
    assert stats.closed == 1
    assert stats.truncated == 0


async def test_zero_max_bytes_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_bytes must be positive"):
        await _read(b"\x00\x00\x00\x00", max_bytes=0)


async def test_frame_stats_bound_the_peak() -> None:
    stats = FrameStats()
    for size in (4, 64, 16, 1024):
        payload = b"z" * size
        await read_frame(_reader(encode_frame(payload, max_bytes=2048)), max_bytes=2048, stats=stats)
    assert stats.frames_in == 4
    assert stats.bytes_in == 4 + 64 + 16 + 1024
    assert stats.peak_frame_bytes == 1024
    assert stats.peak_frame_bytes < 2048

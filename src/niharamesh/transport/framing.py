"""Length-prefixed framing for direct robot-to-robot sockets.

Wire layout, exactly and nothing else::

    +--------------------------+---------------------------+
    | uint32 length, BE, 4 B   | payload, `length` bytes    |
    +--------------------------+---------------------------+

The prefix is *big-endian unsigned* so a byte-order mismatch is impossible to
mistake for a plausible length, and the layout is self-delimiting: a receiver
always knows where the next frame begins without scanning for a delimiter.

The whole point of the ``max_bytes`` guard is that it runs **before** any
allocation proportional to the peer-controlled length. A buggy or hostile peer
that declares ``4_000_000_000`` bytes must make the receiver raise
:class:`FrameTooLargeError` after reading four bytes, not after reserving four
gigabytes. :class:`FrameStats` records the peak frame length actually accepted
so a soak test can prove no buffer grew without bound.
"""

from __future__ import annotations

import asyncio
import struct
from dataclasses import dataclass
from typing import Final

__all__ = [
    "DEFAULT_MAX_FRAME_BYTES",
    "FRAME_PREFIX_BYTES",
    "ConnectionClosedError",
    "FrameError",
    "FrameStats",
    "FrameTooLargeError",
    "TruncatedFrameError",
    "encode_frame",
    "read_frame",
]

#: Size of the length prefix. Four bytes => a 4 GiB ceiling, far above any
#: message this protocol can produce.
FRAME_PREFIX_BYTES: Final[int] = 4

#: Default ceiling for a single frame payload. Matches
#: ``niharamesh.transport.codec.MAX_MESSAGE_BYTES`` plus slack for the prefix.
DEFAULT_MAX_FRAME_BYTES: Final[int] = 262_144

_LENGTH_STRUCT: Final[struct.Struct] = struct.Struct(">I")
_UINT32_MAX: Final[int] = 0xFFFF_FFFF


class FrameError(Exception):
    """Base class for every framing failure. Never a silent data corruption."""

    code: str = "frame_error"


class FrameTooLargeError(FrameError):
    """A frame declares more bytes than the receiver is willing to buffer.

    Raised *before* the body is read or any body-sized buffer is allocated.
    """

    code = "frame_too_large"

    def __init__(self, message: str, *, declared: int, max_bytes: int) -> None:
        super().__init__(message)
        self.declared = declared
        self.max_bytes = max_bytes


class TruncatedFrameError(FrameError):
    """The stream ended part-way through a declared frame."""

    code = "truncated_frame"

    def __init__(self, message: str, *, expected: int, received: int) -> None:
        super().__init__(message)
        self.expected = expected
        self.received = received


class ConnectionClosedError(FrameError):
    """The peer closed the connection cleanly at a frame boundary.

    A clean close is not a fault: it is how a healthy shutdown looks.
    """

    code = "connection_closed"


@dataclass(slots=True)
class FrameStats:
    """Counters proving the framing layer stayed bounded.

    ``peak_frame_bytes`` is the largest payload this process ever accepted.
    It must never approach ``max_frame_bytes`` in a healthy run; if it does, the
    guard has been weakened.
    """

    frames_in: int = 0
    frames_out: int = 0
    bytes_in: int = 0
    bytes_out: int = 0
    peak_frame_bytes: int = 0
    max_bytes_declared: int = 0
    too_large: int = 0
    truncated: int = 0
    closed: int = 0

    def record_in(self, payload: bytes) -> None:
        self.frames_in += 1
        self.bytes_in += len(payload)
        self.peak_frame_bytes = max(self.peak_frame_bytes, len(payload))

    def record_out(self, payload: bytes) -> None:
        self.frames_out += 1
        self.bytes_out += len(payload)
        self.peak_frame_bytes = max(self.peak_frame_bytes, len(payload))

    def as_dict(self) -> dict[str, int]:
        return {
            "frames_in": self.frames_in,
            "frames_out": self.frames_out,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "peak_frame_bytes": self.peak_frame_bytes,
            "max_bytes_declared": self.max_bytes_declared,
            "too_large": self.too_large,
            "truncated": self.truncated,
            "closed": self.closed,
        }


def encode_frame(payload: bytes, *, max_bytes: int = DEFAULT_MAX_FRAME_BYTES) -> bytes:
    """Wrap *payload* in a length prefix.

    The ``max_bytes`` check happens first so an oversized payload is rejected
    before a second buffer of the same size is ever built.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    size = len(payload)
    if size > max_bytes:
        raise FrameTooLargeError(
            f"payload of {size} bytes exceeds the {max_bytes}-byte frame limit",
            declared=size,
            max_bytes=max_bytes,
        )
    if size > _UINT32_MAX:
        raise FrameTooLargeError(
            f"payload of {size} bytes cannot be expressed in a uint32 prefix",
            declared=size,
            max_bytes=max_bytes,
        )
    return _LENGTH_STRUCT.pack(size) + payload


async def read_frame(
    reader: asyncio.StreamReader,
    *,
    max_bytes: int = DEFAULT_MAX_FRAME_BYTES,
    stats: FrameStats | None = None,
) -> bytes:
    """Read exactly one frame, validating the declared length before the body.

    Ordering matters: the length prefix is read, checked against ``max_bytes``,
    and only then is the body read. A peer cannot therefore make this
    coroutine allocate more than ``max_bytes`` by lying in its header.
    """
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    try:
        prefix = await reader.readexactly(FRAME_PREFIX_BYTES)
    except asyncio.IncompleteReadError as exc:
        if not exc.partial:
            if stats is not None:
                stats.closed += 1
            raise ConnectionClosedError("peer closed the connection at a frame boundary") from exc
        if stats is not None:
            stats.truncated += 1
        raise TruncatedFrameError(
            f"only {len(exc.partial)} of {FRAME_PREFIX_BYTES} prefix bytes arrived",
            expected=FRAME_PREFIX_BYTES,
            received=len(exc.partial),
        ) from exc

    (declared,) = _LENGTH_STRUCT.unpack(prefix)
    if stats is not None:
        stats.max_bytes_declared = max(stats.max_bytes_declared, declared)

    if declared > max_bytes:
        if stats is not None:
            stats.too_large += 1
        # The body is deliberately left in the stream: we never read it, so we
        # never allocate it. Recovery is to close the connection.
        raise FrameTooLargeError(
            f"peer declared a {declared}-byte frame; limit is {max_bytes}",
            declared=declared,
            max_bytes=max_bytes,
        )

    if declared == 0:
        if stats is not None:
            stats.record_in(b"")
        return b""

    try:
        payload = await reader.readexactly(declared)
    except asyncio.IncompleteReadError as exc:
        if stats is not None:
            stats.truncated += 1
        raise TruncatedFrameError(
            f"frame body ended after {len(exc.partial)} of {declared} bytes",
            expected=declared,
            received=len(exc.partial),
        ) from exc

    if stats is not None:
        stats.record_in(payload)
    return payload

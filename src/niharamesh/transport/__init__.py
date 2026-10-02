"""Direct robot-to-robot transport: framing, codec, faults, clock sync, sockets.

Import graph, which is the decentralisation claim::

    agent -> niharamesh.transport -> asyncio sockets
                              \\-> domain.identity.admission_outcome
                              \\-> domain.coordination (pure data)

There is no import of :mod:`niharamesh.api`, :mod:`niharamesh.simulator` or any
broker from anything in this package, and a reviewer can check that with
``grep``. Coordination traffic cannot reach a central component because no code
path here can address one.

Layers, outermost first:

``peer``
    Sockets, admission, replay windows, the bounded inbox and health reporting.
``faults``
    Delay / drop / duplicate / reorder / partition, directed and seeded. It may
    never decide anything, and removing a fault restores communication without
    restoring permission.
``clocksync``
    Round-trip offset estimation with an explicit uncertainty bound.
``codec``
    Canonical, strict, all-or-nothing JSON for one :class:`PeerMessage`.
``framing``
    ``uint32`` big-endian length prefix, validated before any body is read.
"""

from __future__ import annotations

from niharamesh.transport.clocksync import ClockSync, is_clock_probe, probe_correlation
from niharamesh.transport.codec import (
    MAX_MESSAGE_BYTES,
    ProtocolDecodeError,
    ProtocolError,
    decode_message,
    encode_message,
)
from niharamesh.transport.faults import (
    ACTIVE_FAULT_NOTE,
    ActiveFault,
    DecisionKind,
    DeliveryDecision,
    FaultLayer,
)
from niharamesh.transport.framing import (
    ConnectionClosedError,
    FrameStats,
    FrameTooLargeError,
    TruncatedFrameError,
    encode_frame,
    read_frame,
)
from niharamesh.transport.peer import (
    PeerDeclaration,
    PeerStatus,
    PeerTransportServer,
    ReplayWindow,
)

__all__ = [
    "ACTIVE_FAULT_NOTE",
    "MAX_MESSAGE_BYTES",
    "ActiveFault",
    "ClockSync",
    "ConnectionClosedError",
    "DecisionKind",
    "DeliveryDecision",
    "FaultLayer",
    "FrameStats",
    "FrameTooLargeError",
    "PeerDeclaration",
    "PeerStatus",
    "PeerTransportServer",
    "ProtocolDecodeError",
    "ProtocolError",
    "ReplayWindow",
    "TruncatedFrameError",
    "decode_message",
    "encode_frame",
    "encode_message",
    "is_clock_probe",
    "probe_correlation",
    "read_frame",
]

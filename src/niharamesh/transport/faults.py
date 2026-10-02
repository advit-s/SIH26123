"""The controllable fault layer that sits between a socket and an agent.

What this layer may do
----------------------
delay, drop, duplicate, reorder, partition a declared direction, and perturb a
*declared* clock-offset estimate. That is the whole list.

What this layer may never do
----------------------------
* **Never decide for an agent.** It has no access to zones, grants, tasks or
  the world. Its entire output vocabulary is :class:`DecisionKind`, which
  contains no ``PERMIT``, and ``FaultLayer.authority_decisions`` is a constant
  zero that exists so a test can assert the invariant instead of trusting the
  prose.
* **Never synthesise or alter semantic content.** The exact
  :class:`PeerMessage` it was handed is the object it delivers - once, twice,
  later, or never. No field is rewritten.

The removable-fault rule
------------------------
Faults are removable, and that is a *transport* statement, not an authority
one. Removing a network fault restores **communication**. It does not restore,
create or imply **movement permission**: a ``zone_grant`` that was dropped
stays dropped, and the owning robot stays outside the zone until the protocol
durably makes a fresh grant. ``AGENTS.md`` rule 4 - conservative occupancy -
means a network repair cannot unfreeze the world.

Targeting
---------
Every fault is directed at ``sender`` and/or ``receiver``. A partition declared
between A and B therefore cannot touch B<->C traffic, because B<->C matches
A/B on neither side.

Determinism
-----------
Every stochastic draw comes from a named stream of
:class:`~niharamesh.clocks.SeededStreams` seeded from that fault's own
``FaultSpec.seed``. Re-running the same specs with the same seeds in the same
call order reproduces every decision exactly.

Time domains
------------
``apply_inbound``/``apply_outbound`` take ``now_ns`` in whatever single domain
the caller has fixed for the fault schedule. The schedule itself is authored in
simulation seconds (``FaultSpec.start_at_s``), so the layer is constructed with
``ns_per_sim_second`` and ``schedule_origin_ns`` and converts once, explicitly.
Two domains are never subtracted without that declared conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from niharamesh.clocks import SeededStreams
from niharamesh.domain.coordination import PeerMessage
from niharamesh.domain.faults import FaultChannel, FaultKind, FaultSpec

__all__ = [
    "ACTIVE_FAULT_NOTE",
    "ActiveFault",
    "DecisionKind",
    "DeliveryDecision",
    "FaultLayer",
    "PendingDelivery",
]

#: Restated by :meth:`FaultLayer.health` so `pnpm doctor` can print it verbatim.
ACTIVE_FAULT_NOTE: Final[str] = (
    "network faults are removable; removing one restores communication, never movement permission"
)

_DEFAULT_DELAY_MIN_NS: Final[float] = 0.0
_DEFAULT_DELAY_MAX_NS: Final[float] = 200_000_000.0
_DEFAULT_REORDER_HOLD_NS: Final[float] = 50_000_000.0
_DEFAULT_SKEW_NS: Final[float] = 5_000_000.0
_MAX_PARKED: Final[int] = 512


class DecisionKind(StrEnum):
    """The complete output vocabulary of the fault layer.

    Note what is absent: there is no ``PERMIT``. A fault can change only *when*
    and *whether* a message travels, never what it authorises.
    """

    DELIVER_AT = "deliver_at"
    DROP = "drop"
    DUPLICATE = "duplicate"
    HOLD = "hold"
    """Parked by a reorder fault; released by :meth:`FaultLayer.drain`."""


@dataclass(frozen=True, slots=True)
class DeliveryDecision:
    """What the transport should do with one message on one direction."""

    kind: DecisionKind
    deliver_at_ns: int = 0
    copies: int = 1
    fault_id: str = ""
    reason: str = ""

    @property
    def dropped(self) -> bool:
        return self.kind is DecisionKind.DROP


@dataclass(frozen=True, slots=True)
class PendingDelivery:
    """A message parked by a reorder fault until its hold elapses.

    ``peer_id`` is the *remote* side: the destination for an ``outbound``
    message, the source for an ``inbound`` one.
    """

    direction: str
    peer_id: str
    message: PeerMessage
    release_at_ns: int


@dataclass(frozen=True, slots=True)
class ActiveFault:
    """A fault whose window covers ``now_ns``, as the doctor sees it."""

    fault_id: str
    kind: FaultKind
    channel: FaultChannel
    sender: str | None
    receiver: str | None
    from_ns: int
    until_ns: int
    expected_invariant: str

    @property
    def silences_traffic(self) -> bool:
        return self.kind in (FaultKind.PARTITION, FaultKind.LOSS)

    def as_dict(self) -> dict[str, object]:
        return {
            "fault_id": self.fault_id,
            "kind": self.kind.value,
            "channel": self.channel.value,
            "sender": self.sender,
            "receiver": self.receiver,
            "from_ns": self.from_ns,
            "until_ns": self.until_ns,
            "silences_traffic": self.silences_traffic,
            "expected_invariant": self.expected_invariant,
        }


_PRIORITY: Final[dict[FaultKind, int]] = {
    FaultKind.PARTITION: 0,
    FaultKind.LOSS: 1,
    FaultKind.REORDER: 2,
    FaultKind.DELAY: 3,
    FaultKind.DUPLICATE: 4,
    FaultKind.CLOCK_SKEW: 5,
}


class FaultLayer:
    """Directed, seeded, removable network faults between peers.

    Constructed with ``local_robot_id`` so that ``apply_inbound`` can name the
    receiving side of a direction without guessing.
    """

    #: A fault layer never exercises authority. Asserted on in tests.
    authority_decisions: Final[int] = 0

    def __init__(
        self,
        specs: tuple[FaultSpec, ...] = (),
        *,
        local_robot_id: str = "",
        ns_per_sim_second: float = 1_000_000_000.0,
        schedule_origin_ns: int = 0,
    ) -> None:
        if ns_per_sim_second <= 0.0:
            raise ValueError("ns_per_sim_second must be positive")
        self._local_robot_id = local_robot_id
        self._ns_per_sim_s = float(ns_per_sim_second)
        self._origin_ns = int(schedule_origin_ns)
        self._specs: dict[str, FaultSpec] = {}
        self._streams: dict[str, SeededStreams] = {}
        self._parked: list[PendingDelivery] = []
        self._counts: dict[DecisionKind, int] = dict.fromkeys(DecisionKind, 0)
        self._park_overflow = 0
        for spec in specs:
            self.add(spec)

    # ---------------------------------------------------------------- registry

    def add(self, spec: FaultSpec) -> None:
        """Register a fault. Re-adding the same id replaces it and reseeds it."""
        self._specs[spec.fault_id] = spec
        self._streams[spec.fault_id] = SeededStreams(base_seed=spec.seed)

    def remove(self, fault_id: str) -> bool:
        """Remove a fault.

        Communication resumes for the affected direction. No permission is
        created, restored or implied - see the module docstring. Messages
        already parked by a reorder fault keep their hold deadline; they are
        transport state, not authority.
        """
        self._streams.pop(fault_id, None)
        return self._specs.pop(fault_id, None) is not None

    def declared_faults(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def active_faults(self, now_ns: int) -> tuple[ActiveFault, ...]:
        """Every fault whose declared window covers ``now_ns``."""
        return tuple(
            ActiveFault(
                fault_id=spec.fault_id,
                kind=spec.target.kind,
                channel=spec.target.channel,
                sender=spec.target.sender,
                receiver=spec.target.receiver,
                from_ns=self._window_start(spec),
                until_ns=self._window_end(spec),
                expected_invariant=spec.expected_invariant,
            )
            for spec in self._sorted_specs()
            if self._in_window(spec, now_ns)
        )

    # --------------------------------------------------------------- decisions

    def apply_inbound(self, msg: PeerMessage, now_ns: int) -> DeliveryDecision:
        """Decide what happens to *msg* arriving from ``msg.envelope.sender``."""
        return self._apply(msg.envelope.sender, self._local_robot_id, msg, now_ns, "inbound")

    def apply_outbound(self, peer_id: str, msg: PeerMessage, now_ns: int) -> DeliveryDecision:
        """Decide what happens to *msg* being sent to *peer_id*."""
        return self._apply(msg.envelope.sender, peer_id, msg, now_ns, "outbound")

    def drain(self, now_ns: int) -> tuple[PendingDelivery, ...]:
        """Release parked messages whose reorder hold has elapsed."""
        due = [p for p in self._parked if p.release_at_ns <= now_ns]
        if due:
            self._parked = [p for p in self._parked if p.release_at_ns > now_ns]
        return tuple(due)

    def parked_count(self) -> int:
        return len(self._parked)

    def clock_skew_ns(self, sender: str, receiver: str, now_ns: int) -> int:
        """Declared clock skew for one direction, in nanoseconds.

        This perturbs the *estimate* a robot is willing to rely on; it never
        touches the real clock on either machine.
        """
        total = 0
        for spec in self._matching(sender, receiver, FaultKind.CLOCK_SKEW, now_ns, None):
            span = float(spec.params.get("skew_ns", _DEFAULT_SKEW_NS))
            if span > 0.0:
                total += round(self._stream(spec).uniform(spec.fault_id, -span, span))
        return total

    # ------------------------------------------------------------------ health

    def health(self, now_ns: int = 0) -> dict[str, object]:
        """Doctor-facing state, including explicitly silenced directions.

        A silenced direction means a *connected but silent* peer as far as the
        operator is concerned. It is reported as ``unavailable``, never rendered
        as "no traffic" (``docs/RESEARCH.md`` QoS finding, AGENTS.md rule 10).
        """
        active = self.active_faults(now_ns)
        silenced = [
            {
                "sender": f.sender or "*",
                "receiver": f.receiver or "*",
                "fault_id": f.fault_id,
                "kind": f.kind.value,
            }
            for f in active
            if f.silences_traffic
        ]
        return {
            "declared": len(self._specs),
            "fault_ids": list(self.declared_faults()),
            "active": [f.as_dict() for f in active],
            "decisions": {kind.value: count for kind, count in self._counts.items()},
            "parked": len(self._parked),
            "park_overflow": self._park_overflow,
            "silenced_directions": silenced,
            "availability": "unavailable" if silenced else "available",
            "authority_decisions": self.authority_decisions,
            "note": ACTIVE_FAULT_NOTE,
        }

    # --------------------------------------------------------------- internals

    def _apply(
        self,
        sender: str,
        receiver: str,
        msg: PeerMessage,
        now_ns: int,
        direction: str,
    ) -> DeliveryDecision:
        kind_str = msg.envelope.kind
        decision = DeliveryDecision(kind=DecisionKind.DELIVER_AT, deliver_at_ns=now_ns)
        applied: list[str] = []
        for spec in self._sorted_specs():
            if spec.target.channel is not FaultChannel.COORDINATION:
                continue
            if spec.target.kind is FaultKind.CLOCK_SKEW:
                continue
            if not self._in_window(spec, now_ns):
                continue
            if not self._targets(spec, sender, receiver, kind_str):
                continue
            step = self._decide(spec, now_ns)
            if step is None:
                continue
            if step.dropped:
                self._counts[DecisionKind.DROP] += 1
                return step
            if step.kind is DecisionKind.HOLD:
                return self._hold(spec, direction, sender, receiver, msg, now_ns)
            applied.append(spec.fault_id)
            decision = DeliveryDecision(
                kind=DecisionKind.DELIVER_AT,
                deliver_at_ns=max(decision.deliver_at_ns, step.deliver_at_ns),
                copies=decision.copies * step.copies,
                fault_id=decision.fault_id or spec.fault_id,
                reason=", ".join(applied),
            )

        kind = DecisionKind.DUPLICATE if decision.copies > 1 else DecisionKind.DELIVER_AT
        self._counts[kind] += 1
        return DeliveryDecision(
            kind=kind,
            deliver_at_ns=decision.deliver_at_ns,
            copies=decision.copies,
            fault_id=decision.fault_id,
            reason=decision.reason or "no fault matched this direction",
        )

    def _hold(
        self,
        spec: FaultSpec,
        direction: str,
        sender: str,
        receiver: str,
        msg: PeerMessage,
        now_ns: int,
    ) -> DeliveryDecision:
        hold_ns = round(float(spec.params.get("hold_ns", _DEFAULT_REORDER_HOLD_NS)))
        if len(self._parked) >= _MAX_PARKED:
            # Bounded park. Overflowing is an explicit, counted drop, not a
            # silent discard and not a crash.
            self._park_overflow += 1
            self._counts[DecisionKind.DROP] += 1
            return DeliveryDecision(
                kind=DecisionKind.DROP,
                fault_id=spec.fault_id,
                reason="reorder park exhausted; message dropped rather than buffered without bound",
            )
        self._parked.append(
            PendingDelivery(
                direction=direction,
                peer_id=receiver if direction == "outbound" else sender,
                message=msg,
                release_at_ns=now_ns + hold_ns,
            )
        )
        self._counts[DecisionKind.HOLD] += 1
        return DeliveryDecision(
            kind=DecisionKind.HOLD,
            deliver_at_ns=now_ns,
            fault_id=spec.fault_id,
            reason=f"parked by reorder fault until +{hold_ns} ns",
        )

    def _decide(self, spec: FaultSpec, now_ns: int) -> DeliveryDecision | None:
        kind = spec.target.kind
        stream = self._stream(spec)
        if kind is FaultKind.PARTITION:
            return DeliveryDecision(
                kind=DecisionKind.DROP,
                fault_id=spec.fault_id,
                reason="direction partitioned",
            )
        if kind is FaultKind.LOSS:
            if stream.chance(spec.fault_id, float(spec.params.get("probability", 1.0))):
                return DeliveryDecision(
                    kind=DecisionKind.DROP,
                    fault_id=spec.fault_id,
                    reason="message lost by declared loss fault",
                )
            return None
        if kind is FaultKind.DUPLICATE:
            if stream.chance(spec.fault_id, float(spec.params.get("probability", 1.0))):
                return DeliveryDecision(
                    kind=DecisionKind.DUPLICATE,
                    deliver_at_ns=now_ns,
                    copies=2,
                    fault_id=spec.fault_id,
                    reason="duplicated by declared duplicate fault",
                )
            return None
        if kind is FaultKind.DELAY:
            low = float(spec.params.get("min_delay_ns", _DEFAULT_DELAY_MIN_NS))
            high = max(low, float(spec.params.get("max_delay_ns", _DEFAULT_DELAY_MAX_NS)))
            offset_ns = round(stream.uniform(spec.fault_id, low, high))
            return DeliveryDecision(
                kind=DecisionKind.DELIVER_AT,
                deliver_at_ns=now_ns + offset_ns,
                fault_id=spec.fault_id,
                reason="delayed by declared delay fault",
            )
        if kind is FaultKind.REORDER:
            if stream.chance(spec.fault_id, float(spec.params.get("probability", 1.0))):
                return DeliveryDecision(
                    kind=DecisionKind.HOLD,
                    deliver_at_ns=now_ns,
                    fault_id=spec.fault_id,
                    reason="reorder fault holds this message back",
                )
            return None
        return None

    def _sorted_specs(self) -> tuple[FaultSpec, ...]:
        return tuple(
            sorted(
                self._specs.values(),
                key=lambda s: (_PRIORITY.get(s.target.kind, 99), s.fault_id),
            )
        )

    def _stream(self, spec: FaultSpec) -> SeededStreams:
        return self._streams[spec.fault_id]

    def _window_start(self, spec: FaultSpec) -> int:
        return self._origin_ns + round(spec.start_at_s * self._ns_per_sim_s)

    def _window_end(self, spec: FaultSpec) -> int:
        return self._origin_ns + round(spec.end_at_s * self._ns_per_sim_s)

    def _in_window(self, spec: FaultSpec, now_ns: int) -> bool:
        return self._window_start(spec) <= now_ns < self._window_end(spec)

    def _matching(
        self,
        sender: str,
        receiver: str,
        kind: FaultKind,
        now_ns: int,
        kind_str: str | None,
    ) -> tuple[FaultSpec, ...]:
        return tuple(
            spec
            for spec in self._sorted_specs()
            if spec.target.kind is kind
            and spec.target.channel is FaultChannel.COORDINATION
            and self._in_window(spec, now_ns)
            and self._targets(spec, sender, receiver, kind_str)
        )

    @staticmethod
    def _targets(spec: FaultSpec, sender: str, receiver: str, kind_str: str | None) -> bool:
        """Directed match. An unset side is a wildcard; the other side must match."""
        target = spec.target
        if target.sender is not None and target.sender != sender:
            return False
        if target.receiver is not None and target.receiver != receiver:
            return False
        return target.message_kind is None or target.message_kind == kind_str

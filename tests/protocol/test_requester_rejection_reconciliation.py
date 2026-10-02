"""Rejection reconciliation: does a rejected attempt withdraw what it collected?

Independent read-only review of the one change made to
``src/niharamesh/coordination/requester.py`` -- the reconciliation branch in
:meth:`ZoneRequester.tick`, which now also fires at ``REJECTED``.

The properties asserted here are the project invariants, not the comment that
shipped with the change (``AGENTS.md`` 4, 5, 6 and 10):

* a requester that ends an attempt holding a promise must withdraw it, or the
  promise outlives the transaction that made it and livelocks its own retry;
* the owner's durable record of "non-executable" lands **before** any message
  withdraws a peer promise -- on every path, including the late-grant one;
* a duplicate grant is evidence of nothing and must not cancel real authority;
* a cancellation belonging to a superseded ``request_version`` must never erase
  a newer promise, and an acknowledgement belonging to one must never settle a
  newer attempt;
* a retry restarts the canonical walk from index zero, its own voter included,
  with one outstanding transaction and one outstanding grant.

Every test drives the real ``ZoneProtocol`` / ``ZoneVoter`` / ``ZoneRequester``.
The only fakes are the journal (in memory, with explicit failure switches) and
the channel (a list that can be dropped from, delayed or duplicated).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from niharamesh.coordination import ZoneProtocol, detect_wait_for_cycle
from niharamesh.coordination.requester import (
    LATE_GRANT_IGNORED,
    TERMINAL_PHASES,
    AdmissionContext,
    ZoneRequester,
)
from niharamesh.coordination.voter import ZoneRecord
from niharamesh.domain.config import ProtocolTiming
from niharamesh.domain.coordination import (
    AcquisitionPhase,
    PeerEnvelope,
    PeerMessage,
    ZoneCancelAckBody,
    ZoneRequestBody,
    build_message,
)
from niharamesh.domain.identity import Membership
from niharamesh.domain.ids import digest_of
from niharamesh.domain.map import MapBoundary, Pose2, WarehouseMap, Zone, ZoneState
from niharamesh.domain.units import TimeDomain

RUN_ID = "run-1"
EPOCH = "e1"
ZONE = "z1"

#: Short deadlines so a *retry* and a *retransmission* are both reachable inside
#: a test. These are the protocol's own knobs, not a relaxation: what is asserted
#: is what happens when the timer expires, not how long anybody waits.
FAST = ProtocolTiming(solicit_timeout_s=0.05, cancel_timeout_s=0.05, release_timeout_s=0.05)
DT_NS = 5_000_000


class FakeJournal:
    """In-memory :class:`~niharamesh.ports.AuthorityJournal` with failure switches.

    ``fail_types`` makes ``append`` return the empty record id that every caller
    of the port in this codebase tests for ("the write did not happen").
    ``raise_types`` models the shipped SQLite journal, which poisons itself and
    *raises* instead (``persistence/journal.py:173``).
    """

    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.corrupt = False
        self.fail_types: set[str] = set()
        self.raise_types: set[str] = set()
        self.on_append: Callable[[str], None] | None = None
        self._n = 0

    def append(self, record_type: str, payload: dict[str, object]) -> str:
        if self.on_append is not None:
            self.on_append(record_type)
        if record_type in self.raise_types:
            raise OSError(f"journal append failed for {record_type!r}")
        if self.corrupt or record_type in self.fail_types:
            return ""
        self._n += 1
        record_id = f"rec-{self._n:04d}"
        self.records.append({"record_id": record_id, "record_type": record_type, **payload})
        return record_id

    def read_all(self) -> list[dict[str, object]]:
        if self.corrupt:
            raise OSError("journal corrupt")
        return list(self.records)

    def latest(self, record_type: str) -> dict[str, object] | None:
        return next((r for r in reversed(self.records) if r["record_type"] == record_type), None)

    def mark_corrupt(self, reason: str) -> None:
        del reason
        self.corrupt = True

    @property
    def healthy(self) -> bool:
        return not self.corrupt

    def close(self) -> None:
        return None

    def of(self, record_type: str) -> list[dict[str, object]]:
        return [r for r in self.records if r["record_type"] == record_type]


def allow(_ctx: AdmissionContext) -> tuple[bool, str]:
    return True, "test_permits"


class Fleet:
    """A whole run in one process, with a controllable in-memory channel."""

    def __init__(
        self,
        robots: Sequence[str],
        zones: Sequence[str],
        *,
        timing: ProtocolTiming | None = None,
    ) -> None:
        members = tuple(sorted(robots))
        self.membership = Membership(
            run_id=RUN_ID,
            epoch=EPOCH,
            members=members,
            digest=digest_of(RUN_ID, EPOCH, *members),
        )
        self.sessions = {r: f"{r}-s1" for r in members}
        self.zone_ids = tuple(zones)
        self.map = WarehouseMap(
            map_id="map-1",
            boundary=MapBoundary(min_x=0.0, min_y=-5.0, max_x=200.0, max_y=5.0),
            zones=tuple(
                Zone(
                    id=z,
                    protected_origin=(10.0 * i - 2.0, 0.0),
                    protected_extent=(4.0, 2.0),
                    entry_pose=Pose2(x=10.0 * i, y=-1.5, theta=0.0),
                    exit_pose=Pose2(x=10.0 * i, y=1.5, theta=0.0),
                )
                for i, z in enumerate(zones)
            ),
        )
        self.journals: dict[str, FakeJournal] = {}
        self.protocols: dict[str, ZoneProtocol] = {}
        self._seq: dict[str, int] = dict.fromkeys(members, 0)
        for robot_id in members:
            journal = FakeJournal()
            self.journals[robot_id] = journal
            protocol = ZoneProtocol(
                robot_id=robot_id,
                session_id=self.sessions[robot_id],
                membership=self.membership,
                journal=journal,
                warehouse_map=self.map,
                timing=timing,
                safety_check=allow,
                time_domain=TimeDomain.LOGICAL,
                session_registry=lambda rid: self.sessions.get(rid),
            )
            protocol.start()
            self.protocols[robot_id] = protocol
        self.inflight: list[tuple[str, PeerMessage]] = []
        self.now_ns = 0
        #: Frames a peer has never sent need a sequence *above* anything the
        #: receiver has already seen, or the replay window discards them as
        #: idempotent duplicates and the test measures nothing.
        self._fresh = 900_000

    def __getitem__(self, robot_id: str) -> ZoneProtocol:
        return self.protocols[robot_id]

    def wire(
        self,
        sender: str,
        target: str,
        kind: str,
        body: object,
        *,
        seq: int | None = None,
        correlation_id: str = "",
    ) -> PeerMessage:
        """Build an arbitrary frame, for hostile, duplicate and reordered traffic."""
        if seq is None:
            self._seq[sender] = self._seq.get(sender, 0) + 1
            seq = self._seq[sender]
        envelope = PeerEnvelope(
            kind=kind,
            sender=sender,
            sender_session=self.sessions[sender],
            run_id=RUN_ID,
            epoch=EPOCH,
            seq=seq,
            sent_at_ns=self.now_ns,
            time_domain=TimeDomain.LOGICAL,
            correlation_id=correlation_id,
        )
        return build_message(envelope, body)  # type: ignore[arg-type]

    def fresh_seq(self) -> int:
        self._fresh += 1
        return self._fresh

    def dispatch(self) -> None:
        for robot_id in sorted(self.protocols):
            for target, message in self.protocols[robot_id].outbox:
                self.inflight.append((target, message))
            self.protocols[robot_id].outbox.clear()

    def deliver_next(self, drop: Callable[[PeerMessage], bool] | None = None) -> bool:
        if not self.inflight:
            return False
        target, message = self.inflight.pop(0)
        if drop is not None and drop(message):
            return True
        self.protocols[target].ingest(message)
        return True

    def deliver_all(self, drop: Callable[[PeerMessage], bool] | None = None) -> int:
        delivered = 0
        while self.deliver_next(drop=drop):
            delivered += 1
        return delivered

    def step(
        self,
        dt_ns: int = DT_NS,
        *,
        drop: Callable[[PeerMessage], bool] | None = None,
    ) -> None:
        self.now_ns += dt_ns
        for robot_id in sorted(self.protocols):
            self.protocols[robot_id].tick(self.now_ns)
        self.dispatch()
        self.deliver_all(drop=drop)

    def settle(self, rounds: int = 20, dt_ns: int = DT_NS, *, drop=None) -> None:
        for _ in range(rounds):
            self.step(dt_ns, drop=drop)
            self.assert_invariants()

    def run_until(self, robot_id: str, phase: AcquisitionPhase, rounds: int = 300) -> None:
        for _ in range(rounds):
            if self[robot_id].phase() is phase:
                return
            self.step()
        raise AssertionError(
            f"{robot_id} did not reach {phase.value} within {rounds} rounds; "
            f"it is {self[robot_id].phase().value}"
        )

    def run_until_predicate(self, robot_id: str, predicate: Callable[[], bool], rounds: int = 300) -> None:
        for _ in range(rounds):
            if predicate():
                return
            self.step()
        raise AssertionError(f"{robot_id} never satisfied the predicate within {rounds} rounds")

    def outstanding(self) -> list[tuple[str, ZoneRecord]]:
        return [
            (robot_id, record)
            for robot_id, protocol in self.protocols.items()
            for record in protocol.voter.outstanding_promises()
        ]

    def holders(self) -> dict[str, str]:
        by_zone: dict[str, set[str]] = {}
        for _voter, record in self.outstanding():
            by_zone.setdefault(record.zone_id, set()).add(record.requester)
        for zone_id, requesters in by_zone.items():
            if len(requesters) > 1:
                raise AssertionError(f"SPLIT GRANT: {zone_id} is promised to {sorted(requesters)}")
        return {zone: next(iter(rs)) for zone, rs in by_zone.items()}

    def record_of(self, voter: str, zone_id: str = ZONE) -> ZoneRecord | None:
        return self[voter].voter.record(zone_id)

    def state_of(self, voter: str, zone_id: str = ZONE) -> ZoneState:
        return self[voter].voter.state_of(zone_id)

    def executable_holder(self, zone_id: str = ZONE) -> str | None:
        allowed = [r for r, p in self.protocols.items() if p.may_enter(zone_id)]
        assert len(allowed) <= 1, f"{zone_id} is executable by {sorted(allowed)}"
        return allowed[0] if allowed else None

    def assert_invariants(self) -> None:
        """One authority per zone, one outstanding grant per robot, no double entry."""
        per_zone: dict[str, set[str]] = {}
        per_requester: dict[str, set[str]] = {}
        for _voter, record in self.outstanding():
            per_zone.setdefault(record.zone_id, set()).add(record.requester)
            per_requester.setdefault(record.requester, set()).add(record.zone_id)
        for zone_id, requesters in per_zone.items():
            assert len(requesters) <= 1, f"{zone_id} promised to {sorted(requesters)}"
        for requester, zones in per_requester.items():
            assert len(zones) <= 1, f"{requester} holds grants for {sorted(zones)}"
        executable: dict[str, set[str]] = {}
        graph: dict[str, str] = {}
        for robot_id, protocol in self.protocols.items():
            graph.update(protocol.wait_for_graph())
            for zone_id in self.zone_ids:
                if protocol.may_enter(zone_id):
                    executable.setdefault(zone_id, set()).add(robot_id)
        for zone_id, robots in executable.items():
            assert len(robots) <= 1, f"{zone_id} is executable by {sorted(robots)}"
        assert detect_wait_for_cycle(graph) is None, "wait-for graph must be acyclic"


def request_for(
    fleet: Fleet, requester: str, zone_id: str = ZONE, version: int = 1, **overrides: object
) -> ZoneRequestBody:
    payload: dict[str, object] = {
        "run_id": RUN_ID,
        "epoch": EPOCH,
        "zone_id": zone_id,
        "requester": requester,
        "requester_session": fleet.sessions[requester],
        "request_version": version,
        "movement": "forward",
        "entry_pose": (0.0, -1.5, 0.0),
        "exit_pose": (0.0, 1.5, 0.0),
        "expires_at_ns": 30_000_000_000,
        "time_domain": TimeDomain.LOGICAL,
        "membership_digest": fleet.membership.digest,
    }
    payload.update(overrides)
    return ZoneRequestBody(**payload)  # type: ignore[arg-type]


def hide_boot_identity(fleet: Fleet, voter: str, peer: str) -> None:
    """Withdraw ``peer``'s boot identity from ``voter``'s required-set hash.

    ``ZoneVoter.solicit`` then refuses with ``NOT_READY`` **and creates no
    record** (``voter.py:664-671``). That is what makes a partial acquisition
    that is then refused reachable from a *consistent* voter set: a voter that
    merely promised the zone to somebody else would be holding a record no
    consistent acquirer could hold, because promising the zone implies having
    already collected every earlier index of the canonical walk.
    """
    assert peer in fleet[voter]._sessions
    del fleet[voter]._sessions[peer]


def restore_boot_identity(fleet: Fleet, voter: str, peer: str) -> None:
    fleet[voter]._sessions[peer] = fleet.sessions[peer]


def make_partial_then_refused(fleet: Fleet, requester: str = "r2", *, rounds: int = 80) -> None:
    """Drive ``requester`` into the state the reviewed branch is about.

    ``r1`` and ``r2``'s own voter grant; ``r3`` refuses without recording
    anything. A real partial acquisition that ends in a refusal, built only from
    public protocol calls plus one withheld session-table entry.
    """
    hide_boot_identity(fleet, "r3", "r3")
    fleet[requester].begin_acquire(ZONE)

    def settled() -> bool:
        acq = fleet[requester].requester.active
        return bool(acq and acq.phase is AcquisitionPhase.REJECTED)

    try:
        fleet.run_until_predicate(requester, settled, rounds=rounds)
    finally:
        restore_boot_identity(fleet, "r3", "r3")

    acq = fleet[requester].requester.active
    assert acq is not None
    assert acq.request.request_version == 1, "precondition: the first attempt, version 1"
    assert acq.ever_granted == {"r1", "r2"}, (
        f"precondition: it really did collect promises, got {sorted(acq.ever_granted)}"
    )
    assert acq.reject_reason is not None


def make_refused_with_nothing_held(fleet: Fleet, requester: str = "r3", *, rounds: int = 80) -> None:
    """Drive ``requester`` to ``REJECTED`` while it holds nothing at all.

    This is the *other* route to the terminal state -- refused at canonical index
    zero -- and the only one that leaves ``durably_non_executable`` false. It is
    the state the reviewed condition adds a branch for.
    """
    fleet["r2"].begin_acquire(ZONE)
    fleet.run_until("r2", AcquisitionPhase.GRANTED)
    fleet[requester].begin_acquire(ZONE)

    def settled() -> bool:
        acq = fleet[requester].requester.active
        return bool(acq and acq.phase is AcquisitionPhase.REJECTED)

    fleet.run_until_predicate(requester, settled, rounds=rounds)
    acq = fleet[requester].requester.active
    assert acq is not None
    assert acq.held() == (), "precondition: refused before collecting anything"
    assert acq.durably_non_executable is False, (
        f"precondition: nothing was cancelled, got cancel_seq={acq.cancel_seq}"
    )


def bring_to_granted(fleet: Fleet, requester: str = "r2") -> None:
    """Let the retry win the complete grant set from a clean, consistent state."""
    fleet.run_until(requester, AcquisitionPhase.GRANTED)


def capture_duplicate_grant(fleet: Fleet, voter: str, request: ZoneRequestBody) -> PeerMessage:
    """Make ``voter`` issue a genuine grant for a transaction it already holds."""
    outcome = fleet[voter].voter.solicit(request, fleet.now_ns)
    assert outcome.grant is not None, "the duplicate grant must actually be issued"
    return fleet.wire(
        voter,
        request.requester,
        "zone_grant",
        fleet[voter].voter.to_wire(request, outcome.grant),
        seq=fleet.fresh_seq(),
    )


class SolicitationRecorder:
    """Records which voter each solicitation went to, in emission order.

    An observation hook, not a decision fake: it wraps the real
    ``ZoneRequester.tick`` and only reads what the real state machine produced.
    """

    def __init__(self) -> None:
        self.solicits: list[tuple[str, str, int]] = []
        self._original = ZoneRequester.tick

    def __enter__(self) -> SolicitationRecorder:
        recorder = self

        def spy(requester: ZoneRequester, now_ns: int) -> list:
            acq = requester.active
            phase = acq.phase if acq is not None else None
            actions = recorder._original(requester, now_ns)
            for action in actions:
                if action.kind == "solicit":
                    assert phase is not None
                    recorder.solicits.append((requester.robot_id, action.target, phase.name))
            return actions

        ZoneRequester.tick = spy  # type: ignore[method-assign]
        return self

    def __exit__(self, *exc: object) -> None:
        ZoneRequester.tick = self._original  # type: ignore[method-assign]


# ===================================================================== Q1
# Reachability: can an attempt even end REJECTED while it holds promises?


def test_a_refused_partial_acquisition_withdraws_every_promise_it_collected() -> None:
    """REQUIRED: the promises a failed attempt collected must not survive it.

    This is the state the reviewed branch is about, built from the real classes:
    ``r2`` walks the canonical order, is granted by ``r1`` and by its own voter,
    and is refused at ``r3``. Whatever it collected must be withdrawn everywhere.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    fleet.settle(rounds=10)

    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.ever_granted == {"r1", "r2"}, "precondition: it really did collect promises"
    assert acq.held() == (), "precondition: the settlement emptied the grant set"
    for voter in ("r1", "r2", "r3"):
        record = fleet.record_of(voter)
        if record is not None:
            assert record.requester != "r2", (
                f"{voter} still holds r2's promise: {record.state.value} v{record.request_version}"
            )
    assert fleet.holders() == {}, "no promise may survive the attempt that made it"


def test_the_retry_after_a_rejection_is_not_livelocked_by_the_failed_attempt() -> None:
    """REQUIRED: a fresh ``request_version`` must be able to win after a refusal.

    The claim under review is that a surviving promise would refuse the retry with
    ``ZONE_PROMISED`` -- same zone, same robot -- forever. So drive the retry to
    a complete grant set rather than only inspecting the bookkeeping.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    history = fleet["r2"].requester.history
    versions = [acq.request.request_version for acq in history]
    assert max(versions) > 1, f"the retry must be a new version, got {versions}"
    assert versions[0] == 1, "the audit trail must start at the refused attempt"

    active = fleet["r2"].requester.active
    assert active is not None
    assert active.held() == fleet["r2"].required_voters("r2"), (
        "the retry must collect the whole set, including its own voter"
    )
    assert fleet.executable_holder(ZONE) == "r2"
    for refusal in (acq.last_refusal() for acq in history):
        if refusal is not None:
            assert refusal.reason.value != "zone_promised" or refusal.blocking_requester != "r2", (
                "r2 was refused because of its own stale promise: the livelock"
            )


def test_rejected_is_never_reached_while_a_promise_is_still_outstanding() -> None:
    """REQUIRED: ``REJECTED`` means "collected nothing that is still held".

    Enumerated over adverse schedules -- refusals, cancellations, and dropped
    grant / cancel / acknowledgement / occupancy frames -- with the reconciliation
    set sampled at every tick. If ``REJECTED`` ever coincides with a voter the
    owner still owes a reconciliation to, the terminal state is lying to the
    retry and to the operator.
    """
    offending: list[str] = []

    def check(fleet: Fleet, label: str) -> None:
        for robot_id in sorted(fleet.protocols):
            acq = fleet[robot_id].requester.active
            if acq is None or acq.phase is not AcquisitionPhase.REJECTED:
                continue
            owed = fleet[robot_id].requester.cancel_targets(acq)
            if owed:
                offending.append(f"{label}/{robot_id}: REJECTED still owes {owed}")
            unacked = set(acq.ever_granted) - set(acq.cancel_acked)
            if unacked:
                offending.append(f"{label}/{robot_id}: REJECTED unacknowledged by {sorted(unacked)}")

    schedules: dict[str, Callable[[PeerMessage], bool] | None] = {
        "clean": None,
        "lose_cancel": lambda m: m.envelope.kind == "zone_cancel" and m.envelope.sender == "r2",
        "lose_ack": lambda m: m.envelope.kind == "zone_cancel_ack",
        "lose_grant": lambda m: m.envelope.kind == "zone_grant",
        "lose_occupy": lambda m: m.envelope.kind == "zone_occupy",
    }
    for seed in ("partial", "empty"):
        for name, drop in schedules.items():
            fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
            if seed == "partial":
                make_partial_then_refused(fleet)
            else:
                make_refused_with_nothing_held(fleet)
            for _ in range(60):
                check(fleet, f"{seed}/{name}")
                fleet.step(drop=drop)
                fleet.assert_invariants()

    assert not offending, "REJECTED with an unreconciled promise:\n" + "\n".join(offending)


def test_the_rejected_branch_cannot_emit_a_message_the_durable_branch_would_not() -> None:
    """REQUIRED: a ``REJECTED`` reconciliation set is empty, so the branch is inert.

    The reviewed condition adds ``phase is REJECTED`` to a branch whose entire
    job is to iterate ``cancel_targets``. The only thing it can therefore change
    is whether an *empty* set is iterated. This asserts that property over the
    same adverse sweep, and that the new-only condition never holds with a
    non-empty set -- which is what would make it a behavioural change at all.
    """
    disagreements: list[str] = []
    inert: list[str] = []

    def check(fleet: Fleet, label: str) -> None:
        for robot_id in sorted(fleet.protocols):
            acq = fleet[robot_id].requester.active
            if acq is None:
                continue
            targets = fleet[robot_id].requester.cancel_targets(acq)
            durable = acq.durably_non_executable and acq.phase is not AcquisitionPhase.RELEASING
            reviewed = acq.phase is AcquisitionPhase.REJECTED or durable
            if reviewed and not durable:
                if targets:
                    disagreements.append(f"{label}/{robot_id}: non-empty set {targets} at REJECTED")
                else:
                    inert.append(f"{label}/{robot_id}")

    for index, drop in enumerate(
        (
            None,
            lambda m: m.envelope.kind == "zone_cancel",
            lambda m: m.envelope.kind == "zone_grant",
            lambda m: m.envelope.kind == "zone_cancel_ack",
        )
    ):
        for seed in ("partial", "empty"):
            fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
            if seed == "partial":
                make_partial_then_refused(fleet)
            else:
                make_refused_with_nothing_held(fleet)
            # Sampled *before* the step as well as after it: the interesting state
            # is the one a settled ``REJECTED`` leaves behind, and the retry
            # replaces it on the very next tick.
            check(fleet, f"schedule-{index}/{seed}/settled")
            for _ in range(60):
                fleet.step(drop=drop)
                check(fleet, f"schedule-{index}/{seed}")
                fleet.assert_invariants()

    assert not disagreements, "\n".join(disagreements)
    assert inert, "precondition: the sweep really did observe the new-only condition"


# ===================================================================== Q2
# Durability of the owner's own cancellation.


def test_the_owners_cancellation_is_journalled_before_any_cancel_frame_exists() -> None:
    """REQUIRED: durable first, then peer reconciliation -- measured, not assumed.

    The journal is asked to snapshot the owner's outbox at the instant it is
    asked to write the cancellation. Any ``zone_cancel`` frame already visible at
    that instant is a message that withdrew a peer promise before the owner had
    recorded that it was non-executable.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    observed: list[tuple[str, int]] = []

    def snapshot(kind: str) -> None:
        # Anything already queued *or* dispatched would have withdrawn a peer
        # promise before the owner recorded that it was non-executable.
        if kind == "cancel":
            observed.append((kind, len(fleet["r2"].outbox) + len(fleet.inflight)))

    fleet.journals["r2"].on_append = snapshot
    fleet["r2"].requester.cancel("operator_abort", now_ns=fleet.now_ns)
    fleet.journals["r2"].on_append = None

    assert observed, "the cancellation must be journalled"
    assert observed[0] == ("cancel", 0), (
        "a cancellation frame was already queued or in flight when the owner "
        f"recorded its non-executability: {observed}"
    )
    cancels = fleet.journals["r2"].of("cancel")
    assert cancels and cancels[-1]["durably_non_executable"] is True
    assert cancels[-1]["reason"] == "operator_abort"
    acq = fleet["r2"].requester.active
    assert acq is not None and acq.durably_non_executable is True
    fleet.settle(rounds=8)
    assert fleet.holders() == {}, "and the reconciliation then really does reach every voter"


def test_a_failed_cancellation_withdraws_no_peer_promise() -> None:
    """REQUIRED: if the owner's write fails, no peer may be told anything.

    ``requester.cancel`` tests the record id. This pins that the test is load
    bearing: with the write refused the transaction stays non-executable *and*
    every peer keeps its promise, which is the honest state -- the owner simply
    never got to say anything.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    fleet.journals["r2"].fail_types.add("cancel")
    assert fleet["r2"].requester.cancel("operator_abort", now_ns=fleet.now_ns) is False
    assert "CANCEL_NOT_DURABLE" in [e.kind for e in fleet["r2"].events]

    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.durably_non_executable is False
    assert acq.cancel_sent == set(), "nothing may be announced after a failed write"
    fleet["r2"].requester.tick(fleet.now_ns)
    fleet.dispatch()
    assert not [m for _t, m in fleet.inflight if m.envelope.kind == "zone_cancel"]
    for voter in ("r1", "r2", "r3"):
        record = fleet.record_of(voter)
        if record is not None:
            assert record.requester == "r2", "a peer promise must survive a failed write"


def test_a_late_grant_cancellation_is_journalled_before_any_promise_is_withdrawn() -> None:
    """REQUIRED: the late-grant path obeys the same durable-first discipline.

    ``ZoneRequester.cancel`` writes, tests the record id, and only then lets a
    message leave (``requester.py:645-666``). ``ZoneRequester._answer_late_grant``
    performs the same write on the same fault and **discards the result**
    (``requester.py:538-550``): it sets ``durably_non_executable = True``
    regardless. A late grant is the one moment a robot that is about to enter is
    told by a peer that its transaction is dead, so this is exactly where a
    non-durable cancellation frees an aisle nobody had durably given up.

    Both failure modes are exercised: the port's empty record id, and the shipped
    SQLite journal's ``JournalCorruptError``.
    """
    for mode in ("empty", "raise"):
        fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
        make_partial_then_refused(fleet)
        bring_to_granted(fleet)

        request = fleet["r2"].requester.active.request
        late = capture_duplicate_grant(fleet, "r1", request)
        if mode == "empty":
            fleet.journals["r2"].fail_types.add("cancel")
        else:
            fleet.journals["r2"].raise_types.add("cancel")

        escaped: list[BaseException] = []
        try:
            fleet["r2"].ingest(late)
        except Exception as exc:  # the failure mode under test, deliberately caught
            escaped.append(exc)

        acq = fleet["r2"].requester.active
        assert acq is not None, mode
        reported = repr(escaped[0]) if escaped else "no exception: the port returned an empty id"
        assert acq.durably_non_executable is False, (
            f"[{mode}] a late-grant cancellation was declared durable with no record on "
            f"disk (the journal said: {reported})"
        )
        fleet["r2"].requester.tick(fleet.now_ns)
        fleet.dispatch()
        assert not [m for _t, m in fleet.inflight if m.envelope.kind == "zone_cancel"], (
            f"[{mode}] a peer promise is being withdrawn with no durable owner record"
        )


def test_a_lost_cancellation_is_re_sent_until_it_is_acknowledged() -> None:
    """REQUIRED: a cancellation nobody heard is a promise nobody withdrew.

    ``cancel_timeout_s`` is plumbed all the way into ``ZoneRequester`` and then
    never read, so a single lost ``zone_cancel`` is the end of the
    reconciliation: the peer keeps the promise forever and the owner waits in
    ``CANCELLING`` forever. ``CANCELLING`` is not a terminal phase, so the
    requester also refuses to open a replacement transaction -- the zone is
    wedged for that requester with no recovery the agent can take.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    lost_to_r1: list[str] = []
    cancels_to_r1: list[int] = []

    def drop_first_r1_cancel(message: PeerMessage) -> bool:
        # Observed **on the wire**, at the point the frame is handed to the
        # transport, rather than by inspecting ``Fleet.inflight`` after the fact.
        # ``step`` dispatches and then drains ``inflight`` completely, so a test
        # that inspects the queue afterwards is inspecting an empty list and can
        # never observe a retransmission at all -- it would fail however correctly
        # the protocol behaved.
        if message.envelope.kind == "zone_cancel" and message.envelope.sender == "r2":
            cancels_to_r1.append(message.body.cancel_seq)  # type: ignore[union-attr]
            if "r1" not in lost_to_r1:
                lost_to_r1.append("r1")
                return True
        return False

    fleet["r2"].cancel("operator_abort")
    fleet.dispatch()
    fleet.inflight.clear()
    fleet.settle(rounds=4)
    first_pass = len(cancels_to_r1)

    fleet.settle(rounds=80, drop=drop_first_r1_cancel)  # 16x cancel_timeout_s

    resent = len(cancels_to_r1) > first_pass
    assert resent, (
        "the cancellation to r1 was never re-sent: "
        f"r1 held {fleet.state_of('r1').value} and r2 is {fleet['r2'].phase().value} "
        "with no way to re-request the zone"
    )
    assert fleet.state_of("r1") is ZoneState.FREE
    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.phase is AcquisitionPhase.CANCELLED, (
        "a settled cancellation must leave the robot able to ask again, not wedged in CANCELLING"
    )


# ===================================================================== Q3
# Reconciliation completeness, duplicate acknowledgements, and late grants.


def test_a_grant_that_arrives_after_the_rejection_still_converges_the_peer_record() -> None:
    """REQUIRED: a grant that lands after the owner settled must not be authority,
    and the peer that issued it must still be told to withdraw.

    The duplicate is captured while ``r1`` legitimately holds the promise, so it
    is a genuine grant frame from a real voter -- not a forgery -- held back until
    the owner has already reached ``REJECTED``.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    hide_boot_identity(fleet, "r3", "r3")
    fleet["r2"].begin_acquire(ZONE)
    # Both of the first two grants can land inside one delivery, so the predicate
    # only requires that ``r1`` has granted at all.
    fleet.run_until_predicate(
        "r2",
        lambda: bool((a := fleet["r2"].requester.active) and "r1" in a.ever_granted),
        rounds=60,
    )
    request = fleet["r2"].requester.active.request
    late = capture_duplicate_grant(fleet, "r1", request)

    fleet.run_until_predicate("r2", lambda: fleet["r2"].phase() is AcquisitionPhase.REJECTED, rounds=200)
    acq = fleet["r2"].requester.active
    assert acq is not None and acq.request.request_version == 1
    restore_boot_identity(fleet, "r3", "r3")

    fleet["r2"].ingest(late)
    assert LATE_GRANT_IGNORED in [e.kind for e in fleet["r2"].events], (
        "a grant arriving after the rejection must be recorded as such"
    )
    assert acq.phase is not AcquisitionPhase.GRANTED
    assert acq.durably_non_executable is True
    assert "r1" not in acq.held(), "a late grant must never become authority"
    assert fleet.executable_holder(ZONE) is None

    fleet.settle(rounds=10)
    for voter in ("r1", "r2", "r3"):
        record = fleet.record_of(voter)
        assert record is None or record.requester != "r2", (
            f"{voter} kept r2's promise after issuing a grant the owner had abandoned"
        )
    assert fleet.holders() == {}


def test_a_duplicate_acknowledgement_is_idempotent_and_a_missing_one_is_never_assumed() -> None:
    """REQUIRED: duplicates change nothing, and a silence is not an acknowledgement.

    A ``zone_cancel_ack`` that never arrives must leave the owner visibly
    un-reconciled, must not be read as agreement, and must not arm the retry --
    otherwise the owner would move on while a peer still holds its promise.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    fleet["r2"].cancel("operator_abort")
    fleet.dispatch()
    cancels = list(fleet.inflight)
    fleet.inflight.clear()
    assert len(cancels) == 2, f"two peer cancellations expected, got {len(cancels)}"
    # Every peer except r1 hears the cancellation; r1 hears nothing at all.
    for target, message in cancels:
        if message.envelope.kind == "zone_cancel" and target == "r1":
            continue
        fleet[target].ingest(message)
    fleet.dispatch()
    acks = [(t, m) for t, m in fleet.inflight if m.envelope.kind == "zone_cancel_ack"]
    fleet.inflight.clear()
    assert len(acks) == 1, f"exactly one peer heard the cancellation, got {len(acks)}"
    others = list(acks)

    # The silence: r1 never hears the cancellation, so it never answers.
    for target, message in others:
        fleet[target].ingest(message)
    fleet.settle(rounds=8)
    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.phase is AcquisitionPhase.CANCELLING, (
        "an unacknowledged cancellation must not be reported as settled"
    )
    assert "r1" not in acq.cancel_acked
    assert fleet.state_of("r1") is ZoneState.PROMISED, (
        "r1 still holds the promise r2 durably gave up, and nobody has been told"
    )
    assert fleet["r2"].requester.retry_due(fleet.now_ns) is False, (
        "a retry must not be armed while a peer still holds the old promise"
    )

    # r1's acknowledgement, built from the same fields ``ZoneVoter.apply_cancel``
    # would have answered with had the frame reached it: the owner's identity, the
    # owner's ``cancel_seq``, r1's own session, and ``no_record=False``.
    active = fleet["r2"].requester.active
    assert active is not None
    from_r1_ack = ZoneCancelAckBody(
        zone_id=ZONE,
        requester=active.request.requester,
        requester_session=active.request.requester_session,
        request_version=active.request.request_version,
        cancel_seq=active.cancel_seq,
        voter="r1",
        voter_session=fleet.sessions["r1"],
        no_record=False,
    )

    # The duplicates: the same acknowledgement three times changes nothing.
    for _ in range(3):
        fleet["r2"].ingest(fleet.wire("r1", "r2", "zone_cancel_ack", from_r1_ack, seq=fleet.fresh_seq()))
        for target, message in others:
            fleet[target].ingest(message)
    fleet.settle(rounds=4)

    # r1 never heard the cancellation, so its own record is still there; the owner
    # has nevertheless been told. Recorded honestly rather than papered over.
    assert fleet.state_of("r1") is ZoneState.PROMISED

    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.cancel_acked == {"r1", "r2", "r3"}, (
        f"every voter that ever granted must acknowledge, including the self "
        f"voter whose acknowledgement is applied in process: {sorted(acq.cancel_acked)}"
    )
    assert acq.phase is AcquisitionPhase.CANCELLED
    written = [
        r
        for r in fleet.journals["r2"].of("cancel")
        if r.get("owner") == "r2" and r.get("reason") == "operator_abort"
    ]
    assert len(written) == 1, (
        f"a repeated acknowledgement must not write a second durable cancellation: {written}"
    )


# ===================================================================== Q4
# A superseded version's messages must not touch a newer attempt.


def test_a_delayed_cancellation_from_a_superseded_version_cannot_erase_a_newer_promise() -> None:
    """REQUIRED: an old ``zone_cancel`` must not free a zone promised to a newer
    attempt by the *same* robot.

    Delivered deliberately out of order: the v1 cancellation is written first and
    delivered after the v2 attempt already holds promises under a fresh
    ``request_version``. Identity, not arrival order, has to be what protects the
    newer promise.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    v1 = fleet["r2"].requester.active
    assert v1 is not None
    stale = fleet["r2"].requester.cancel_body(v1)
    assert stale.request_version == 1
    assert stale.grant_id == v1.request.grant_id

    hide_boot_identity(fleet, "r3", "r3")
    fleet.run_until_predicate(
        "r2",
        lambda: bool(
            (a := fleet["r2"].requester.active)
            and a.request.request_version == 2
            and a.ever_granted == {"r1", "r2"}
        ),
        rounds=200,
    )
    record = fleet.record_of("r1")
    assert record is not None
    assert record.request_version == 2, "precondition: r1 now holds the v2 promise"
    newer_grant = record.grant_id

    for voter in ("r1", "r2"):
        fleet[voter].ingest(fleet.wire("r2", voter, "zone_cancel", stale, seq=fleet.fresh_seq()))

    after = fleet.record_of("r1")
    assert after is not None, "a stale cancellation erased a live promise"
    assert after.request_version == 2
    assert after.grant_id == newer_grant
    assert after.state is ZoneState.PROMISED

    restore_boot_identity(fleet, "r3", "r3")
    fleet.run_until("r2", AcquisitionPhase.GRANTED)
    assert fleet.executable_holder(ZONE) == "r2", "the newer attempt lost its grant set"

    # And a third party is still kept out.
    refused = fleet["r1"].voter.solicit(request_for(fleet, "r1"), fleet.now_ns)
    assert refused.grant is None
    assert refused.reason is not None and refused.reason.value == "zone_promised"


def test_an_acknowledgement_from_a_superseded_version_cannot_settle_the_new_attempt() -> None:
    """REQUIRED: a stale ``zone_cancel_ack`` must not settle a newer attempt.

    Both versions number their first cancellation ``cancel_seq == 1``, so the
    sequence number alone cannot separate them. The transaction identity has to.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    stale_ack = ZoneCancelAckBody(
        zone_id=ZONE,
        requester="r2",
        requester_session=fleet.sessions["r2"],
        request_version=1,
        cancel_seq=1,
        voter="r1",
        voter_session=fleet.sessions["r1"],
        no_record=False,
    )

    fleet.run_until_predicate(
        "r2",
        lambda: bool(
            (a := fleet["r2"].requester.active) and a.request.request_version == 2 and "r1" in a.held()
        ),
        rounds=200,
    )
    acq = fleet["r2"].requester.active
    assert acq is not None
    before = acq.held()
    assert acq.cancel_seq == 0

    fleet["r2"].ingest(fleet.wire("r1", "r2", "zone_cancel_ack", stale_ack, seq=fleet.fresh_seq()))
    assert fleet["r2"].requester.active is acq
    assert acq.held() == before, "a stale acknowledgement flipped a live grant to cancelled"
    assert fleet["r2"].phase() not in (AcquisitionPhase.CANCELLED, AcquisitionPhase.REJECTED)
    assert fleet.executable_holder(ZONE) != "r2" or acq.all_slots_granted()

    fleet.settle(rounds=10)
    assert fleet["r2"].requester.active is not None
    assert fleet["r2"].phase() is AcquisitionPhase.GRANTED
    assert fleet.executable_holder(ZONE) == "r2"


# ===================================================================== Q5
# The retry restarts the canonical walk; nothing is pre-reserved.


def test_a_retry_restarts_the_canonical_walk_from_index_zero_including_its_own_voter() -> None:
    """REQUIRED (``AGENTS.md`` 6): the retry is a fresh walk in the global order.

    Four voters, so the requester's own voter is *not* first: ``r2`` is at index
    one. One solicitation is held back and released late, so the retry is also
    run under reordering. Asserted: the slot list is the global canonical order,
    the self voter sits at its own index, the held set is always a prefix of that
    order, and exactly one transaction is ever outstanding.
    """
    fleet = Fleet(["r1", "r2", "r3", "r4"], [ZONE], timing=FAST)
    order = fleet["r2"].required_voters("r2")
    assert order == ("r1", "r2", "r3", "r4")

    hide_boot_identity(fleet, "r4", "r4")
    fleet["r2"].begin_acquire(ZONE)
    fleet.run_until_predicate("r2", lambda: fleet["r2"].phase() is AcquisitionPhase.REJECTED, rounds=120)
    restore_boot_identity(fleet, "r4", "r4")

    delayed: list[PeerMessage] = []

    def hold_one_solicit_to_r4(message: PeerMessage) -> bool:
        if (
            message.envelope.kind == "zone_request"
            and message.body.zone_id == ZONE
            and message.body.request_version == 2
            and message.envelope.sender == "r2"
            and len(delayed) == 0
        ):
            delayed.append(message)
            return True
        return False

    problems: list[str] = []
    with SolicitationRecorder() as recorder:
        for _ in range(400):
            acq = fleet["r2"].requester.active
            if acq is not None:
                if [s.voter for s in acq.slots] != list(order):
                    problems.append(f"slot order {[s.voter for s in acq.slots]}")
                if [s.is_self for s in acq.slots] != [v == "r2" for v in order]:
                    problems.append("self voter is not at its own canonical index")
                if acq.held() != order[: len(acq.held())]:
                    problems.append(f"held {acq.held()} is not a prefix of {order}")
                if len(acq.held()) > len(order):
                    problems.append("more grants than there are voters")
                if fleet["r2"].requester.held_grants != len(acq.held()):
                    problems.append("held_grants disagrees with the slot set")
            live = [a for a in fleet["r2"].requester.history if a.phase not in TERMINAL_PHASES]
            if len(live) > 1:
                problems.append(f"two outstanding transactions: {[a.phase.name for a in live]}")
            if fleet["r2"].phase() is AcquisitionPhase.GRANTED:
                break
            fleet.step(drop=hold_one_solicit_to_r4)
            # Release the held solicitation a few ticks after it was sent, so the
            # retry really does run against reordered delivery.
            if delayed and len(recorder.solicits) % 3 == 0:
                fleet["r4"].ingest(delayed.pop(0))
            fleet.assert_invariants()

    assert not problems, "\n".join(sorted(set(problems)))
    assert fleet["r2"].phase() is AcquisitionPhase.GRANTED
    active = fleet["r2"].requester.active
    assert active is not None
    assert active.request.request_version == 2
    assert active.held() == order
    assert fleet.executable_holder(ZONE) == "r2"

    # The self voter was solicited at its own index, in the global order.
    # A pending slot is re-solicited every solicit_timeout while its grant is in
    # flight, so consecutive repeats of the same target are one step, not two.
    own: list[str] = []
    for robot, target, _phase in recorder.solicits:
        if robot != "r2":
            continue
        if not own or own[-1] != target:
            own.append(target)
    assert own == list(order), (
        f"the retry must walk the whole canonical order, including its own voter at index one: {own}"
    )
    assert own[order.index("r2")] == "r2", "never pre-reserve your own grant"
    graph: dict[str, str] = {}
    for _robot_id, protocol in sorted(fleet.protocols.items()):
        graph.update(protocol.wait_for_graph())
    assert fleet["r2"].detect_deadlock(graph) is None


# ===================================================================== Q6
# A duplicate grant for a transaction that has already been granted or entered.


def test_a_duplicate_grant_does_not_free_an_aisle_that_is_already_occupied() -> None:
    """REQUIRED (``AGENTS.md`` 4): occupancy is not undone by a stale message.

    The duplicate is captured while ``r1`` legitimately holds the promise, so it
    is a real grant frame, held back until after physical entry has been declared
    at every voter. ``ZoneVoter.apply_cancel`` refuses a pre-entry cancellation
    for an ``OCCUPIED`` zone, so the aisle must stay held and a competing entrant
    must still be refused.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    request = fleet["r2"].requester.active.request
    duplicate = capture_duplicate_grant(fleet, "r1", request)

    assert fleet["r2"].mark_entered(ZONE) is True
    fleet.settle(rounds=4)
    for voter in ("r1", "r2", "r3"):
        assert fleet.state_of(voter) is ZoneState.OCCUPIED, voter

    fleet["r2"].ingest(duplicate)
    assert LATE_GRANT_IGNORED in [e.kind for e in fleet["r2"].events]
    fleet.settle(rounds=8)

    for voter in ("r1", "r2", "r3"):
        assert fleet.state_of(voter) is ZoneState.OCCUPIED, (
            f"{voter} let a stale message empty an aisle somebody is standing in"
        )
    assert fleet.holders() == {ZONE: "r2"}, "the zone must still have exactly one holder"
    assert fleet.executable_holder(ZONE) is None, "entry permission is spent, not authority"

    # A competing entrant is refused on the same facts.
    refused = fleet["r1"].voter.solicit(request_for(fleet, "r1"), fleet.now_ns)
    assert refused.grant is None
    assert refused.reason is not None and refused.reason.value == "zone_promised"
    assert fleet["r3"].requester.retry_due(fleet.now_ns) in (True, False)


def test_a_duplicate_grant_does_not_cancel_a_transaction_that_has_already_entered() -> None:
    """REQUIRED: a duplicate grant is evidence of nothing.

    ``ZoneRequester.cancel`` refuses a cancellation once a robot has declared
    physical entry (``requester.py:629-640``): the only honest way out is
    exit-then-release. ``ZoneRequester.on_grant`` routes *any* grant that arrives
    outside ``ACQUIRING`` into ``_answer_late_grant``, which sets
    ``durably_non_executable = True`` and moves the transaction to
    ``CANCELLING`` -- for ``GRANTED``, ``OCCUPIED`` and ``RELEASING`` alike.

    That is the distinction the two duplicate-grant cases turn on, and it is
    currently not made. With occupancy declared, ``test_a_duplicate_grant_does_
    not_free_an_aisle_that_is_already_occupied`` shows the peers still hold the
    zone. Without occupancy declared there is nothing on the peer side to refuse,
    so the whole protection rests on the owner's own record -- which is exactly
    what this test says must not be discardable by a duplicated frame.
    """
    fleet = Fleet(["r1", "r2", "r3"], [ZONE], timing=FAST)
    make_partial_then_refused(fleet)
    bring_to_granted(fleet)

    request = fleet["r2"].requester.active.request
    duplicate = capture_duplicate_grant(fleet, "r1", request)
    assert fleet["r2"].phase() is AcquisitionPhase.GRANTED, "precondition: entry permission"

    fleet["r2"].ingest(duplicate)
    assert LATE_GRANT_IGNORED in [e.kind for e in fleet["r2"].events], (
        "a duplicate grant must be recorded as ignored"
    )
    acq = fleet["r2"].requester.active
    assert acq is not None
    assert acq.durably_non_executable is False, (
        "a duplicated grant frame revoked the entry permission of a transaction nobody withdrew"
    )
    assert acq.phase is AcquisitionPhase.GRANTED, (
        f"a transaction that is GRANTED moved to {acq.phase.value} because a peer "
        "repeated a grant it had already answered"
    )
    fleet.settle(rounds=8)
    assert fleet.executable_holder(ZONE) == "r2"
    assert fleet.holders() == {ZONE: "r2"}

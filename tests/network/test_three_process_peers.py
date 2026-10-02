"""Three robots, three OS processes, three real loopback sockets.

This is the decentralisation claim under test. Nothing here may route through a
central component, so:

* three ``multiprocessing`` processes are spawned (Windows uses ``spawn``, so each
  child re-imports the module - these are genuinely separate interpreters, not
  threads or greenlets);
* each child binds its own port and dials only the two peers its ``Membership``
  declares, directly;
* each child records the *observed* socket address every inbound peer connected
  from, and the parent asserts those addresses are the other two robots' ports
  and nothing else - which is falsifiable evidence against a relay;
* the ``os.getpid()`` values are asserted distinct, so "separate processes" is
  measured rather than assumed.

Phase 2 partitions A<->B and asserts B<->C keeps carrying real messages.

The shutdown barrier
--------------------
Every phase-2 assertion is made against a snapshot of ``transport.health()``
taken *by the robot itself*. That makes the snapshot's instant the only thing
that decides the result, so it must not be a moment when a peer has legitimately
gone: ``transport.stop()`` closes every peer socket, and a robot that has closed
its socket is truthfully ``disconnected`` / ``availability: "unavailable"``. The
three children are not phase-synchronised - each starts its own clock after its
own import and observes the phase-2 command on a 20 ms poll - so without a
barrier one child can finish, exit, and be sampled as a dead link by a peer that
has not finished yet. That was measured, not hypothesised: under CPU load it
fired in 5 of 45 runs, and the departed peer's own report records the closing
stacks ``PeerTransportServer.stop -> PeerClient.stop -> _detach -> close``.

So no robot leaves until every robot has taken its phase-2 snapshot, and the
parent asserts that invariant on the run artifacts before releasing them. The
release is a hang guard, not a settling window: the parent writes it within one
poll interval of seeing the last snapshot.
"""

from __future__ import annotations

import asyncio
import json
import multiprocessing
import os
import socket
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from niharamesh.domain.coordination import PeerEnvelope, PeerMessage, PeerState, build_message
from niharamesh.domain.faults import FaultChannel, FaultKind, FaultSpec, FaultTarget
from niharamesh.domain.identity import (
    Membership,
    PeerEndpoint,
    RobotIdentity,
    RobotSession,
)
from niharamesh.domain.pose import Footprint
from niharamesh.domain.units import TimeDomain
from niharamesh.transport.clocksync import ClockSync
from niharamesh.transport.codec import MAX_FRAME_BYTES
from niharamesh.transport.faults import FaultLayer
from niharamesh.transport.peer import (
    DEFAULT_SILENCE_THRESHOLD_NS,
    PeerDeclaration,
    PeerTransportServer,
)

_ROBOTS = ("r1", "r2", "r3")
_RUN_ID = "netrun"
_EPOCH = "e1"
_PUBLISH_INTERVAL_S = 0.02
_PROBE_INTERVAL_S = 0.05
#: A peer publishing every 20 ms must look alive; a peer publishing nothing must
#: cross this bound inside one phase so "connected but silent" is reachable.
_SILENCE_THRESHOLD_NS = 600_000_000
_PHASE_S = 1.2
#: How long a child waits for the parent to release it after sampling, and how
#: long the parent waits for each child's final report. These are hang guards, in
#: the same spirit as the existing 25 s command timeout: the release cannot
#: legitimately take longer than one parent poll interval (20 ms), so anything
#: approaching this bound is a lost child and must be reported, not absorbed.
_PHASE2_RELEASE_TIMEOUT_S = 25.0
_REPORT_TIMEOUT_S = 25.0
#: Written by the parent once every robot has taken its phase-2 sample.
_RELEASE_FILE = "phase2-released.json"


@dataclass(frozen=True, slots=True)
class _Config:
    """Everything a child needs. Plain data so ``spawn`` can pickle it."""

    robot_id: str
    session_id: str
    port: int
    peer_ports: dict[str, int]
    workdir: str
    label: str = ""
    #: Length of this robot's second phase. Equal for every robot in the main
    #: test; deliberately unequal in the early-exit regression, where the skew is
    #: the thing under test rather than an accident of scheduling.
    phase2_s: float = _PHASE_S


# --------------------------------------------------------------------- helpers


def _free_port() -> int:
    """Reserve an ephemeral loopback port and hand it back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _wait_for(path: Path, timeout_s: float) -> dict[str, Any] | None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            try:
                return _read(path)
            except (OSError, ValueError):
                pass
        time.sleep(0.02)
    return None


async def _await_file(path: Path, timeout_s: float) -> dict[str, Any] | None:
    """Async variant: never blocks the child's event loop while it waits."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            return _read(path)
        except (OSError, ValueError):
            await asyncio.sleep(0.02)
    return None


def _identity(robot_id: str) -> RobotIdentity:
    return RobotIdentity(
        robot_id=robot_id,
        model="niharamesh-amr",
        footprint=Footprint(length_m=0.9, width_m=0.6, turning_radius_m=0.35),
    )


def _membership() -> Membership:
    return Membership(run_id=_RUN_ID, epoch=_EPOCH, members=_ROBOTS)


def _peer_state(robot_id: str, seq: int) -> PeerMessage:
    """One real ``peer_state`` publication from *robot_id*, for in-process tests."""
    session = f"sess-{robot_id}-{_RUN_ID}"
    now_ns = time.monotonic_ns()
    return build_message(
        PeerEnvelope(
            kind="peer_state",
            sender=robot_id,
            sender_session=session,
            run_id=_RUN_ID,
            epoch=_EPOCH,
            seq=seq,
            sent_at_ns=now_ns,
            time_domain=TimeDomain.MONOTONIC,
        ),
        PeerState(
            robot_id=robot_id,
            session_id=session,
            seq=seq,
            pose=(0.0, 0.0, 0.0),
            velocity=(0.0, 0.0),
            uncertainty_m=0.02,
            uncertainty_rad=0.01,
            sent_at_ns=now_ns,
            time_domain=TimeDomain.MONOTONIC,
        ),
    )


# ------------------------------------------------------------------- child code


def _peer_worker(config: _Config) -> None:
    """One robot process. Owns a socket, a fault layer and a clock estimator."""
    workdir = Path(config.workdir)
    report: dict[str, Any] = {
        "robot_id": config.robot_id,
        "session_id": config.session_id,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "python": sys.executable,
        "requested_port": config.port,
        "error": "",
        "phase1": {},
        "phase2": {},
    }
    try:
        asyncio.run(_run_robot(config, workdir, report))
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = "".join(traceback.format_exception(exc))
    finally:
        _write(workdir / f"report-{config.robot_id}.json", report)


@dataclass(slots=True)
class _Counters:
    received_by_sender: dict[str, int] = field(default_factory=dict)
    received_total: int = 0
    published: int = 0


async def _run_robot(config: _Config, workdir: Path, report: dict[str, Any]) -> None:
    membership = _membership()
    identity = _identity(config.robot_id)
    session = RobotSession(
        robot_id=config.robot_id,
        session_id=config.session_id,
        started_at_ns=time.monotonic_ns(),
        pid=os.getpid(),
        host="127.0.0.1",
        listening_port=config.port,
    )
    declarations = {
        peer: PeerDeclaration(
            identity=_identity(peer),
            session=RobotSession(
                robot_id=peer,
                session_id=f"sess-{peer}-{_RUN_ID}",
                started_at_ns=0,
                pid=0,
                host="127.0.0.1",
                listening_port=port,
            ),
            endpoint=PeerEndpoint(robot_id=peer, host="127.0.0.1", port=port),
        )
        for peer, port in config.peer_ports.items()
    }
    faults = FaultLayer(local_robot_id=config.robot_id)
    transport = PeerTransportServer(
        identity=identity,
        session=session,
        membership=membership,
        peers=declarations,
        fault_layer=faults,
        bind_host="127.0.0.1",
        bind_port=config.port,
        silence_threshold_ns=_SILENCE_THRESHOLD_NS,
        seed=17,
    )
    sync = ClockSync(
        robot_id=config.robot_id,
        session_id=config.session_id,
        run_id=_RUN_ID,
        epoch=_EPOCH,
        interval_s=_PROBE_INTERVAL_S,
    )
    counters = _Counters()
    seq = 0

    def state_provider() -> PeerMessage:
        """The agent's *own* state. The transport never fabricates a pose."""
        nonlocal seq
        seq += 1
        now_ns = time.monotonic_ns()
        envelope = PeerEnvelope(
            kind="peer_state",
            sender=config.robot_id,
            sender_session=config.session_id,
            run_id=_RUN_ID,
            epoch=_EPOCH,
            seq=seq,
            sent_at_ns=now_ns,
            time_domain=TimeDomain.MONOTONIC,
        )
        body = PeerState(
            robot_id=config.robot_id,
            session_id=config.session_id,
            seq=seq,
            pose=(float(seq) * 0.01, 0.0, 0.0),
            velocity=(0.1, 0.0),
            uncertainty_m=0.02,
            uncertainty_rad=0.01,
            sent_at_ns=now_ns,
            time_domain=TimeDomain.MONOTONIC,
        )
        return build_message(envelope, body)

    sync.state_provider = state_provider
    transport.attach_clock_sync(sync)

    async def publish() -> None:
        while True:
            message = state_provider()
            for peer in config.peer_ports:
                await transport.send(peer, message)
            counters.published += 1
            await asyncio.sleep(_PUBLISH_INTERVAL_S)

    async def drain() -> None:
        async for message in transport.inbox():
            sender = message.envelope.sender
            counters.received_by_sender[sender] = counters.received_by_sender.get(sender, 0) + 1
            counters.received_total += 1

    seen_events = 0

    def snapshot() -> dict[str, Any]:
        """Counters, health, and the peer-link events since the previous snapshot.

        The trace is delta-compressed per phase so a failing run's artifacts say
        what each link did rather than only what it looks like now.
        """
        nonlocal seen_events
        trace = transport.link_trace()
        events = trace["events"]
        assert isinstance(events, list)
        report = {
            "robot_id": transport.robot_id,
            "session_id": transport.session_id,
            "listening_port": transport.listening_port,
            "received_by_sender": dict(counters.received_by_sender),
            "received_total": counters.received_total,
            "published": counters.published,
            "health": transport.health(),
            "link_trace": {
                "live_tasks": trace["live_tasks"],
                "inbound_live": trace["inbound_live"],
                "worker_failures": trace["worker_failures"],
                "evicted": trace["evicted"],
                "new_events": events[seen_events:],
            },
        }
        seen_events = len(events)
        return report

    workers: list[asyncio.Task[None]] = []
    try:
        await transport.start()
        report["listening_port"] = transport.listening_port
        workers.append(asyncio.create_task(publish(), name="publish"))
        workers.append(asyncio.create_task(drain(), name="drain"))

        await asyncio.sleep(_PHASE_S)
        report["phase1"] = snapshot()
        _write(workdir / f"phase1-{config.robot_id}.json", report["phase1"])
        _write(workdir / f"ready-{config.robot_id}.json", {"pid": os.getpid()})

        command = await _await_file(workdir / "command.json", timeout_s=25.0) or {}
        # `pairs` names disjoint two-robot cuts. This robot cuts only with its
        # own counterpart; a robot outside every pair installs no fault at all,
        # which is exactly what "a partition between A and B does not affect
        # B<->C" means.
        peers = sorted(
            {
                partner
                for pair in command.get("pairs", [])
                if config.robot_id in pair
                for partner in pair
                if partner != config.robot_id
            }
        )
        for peer in peers:
            faults.add(_partition_spec(f"cut-out-{peer}", sender=config.robot_id, receiver=peer))
            faults.add(_partition_spec(f"cut-in-{peer}", sender=peer, receiver=config.robot_id))

        # `cut` is the sample taken the instant the cut is armed. `cut2` is taken
        # half a phase later, and the "no leak" assertion compares *those two*
        # rather than "cut vs final": a frame already off the socket and past the
        # fault layer when the cut landed is in flight, not a leak, and comparing
        # two post-cut samples removes the in-flight backlog from the assertion
        # entirely. Anything still crossing the cut after half a phase could not
        # have been in flight when the partition existed.
        #
        # What this deliberately does *not* do is claim that the cut is live at the
        # instant `add()` returns. `FaultLayer.add` takes effect synchronously -
        # there is no separate arming step to wait for - and the post-cut samples,
        # not this one, are what the assertion rests on.
        _write(
            workdir / f"cut-{config.robot_id}.json",
            {"partition": peers, "received_by_sender": dict(counters.received_by_sender)},
        )

        await asyncio.sleep(_PHASE_S / 2.0)
        _write(
            workdir / f"cut2-{config.robot_id}.json",
            {"partition": peers, "received_by_sender": dict(counters.received_by_sender)},
        )

        await asyncio.sleep(config.phase2_s)
        report["phase2"] = snapshot()
        _write(workdir / f"phase2-{config.robot_id}.json", report["phase2"])
    finally:
        # Shutdown barrier. `transport.stop()` closes every peer socket, so a
        # robot that leaves before a peer has taken its phase-2 sample makes that
        # peer truthfully report the link as `disconnected` /
        # `availability: "unavailable"`. That is correct transport behaviour and
        # the wrong thing to assert on: the peer really is gone. The three
        # children are not phase-synchronised, so wait for the parent to release
        # every robot at once.
        #
        # A missed release is reported rather than absorbed: the artifacts carry
        # `barrier_timed_out` so the parent can name it instead of guessing.
        if await _await_file(workdir / _RELEASE_FILE, timeout_s=_PHASE2_RELEASE_TIMEOUT_S):
            report["barrier_released"] = True
        else:
            report["barrier_timed_out"] = True
        # Clean shutdown: the transport closes the inbox (ending `drain`), then the
        # publisher is cancelled and awaited. No task outlives this process.
        shutdown = snapshot()
        await transport.stop()
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        report["shutdown"] = shutdown


def _partition_spec(fault_id: str, *, sender: str, receiver: str) -> FaultSpec:
    return FaultSpec(
        fault_id=fault_id,
        target=FaultTarget(
            channel=FaultChannel.COORDINATION,
            kind=FaultKind.PARTITION,
            sender=sender,
            receiver=receiver,
        ),
        start_at_s=0.0,
        duration_s=3600.0,
        expected_invariant="B<->C coordination survives an A<->B partition",
    )


# ------------------------------------------------------------------- parent code


def _spawn(ctx: multiprocessing.context.BaseContext, configs: list[_Config]) -> list[Any]:
    procs = []
    for config in configs:
        proc = ctx.Process(target=_peer_worker, args=(config,), name=config.robot_id)
        proc.start()
        procs.append(proc)
    return procs


def _shutdown(procs: list[Any]) -> None:
    for proc in procs:
        proc.join(timeout=10)
    for proc in procs:
        if proc.is_alive():
            # Only ever terminate processes this test started.
            proc.terminate()
            proc.join(timeout=5)


def _reports(workdir: Path, phase: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for robot in _ROBOTS:
        data = _wait_for(workdir / f"{phase}-{robot}.json", timeout_s=20.0)
        assert data is not None, f"{robot} produced no {phase} report"
        out[robot] = data
    return out


def _assert_no_robot_exited_before_everyone_sampled(workdir: Path) -> None:
    """No robot may shut down before every robot has taken its phase-2 sample.

    A robot writes its final report only after ``transport.stop()``, which closes
    every peer socket. So a report that exists at the moment the parent has all
    three phase-2 snapshots means one robot's snapshot was taken after that peer
    had already left - and that snapshot will truthfully call the link
    ``disconnected``. Checked on the artifacts rather than inferred from a health
    mismatch, so a future regression names the orchestration rather than the
    transport.
    """
    early = sorted(robot for robot in _ROBOTS if (workdir / f"report-{robot}.json").exists())
    assert early == [], (
        f"{early} shut down before every robot had sampled phase 2; a peer that has "
        "exited is reported disconnected/unavailable, which is correct transport "
        "behaviour and not a link fault"
    )


def _release(workdir: Path) -> None:
    """Let every robot shut down. Called only after the invariant above holds."""
    _write(workdir / _RELEASE_FILE, {"released": True})


@dataclass(slots=True)
class _Run:
    """Everything one orchestrated three-process run produced."""

    phase1: dict[str, dict[str, Any]]
    cut_at: dict[str, dict[str, Any]]
    #: Mid-phase sample, used so the "no leak" comparison starts *after* the
    #: in-flight backlog has drained rather than at the instant the cut is armed.
    cut2: dict[str, dict[str, Any]]
    phase2: dict[str, dict[str, Any]]
    reports: dict[str, dict[str, Any] | None]
    ports: dict[str, int]


def _run_three(tmp_path: Path, *, phase2_s: dict[str, float] | None = None) -> _Run:
    """Spawn the three robots, cut r1<->r2, and collect every artifact.

    ``phase2_s`` overrides a robot's second-phase length. Used only by the
    early-exit regression, where the skew *is* the subject; the main test leaves
    every robot on the same length so the run keeps its original timing.
    """
    workdir = tmp_path / "run"
    workdir.mkdir(parents=True, exist_ok=True)
    ports = {robot: _free_port() for robot in _ROBOTS}
    assert len(set(ports.values())) == 3, "each robot must own a distinct port"

    overrides = phase2_s or {}
    configs = [
        _Config(
            robot_id=robot,
            session_id=f"sess-{robot}-{_RUN_ID}",
            port=ports[robot],
            peer_ports={p: ports[p] for p in _ROBOTS if p != robot},
            workdir=str(workdir),
            label=robot,
            phase2_s=overrides.get(robot, _PHASE_S),
        )
        for robot in _ROBOTS
    ]

    ctx = multiprocessing.get_context("spawn")
    procs = _spawn(ctx, configs)
    cut_at: dict[str, dict[str, Any]] = {}
    cut2: dict[str, dict[str, Any]] = {}
    try:
        phase1 = _reports(workdir, "phase1")
        _write(workdir / "command.json", {"pairs": [["r1", "r2"]]})
        for robot in _ROBOTS:
            data = _wait_for(workdir / f"cut-{robot}.json", timeout_s=20.0)
            assert data is not None, f"{robot} never applied the partition"
            cut_at[robot] = data
            mid = _wait_for(workdir / f"cut2-{robot}.json", timeout_s=20.0)
            assert mid is not None, f"{robot} never took the mid-phase sample"
            cut2[robot] = mid
        phase2 = _reports(workdir, "phase2")
        # Every robot is still running here; that is the invariant the whole
        # phase-2 assertion set depends on, so it is checked before the release
        # rather than inferred from a health mismatch afterwards.
        _assert_no_robot_exited_before_everyone_sampled(workdir)
        _release(workdir)
        reports = {robot: _wait_for(workdir / f"report-{robot}.json", _REPORT_TIMEOUT_S) for robot in _ROBOTS}
    finally:
        _shutdown(procs)
    return _Run(
        phase1=phase1,
        cut_at=cut_at,
        cut2=cut2,
        phase2=phase2,
        reports=reports,
        ports=ports,
    )


def _assert_children_clean(run: _Run) -> None:
    for robot in _ROBOTS:
        report = run.reports[robot]
        assert report is not None, f"no final report from {robot}"
        assert report["error"] == "", f"{robot} failed: {report['error']}\n{report.get('traceback', '')}"
        assert report.get("barrier_timed_out") is not True, (
            f"{robot} never saw the phase-2 release; the parent would have "
            "asserted on a peer that had already exited"
        )


@pytest.mark.network
@pytest.mark.timeout(60)
def test_three_process_peers_talk_directly(tmp_path: Path) -> None:
    run = _run_three(tmp_path)
    phase1, phase2, cut_at, cut2, reports, ports = (
        run.phase1,
        run.phase2,
        run.cut_at,
        run.cut2,
        run.reports,
        run.ports,
    )
    _assert_children_clean(run)

    # (b) distinct identity per process, and genuinely separate OS processes.
    pids = {robot: int(reports[robot]["pid"]) for robot in _ROBOTS}
    assert len(set(pids.values())) == 3, f"expected three OS pids, got {pids}"
    assert all(pid != os.getpid() for pid in pids.values()), "a child ran in the parent"
    assert len({reports[r]["session_id"] for r in _ROBOTS}) == 3
    bound = {robot: int(phase1[robot]["listening_port"]) for robot in _ROBOTS}
    assert bound == ports
    assert len(set(bound.values())) == 3

    # (a) every robot received both of the others.
    for robot in _ROBOTS:
        senders = phase1[robot]["received_by_sender"]
        assert set(senders) == set(_ROBOTS) - {robot}, f"{robot} received {senders}"
        assert all(count > 0 for count in senders.values())
        assert phase1[robot]["published"] > 0

    # (c) health is healthy for every peer in the baseline phase.
    for robot in _ROBOTS:
        health = phase1[robot]["health"]
        assert health["silent_peers"] == [], health
        assert health["disconnected_peers"] == [], health
        for peer, info in health["peers"].items():
            assert info["status"] == "healthy", f"{robot}->{peer}: {info}"
            assert info["availability"] == "available"
            assert info["connected"] is True
            # Received *and* transmitted evidence, both fresh. Presence is `is not
            # None` rather than `> 0`: the monotonic clock resolves to a
            # millisecond on Windows, so a first measurement can legitimately be 0.
            assert info["last_rx_ns"] is not None, f"{robot}->{peer} received nothing: {info}"
            assert info["last_tx_ns"] is not None, f"{robot}->{peer} sent nothing: {info}"
            assert info["silence_ms"] is not None
            assert info["silence_ms"] < _SILENCE_THRESHOLD_NS / 1e6, f"{robot}->{peer}: {info}"

    # (e) no central relay. Each peer contributes exactly one inbound socket, and
    #     its source port is precisely the ephemeral port that peer's own transport
    #     reported dialling from. A relay could not satisfy that identity.
    for robot in _ROBOTS:
        observed = phase1[robot]["health"]["observed_inbound_peers"]
        assert set(observed) == set(_ROBOTS) - {robot}, observed
        for peer, addrs in observed.items():
            assert len(addrs) == 1, f"{robot} saw {len(addrs)} sockets from {peer}"
            host, source_port = addrs[0]
            assert host == "127.0.0.1", f"non-loopback peer {host}"
            dialed_from = int(phase1[peer]["health"]["peers"][robot]["dialed_from_port"])
            assert int(source_port) == dialed_from, (
                f"{robot} received from {peer}:{source_port} but {peer} dialled "
                f"{robot} from port {dialed_from} - traffic was relayed"
            )
            assert dialed_from != ports[robot], "a peer must dial, not connect to itself"

    # (d) the A<->B partition leaves B<->C carrying real traffic. Both
    #     directions of the cut are applied on both cut robots; the survivor
    #     installs no fault whatsoever.
    cut = {"r1", "r2"}
    survivor = "r3"
    assert cut_at[survivor]["partition"] == [], "the survivor must not cut itself"
    assert phase2[survivor]["health"]["faults"]["silenced_directions"] == []
    assert phase2[survivor]["health"]["faults"]["availability"] == "available"
    for peer in sorted(cut):
        link = phase2[survivor]["health"]["peers"][peer]
        assert link["status"] == "healthy", link
        assert link["availability"] == "available"
        before = cut_at[survivor]["received_by_sender"].get(peer, 0)
        after = phase2[survivor]["received_by_sender"].get(peer, 0)
        assert after > before, f"{survivor} stopped hearing {peer} after the cut: {before} -> {after}"
    for robot in sorted(cut):
        assert cut_at[robot]["partition"] == [other for other in cut if other != robot]
        before = cut_at[robot]["received_by_sender"].get(survivor, 0)
        after = phase2[robot]["received_by_sender"].get(survivor, 0)
        assert after > before, f"{robot} stopped hearing {survivor}: {before} -> {after}"
        link = phase2[robot]["health"]["peers"][survivor]
        assert link["status"] == "healthy", link
        assert link["availability"] == "available"
    for robot in sorted(cut):
        other = "r2" if robot == "r1" else "r1"
        link = phase2[robot]["health"]["peers"][other]
        assert link["status"] in {"connected_silent", "disconnected"}, link
        # Silence is reported honestly as unavailable, never as "no traffic".
        assert link["availability"] == "unavailable"
        # Compare the *mid-phase* sample against the cut sample. Anything crossing
        # here was in flight when the cut landed, which is not a leak; anything
        # crossing after half a phase while the cut is installed would be.
        mid = cut2[robot]["received_by_sender"].get(other, 0)
        after = phase2[robot]["received_by_sender"].get(other, 0)
        assert after == mid, (
            f"{robot} kept receiving from {other} after the cut settled: "
            f"{cut_at[robot]['received_by_sender'].get(other, 0)} (at cut) -> "
            f"{mid} (mid-phase) -> {after} (end of phase)"
        )
        faults = phase2[robot]["health"]["faults"]
        assert faults["availability"] == "unavailable"
        assert len(faults["silenced_directions"]) == 2
        assert faults["authority_decisions"] == 0

    # Bounded resources held: no unbounded buffers anywhere in the run.
    for robot in _ROBOTS:
        health = phase2[robot]["health"]
        frames = health["frames"]
        assert health["inbox_depth"] <= health["inbox_capacity"]
        assert frames["peak_frame_bytes"] < MAX_FRAME_BYTES
        assert frames["too_large"] == 0
        assert frames["truncated"] == 0
        assert health["inbox_shed_replaceable"] + health["inbox_refused"] <= (
            frames["frames_in"] + frames["frames_out"]
        )
        for link in health["peers"].values():
            assert link["outbox_depth"] <= link["outbox_capacity"]

    # No worker died silently. `_reap` records every abnormal task exit, so an
    # empty failure list here is a measured result rather than an absence of
    # evidence - which is what it was before the transport reported worker deaths.
    for robot in _ROBOTS:
        for phase, samples in (("phase1", phase1), ("phase2", phase2)):
            failures = samples[robot]["link_trace"]["worker_failures"]
            assert isinstance(failures, list)
            assert failures == [], f"{robot}/{phase} workers died abnormally: {failures}"


@pytest.mark.network
@pytest.mark.timeout(60)
def test_a_robot_that_finishes_early_is_still_healthy_in_its_peers(tmp_path: Path) -> None:
    """A peer that reaches the end of its phase first must not look like a fault.

    The regression for the intermittent ``status == "healthy"`` failure. Under CPU
    load, a robot that finished and called ``transport.stop()`` before a peer had
    taken its phase-2 snapshot made that peer report the link ``disconnected`` /
    ``availability: "unavailable"`` - truthfully, because the peer really had
    gone - and the assertion then failed. Measured in 5 of 45 loaded runs, with
    the departed peer's own report recording the closing stacks
    ``PeerTransportServer.stop -> PeerClient.stop -> _detach -> close``.

    CPU load only widened a skew that is already there: each child starts its own
    clock after its own import and observes the phase-2 command on a 20 ms poll,
    so the three children are never phase-aligned. Here the skew is injected
    instead of waited for, which makes the race deterministic instead of rare:

    * ``_run_three`` asserts that no robot exited before every robot had sampled,
      which is the invariant the phase-2 assertions rest on;
    * with the barrier, r3's early finish is held until r1 and r2 have sampled,
      so both still see it ``healthy``.

    Removing the barrier makes this test fail deterministically, with the
    surviving robots reporting r3 ``disconnected``.
    """
    run = _run_three(tmp_path, phase2_s={"r3": _PHASE_S / 4.0})
    _assert_children_clean(run)

    for robot in ("r1", "r2"):
        info = run.phase2[robot]["health"]["peers"]["r3"]
        assert info["status"] == "healthy", (
            f"{robot} reported the still-running peer r3 as {info['status']}; r3 had "
            f"finished its phase first but must not have left"
        )
        assert info["availability"] == "available"
        assert info["connected"] is True
        assert run.phase2[robot]["health"]["disconnected_peers"] == []

    # r3 really did reach the end of its phase first. Without this the test would
    # pass for the wrong reason if the skew stopped taking effect.
    assert run.phase2["r3"]["received_total"] > 0
    for robot in ("r1", "r2"):
        assert run.phase2[robot]["received_by_sender"].get("r3", 0) > 0, (
            f"{robot} heard nothing from r3 at all, so this proves nothing"
        )


@pytest.mark.network
@pytest.mark.timeout(30)
def _build_pair() -> tuple[PeerTransportServer, PeerTransportServer, dict[str, int]]:
    """Two real loopback transports that declare each other as peers."""
    ports = {robot: _free_port() for robot in ("a", "b")}
    membership = Membership(run_id=_RUN_ID, epoch=_EPOCH, members=("a", "b"))

    def session(robot: str) -> RobotSession:
        return RobotSession(
            robot_id=robot,
            session_id=f"sess-{robot}-{_RUN_ID}",
            started_at_ns=0,
            pid=os.getpid(),
            host="127.0.0.1",
            listening_port=ports[robot],
        )

    def identity(robot: str) -> RobotIdentity:
        return RobotIdentity(
            robot_id=robot,
            model="niharamesh-amr",
            footprint=Footprint(length_m=0.9, width_m=0.6, turning_radius_m=0.35),
        )

    def build(robot: str) -> PeerTransportServer:
        peer = "b" if robot == "a" else "a"
        return PeerTransportServer(
            identity=identity(robot),
            session=session(robot),
            membership=membership,
            peers={
                peer: PeerDeclaration(
                    identity=identity(peer),
                    session=session(peer),
                    endpoint=PeerEndpoint(robot_id=peer, host="127.0.0.1", port=ports[peer]),
                )
            },
            bind_host="127.0.0.1",
            bind_port=ports[robot],
            silence_threshold_ns=_SILENCE_THRESHOLD_NS,
            seed=17,
        )

    return build("a"), build("b"), ports


async def _consume(transport: PeerTransportServer) -> None:
    async for _ in transport.inbox():
        pass


#: Poll cadence and budget for "has this link carried real traffic yet" checks.
#: The budget is the transport's declared silence tolerance
#: (``DEFAULT_SILENCE_THRESHOLD_NS``, after which it would call the link silent
#: itself) times two. Past that, waiting longer proves nothing - it could only be
#: hiding the fault the assertions below are meant to see.
_TRAFFIC_POLL_S = 0.02
_TRAFFIC_BUDGET_S = 2.0 * DEFAULT_SILENCE_THRESHOLD_NS / 1e9


async def _await_real_traffic(a: PeerTransportServer, b: PeerTransportServer) -> None:
    """Wait until real peer messages have crossed in *both* directions.

    A link only becomes usable once its first dial succeeds, and a dial can fail
    while the peer's listener is still coming up; the retry is capped by the
    transport's own reconnect backoff. The bound is :data:`_TRAFFIC_BUDGET_S`,
    derived from the contract rather than from an observed run.

    "Received evidence" is tested as ``is not None``, not ``> 0``: the monotonic
    clock resolves to a millisecond on Windows, so the first measurement on a link
    can legitimately be ``0``.
    """
    for _ in range(int(_TRAFFIC_BUDGET_S / _TRAFFIC_POLL_S)):
        if (
            a.health()["peers"]["b"]["last_rx_ns"] is not None
            and b.health()["peers"]["a"]["last_rx_ns"] is not None
        ):
            return
        await asyncio.sleep(_TRAFFIC_POLL_S)


@pytest.mark.network
@pytest.mark.timeout(30)
async def test_a_peer_that_has_exited_is_unavailable_and_is_still_retried() -> None:
    """The contract the diagnosis rests on, pinned so it cannot be papered over.

    A peer that has closed its sockets and gone away is ``disconnected`` and
    ``availability: "unavailable"`` - never ``healthy``, never ``available`` - and
    the reconnect loop keeps retrying with capped backoff. This is the honest
    report that the three-process test must not assert against, and it is exactly
    what the flaky snapshot contained, so it is asserted here on purpose rather
    than left implicit.
    """
    a, b, _ports = _build_pair()
    await a.start()
    await b.start()
    consumer = asyncio.create_task(_consume(a))
    try:
        await a.send("b", _peer_state("a", 1))
        await b.send("a", _peer_state("b", 1))
        await _await_real_traffic(a, b)

        # "healthy" must rest on received evidence, not on a bare connect.
        assert a.health()["frames"]["frames_in"] > 0, "no real message crossed b->a"
        assert b.health()["frames"]["frames_in"] > 0, "no real message crossed a->b"
        link = a.health()["peers"]["b"]
        assert link["last_rx_ns"] is not None, "healthy must rest on received evidence"
        assert link["silence_ms"] is not None
        assert link["silence_ms"] < _SILENCE_THRESHOLD_NS / 1e6
        assert link["status"] == "healthy", link
        assert link["availability"] == "available"

        await b.stop()  # b has gone: every socket closed and its listener released

        # Wait for the survivor to notice and to retry. `PeerClient` restarts its
        # backoff at 50 ms (with up to 15% jitter) after a successful attach, so
        # 300 ms is several minimum backoffs and the attempt count must have grown.
        await asyncio.sleep(0.3)

        link = a.health()["peers"]["b"]
        assert link["status"] == "disconnected", link
        assert link["availability"] == "unavailable", "a departed peer must never be reported available"
        assert link["connected"] is False
        assert link["dialed_from_port"] == 0
        assert a.health()["disconnected_peers"] == ["b"]
        assert link["connect_attempts"] > 1, (
            "the reconnect loop must keep retrying a departed peer, capped by backoff"
        )
        assert link["reconnects"] == 1, "no new connection can be established to a gone peer"
        assert not a.link_trace()["worker_failures"], (
            "a refused dial is a normal reconnect, not a dead worker"
        )
    finally:
        consumer.cancel()
        await asyncio.gather(consumer, return_exceptions=True)
        await a.stop()
        await b.stop()


@pytest.mark.network
@pytest.mark.timeout(30)
async def test_a_worker_that_dies_is_recorded_rather_than_swallowed() -> None:
    """An unexpected exception in a transport worker must leave evidence.

    Before this, ``_spawn`` registered ``self._tasks.discard`` as the done
    callback: a worker killed by an unhandled exception left nothing behind at
    all - no counter, no health field, no log - and the peer link simply never came
    back. That silence is what made the three-process flake look like a scheduling
    problem inside the transport instead of an orchestration problem in the test.
    """
    victim, peer, _ports = _build_pair()

    class Boom(RuntimeError):
        pass

    def explode(message: PeerMessage, now_ns: int) -> Any:
        raise Boom("injected ingestion failure")

    # Break the step *inside* ingestion, so the guard in `_ingest` and the guard in
    # `_serve_connection` both see it. `_accept_inbound_frame` would not do: in a
    # mutual mesh every inbound message arrives on an *accepted* socket, because
    # each robot dials the other and the peer never writes back onto the socket it
    # accepted.
    victim.fault_layer.apply_inbound = explode  # type: ignore[method-assign]
    await victim.start()
    await peer.start()
    try:
        await peer.send("a", _peer_state("b", 1))
        for _ in range(int(_TRAFFIC_BUDGET_S / _TRAFFIC_POLL_S)):
            if victim.link_trace()["worker_failures"]:
                break
            await asyncio.sleep(_TRAFFIC_POLL_S)

        failures = victim.link_trace()["worker_failures"]
        assert isinstance(failures, tuple)
        assert failures, "a worker that died on an unhandled exception left no evidence"
        assert "Boom: injected ingestion failure" in str(failures[-1]["summary"])
        scopes = {str(f["scope"]) for f in failures}
        assert "serve.failed" in scopes, scopes
        events = {str(event["scope"]) for event in victim.link_trace()["events"]}
        assert {"ingest_escaped", "serve_escaped"} <= events, events
    finally:
        await victim.stop()
        await peer.stop()


@pytest.mark.network
@pytest.mark.timeout(30)
async def test_port_conflict_is_reported_not_worked_around(tmp_path: Path) -> None:
    """A taken port must fail loudly and name the address.

    Nothing is killed and nothing is stolen: the socket this test opened stays
    open and is released by its own context manager.
    """
    identity = _identity("r1")
    session = RobotSession(robot_id="r1", session_id="sess-r1", started_at_ns=0, pid=0, host="127.0.0.1")
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    taken = 0
    try:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        taken = int(blocker.getsockname()[1])
        transport = PeerTransportServer(
            identity=identity,
            session=session,
            membership=Membership(run_id=_RUN_ID, epoch=_EPOCH, members=("r1",)),
            peers={},
            bind_host="127.0.0.1",
            bind_port=taken,
        )
        with pytest.raises(OSError) as excinfo:
            await transport.start()
        message = str(excinfo.value)
        assert "address" in message.lower() or "bind" in message.lower(), message
        assert str(taken) in message
        # The blocker is still ours: nothing was killed or hijacked.
        assert blocker.getsockname()[1] == taken
    finally:
        blocker.close()

    # Once released, the very same port binds cleanly and reports its own port.
    reclaimed = PeerTransportServer(
        identity=identity,
        session=session,
        membership=Membership(run_id=_RUN_ID, epoch=_EPOCH, members=("r1",)),
        peers={},
        bind_host="127.0.0.1",
        bind_port=taken,
    )
    try:
        await reclaimed.start()
        assert reclaimed.listening_port == taken
    finally:
        await reclaimed.stop()


def test_non_loopback_bind_is_refused() -> None:
    identity = _identity("r1")
    session = RobotSession(robot_id="r1", session_id="sess-r1", started_at_ns=0, pid=0, host="127.0.0.1")
    with pytest.raises(ValueError, match="loopback-only"):
        PeerTransportServer(
            identity=identity,
            session=session,
            membership=Membership(run_id=_RUN_ID, epoch=_EPOCH, members=("r1",)),
            peers={},
            bind_host="0.0.0.0",
        )

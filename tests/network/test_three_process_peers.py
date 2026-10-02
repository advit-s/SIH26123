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
from niharamesh.transport.peer import PeerDeclaration, PeerTransportServer

_ROBOTS = ("r1", "r2", "r3")
_RUN_ID = "netrun"
_EPOCH = "e1"
_PUBLISH_INTERVAL_S = 0.02
_PROBE_INTERVAL_S = 0.05
#: A peer publishing every 20 ms must look alive; a peer publishing nothing must
#: cross this bound inside one phase so "connected but silent" is reachable.
_SILENCE_THRESHOLD_NS = 600_000_000
_PHASE_S = 1.2


@dataclass(frozen=True, slots=True)
class _Config:
    """Everything a child needs. Plain data so ``spawn`` can pickle it."""

    robot_id: str
    session_id: str
    port: int
    peer_ports: dict[str, int]
    workdir: str
    label: str = ""


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

    def snapshot() -> dict[str, Any]:
        return {
            "robot_id": transport.robot_id,
            "session_id": transport.session_id,
            "listening_port": transport.listening_port,
            "received_by_sender": dict(counters.received_by_sender),
            "received_total": counters.received_total,
            "published": counters.published,
            "health": transport.health(),
        }

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

        # Wait until the cut is *observably live* before sampling the counters.
        #
        # `faults.add` only schedules the fault. A frame already off the socket and
        # past the fault layer when the cut landed is not a leak - it was in
        # flight before the partition existed. Sampling the instant `add()` returns
        # races with those frames and produces an intermittent "kept receiving after
        # the cut" failure that says nothing about the transport.
        #
        # The observable signal that the cut is live is the fault layer reporting the
        # direction as silenced, so the wait is on that condition rather than on a
        # guessed sleep duration.
        # The "no leak" comparison starts at the mid-phase sample rather than at the
        # instant the cut is armed, so frames already in flight when the partition
        # landed cannot be mistaken for a leak.
        _write(
            workdir / f"cut-{config.robot_id}.json",
            {"partition": peers, "received_by_sender": dict(counters.received_by_sender)},
        )

        # Second sample, taken halfway through the phase. Comparing *these two*
        # rather than "cut vs final" removes the in-flight backlog from the
        # assertion entirely: anything still crossing the cut after half a phase
        # cannot have been in flight when the cut landed.
        await asyncio.sleep(_PHASE_S / 2.0)
        _write(
            workdir / f"cut2-{config.robot_id}.json",
            {"partition": peers, "received_by_sender": dict(counters.received_by_sender)},
        )

        await asyncio.sleep(_PHASE_S)
        report["phase2"] = snapshot()
        _write(workdir / f"phase2-{config.robot_id}.json", report["phase2"])
    finally:
        # Clean shutdown: the transport closes the inbox (ending `drain`), then the
        # publisher is cancelled and awaited. No task outlives this process.
        await transport.stop()
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


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


@pytest.mark.network
@pytest.mark.timeout(60)
def test_three_process_peers_talk_directly(tmp_path: Path) -> None:
    workdir = tmp_path / "run"
    workdir.mkdir(parents=True, exist_ok=True)
    ports = {robot: _free_port() for robot in _ROBOTS}
    assert len(set(ports.values())) == 3, "each robot must own a distinct port"

    configs = [
        _Config(
            robot_id=robot,
            session_id=f"sess-{robot}-{_RUN_ID}",
            port=ports[robot],
            peer_ports={p: ports[p] for p in _ROBOTS if p != robot},
            workdir=str(workdir),
            label=robot,
        )
        for robot in _ROBOTS
    ]

    ctx = multiprocessing.get_context("spawn")
    procs = _spawn(ctx, configs)
    cut_at: dict[str, dict[str, Any]] = {}
    #: Mid-phase sample, used so the "no leak" comparison starts *after* the
    #: in-flight backlog has drained rather than at the instant the cut is armed.
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

        reports = {robot: _wait_for(workdir / f"report-{robot}.json", 5.0) for robot in _ROBOTS}
    finally:
        _shutdown(procs)

    for robot in _ROBOTS:
        assert reports[robot] is not None, f"no final report from {robot}"
        assert reports[robot]["error"] == "", (
            f"{robot} failed: {reports[robot]['error']}\n{reports[robot].get('traceback', '')}"
        )

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
            assert info["last_rx_ns"] > 0 and info["last_tx_ns"] > 0

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

"""Event-store tests: ordering, gaps, decimation and restart-without-reset.

The reviewer-facing claim under test is the last one: restarting the observer
must reconstruct its read model *without* resetting the fleet or re-assigning
tasks. So the read model is rebuilt purely by replaying stored events, and
rebuilding twice must produce byte-identical state.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from niharamesh.domain.telemetry import (
    DURABLE_CATEGORIES,
    DomainEvent,
    EventCategory,
    EventSeverity,
    RecordingGap,
    TelemetrySample,
)
from niharamesh.persistence.eventstore import EventSpool, EventStore, rebuild_read_model
from niharamesh.persistence.migrations import (
    MIGRATIONS,
    MigrationDrift,
    current_version,
    migrate,
)
from niharamesh.telemetry.gaps import RecordingGapTracker
from niharamesh.telemetry.recorder import Recorder


def _event(
    *,
    type: str = "note",
    category: EventCategory = EventCategory.LIFECYCLE,
    robot_id: str | None = None,
    task_id: str | None = None,
    zone_id: str | None = None,
    payload: dict[str, object] | None = None,
    seq: int = 0,
    sim_time_s: float = 0.0,
) -> DomainEvent:
    return DomainEvent(
        run_id="run-a",
        seq=seq,
        source="test",
        source_session="sess-r1",
        event_time_ns=1_000,
        time_domain="monotonic",
        receive_time_ns=2_000,
        receive_time_domain="monotonic",
        sim_time_s=sim_time_s,
        type=type,
        category=category,
        severity=EventSeverity.INFO,
        robot_id=robot_id,
        task_id=task_id,
        zone_id=zone_id,
        payload=payload or {},
    )


def _sample(index: int, robot_id: str = "r1") -> TelemetrySample:
    return TelemetrySample(
        run_id="run-a",
        robot_id=robot_id,
        sample_index=index,
        sim_time_s=index * 0.1,
        x=float(index),
        y=0.0,
        theta=0.0,
        linear_mps=0.0,
        angular_radps=0.0,
    )


# ------------------------------------------------------------------ migrations


def test_migrations_are_forward_only_and_ordered() -> None:
    versions = [version for version, _ in MIGRATIONS]
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert versions[0] == 1


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "x.db"), isolation_level=None)
    try:
        assert current_version(conn) == 0
        first = migrate(conn)
        second = migrate(conn)
        assert first == second == max(v for v, _ in MIGRATIONS)
        assert current_version(conn) == first
        rows = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        assert rows == len(MIGRATIONS)
    finally:
        conn.close()


def test_edited_migration_is_detected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import sqlite3

    conn = sqlite3.connect(str(tmp_path / "x.db"), isolation_level=None)
    try:
        migrate(conn)
        conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = 1")
        import niharamesh.persistence.migrations as module

        monkeypatch.setattr(module, "MIGRATIONS", ((1, "SELECT 1;"),))
        with pytest.raises(MigrationDrift):
            migrate(conn)
    finally:
        conn.close()


# --------------------------------------------------------------- sequence order


def test_seq_is_monotonic_and_gap_free(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        seqs = [store.append_event(_event()) for _ in range(50)]
        assert seqs == list(range(50))
        stored = store.read_all_events()
        assert [e.seq for e in stored] == list(range(50))
        assert store.event_count() == 50


def test_sequence_continues_across_a_reopen(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        store.append_event(_event())
        store.append_event(_event())
    with EventStore(tmp_path, run_id="run-a") as store:
        assert store.append_event(_event()) == 2
        assert store.event_count() == 3
        assert [e.seq for e in store.read_all_events()] == [0, 1, 2]


def test_read_events_honours_from_seq_and_limit(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        for _ in range(10):
            store.append_event(_event())
        page = store.read_events(from_seq=4, limit=3)
        assert [e.seq for e in page] == [4, 5, 6]


def test_jsonl_artifact_is_append_only_and_ordered(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        for _ in range(5):
            store.append_event(_event())
        path = store.events_path
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    seqs = [json.loads(line)["seq"] for line in lines]
    assert seqs == [0, 1, 2, 3, 4]


# ------------------------------------------------------------------- telemetry


def test_telemetry_round_trip(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        for i in range(5):
            assert store.write_telemetry(_sample(i)) is True
        rows = store.read_telemetry("run-a", from_index=2, limit=10)
        assert [s.sample_index for s in rows] == [2, 3, 4]
        assert rows[0].x == 2.0


def test_telemetry_decimation_produces_an_explicit_gap(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a", telemetry_decimation=3) as store:
        kept = [store.write_telemetry(_sample(i)) for i in range(9)]

        # One in three is kept; the holes are recorded, not hidden.
        assert kept == [True, False, False] * 3
        stored = store.read_telemetry("run-a")
        assert [s.sample_index for s in stored] == [0, 3, 6]

        gaps = store.gaps(EventCategory.TELEMETRY)
        assert len(gaps) == 6
        assert all(g.category is EventCategory.TELEMETRY for g in gaps)
        assert {g.from_seq for g in gaps} == {1, 2, 4, 5, 7, 8}
        assert all("decimated 1/3" in g.cause for g in gaps)

        health = store.health()
        assert health["telemetry_decimated"] == 6
        # A telemetry hole is a data gap, not a durability failure.
        assert health["durable_complete"] is True
        assert health["unrecovered_durable_gaps"] == 0


# ---------------------------------------------------------------------- gaps


def test_no_gap_is_recorded_for_a_durable_category_in_normal_operation(
    tmp_path: Path,
) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        for category in DURABLE_CATEGORIES:
            store.append_event(_event(category=category, type="authority_step"))
        assert store.gaps() == ()
        assert store.health()["durable_complete"] is True
        assert store.health()["spool_durable_overflow"] == 0


def test_a_durable_event_cannot_be_dropped_silently(tmp_path: Path) -> None:
    """Overflow the spool with durable events: every loss is written down."""
    capacity = 4
    with EventStore(tmp_path, run_id="run-a", spool_capacity=capacity, auto_flush=False) as store:
        seqs = [store.append_event(_event(category=EventCategory.AUTHORITY)) for _ in range(10)]
        assert store.health()["spool_depth"] == capacity
        assert store.health()["spool_durable_overflow"] == 6

        durable_gaps = store.gaps(EventCategory.AUTHORITY)
        assert len(durable_gaps) == 6
        # The gaps name exactly the sequences that were lost, so a reader can see
        # the hole instead of inferring it from a smooth-looking trace.
        assert {g.from_seq for g in durable_gaps} == set(seqs[capacity:])
        health = store.health()
        assert health["unrecovered_durable_gaps"] == 6
        assert health["durable_complete"] is False


def test_replaceable_overflow_does_not_claim_a_durable_hole(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a", spool_capacity=2, auto_flush=False) as store:
        for _ in range(6):
            store.append_event(_event(category=EventCategory.TELEMETRY))
        health = store.health()
        assert health["spool_replaceable_overflow"] == 4
        assert health["spool_durable_overflow"] == 0
        assert health["unrecovered_durable_gaps"] == 0
        assert store.gaps() == ()


def test_event_spool_bound_is_enforced_and_counted() -> None:
    spool = EventSpool(capacity=2)
    assert spool.put(_event(category=EventCategory.AUTHORITY)) is True
    assert spool.put(_event(category=EventCategory.TELEMETRY)) is True
    assert spool.put(_event(category=EventCategory.AUTHORITY)) is False
    assert spool.put(_event(category=EventCategory.TELEMETRY)) is False
    assert len(spool) == 2
    assert spool.durable_overflow == 1
    assert spool.replaceable_overflow == 1
    assert [e.seq for e in spool.drain()] == [0, 0]
    assert len(spool) == 0


def test_recorded_gap_is_readable_through_the_tracker(tmp_path: Path) -> None:
    tracker = RecordingGapTracker()
    with EventStore(tmp_path, run_id="run-a") as store:
        store.record_gap(
            RecordingGap(
                run_id="run-a",
                category=EventCategory.EVALUATION,
                from_seq=5,
                to_seq=6,
                sim_time_from_s=1.0,
                sim_time_to_s=1.5,
                cause="evaluator restarted",
            )
        )
        recorder = Recorder(store, run_id="run-a", robot_id="r1", session_id="sess-r1", tracker=tracker)
        recorder.ingest_gap_tracker(store)
        assert tracker.unrecovered_durable_gaps()
        assert tracker.durable_complete() is False
        assert "makespan_s" in tracker.excluded_metrics()
        assert recorder.health()["durable_complete"] is False


# --------------------------------------------------------------------- restart


def _seed(store: EventStore) -> None:
    store.append_event(
        _event(
            type="robot_state",
            category=EventCategory.TELEMETRY,
            robot_id="r1",
            payload={"pose": [1.0, 2.0, 0.25]},
        )
    )
    store.append_event(
        _event(
            type="task_awarded",
            category=EventCategory.TASK,
            robot_id="r2",
            task_id="t-7",
            payload={"task_id": "t-7", "robot_id": "r2"},
        )
    )
    store.append_event(
        _event(
            type="zone_granted",
            category=EventCategory.AUTHORITY,
            zone_id="z-1",
            payload={"zone_id": "z-1", "requester": "r1"},
        )
    )
    store.append_event(
        _event(
            type="zone_fenced",
            category=EventCategory.AUTHORITY,
            zone_id="z-9",
            payload={"zone_id": "z-9", "reason": "holder crashed"},
        )
    )


def test_reopening_does_not_reset_or_reassign(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        _seed(store)
        before = rebuild_read_model(store)
        before_events = store.event_count()

    # A second observer opens the same run. It must neither clear nor re-award.
    reopened = EventStore.open_or_create(tmp_path, "run-a")
    try:
        assert reopened.event_count() == before_events
        after = rebuild_read_model(reopened)
        assert after.task_owners == {"t-7": "r2"}
        assert after.task_owners == before.task_owners
        assert after.zone_holders == before.zone_holders == {"z-1": "r1"}
        assert after.fenced_zones == before.fenced_zones
        assert after.digest == before.digest
        assert after.robot_positions == {"r1": (1.0, 2.0, 0.25)}
        assert after.events_replayed == 4
    finally:
        reopened.close()


def test_rebuild_is_pure_and_repeatable(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        _seed(store)
        first = rebuild_read_model(store)
        second = rebuild_read_model(store)
        third = rebuild_read_model(store)
        assert first.as_dict() == second.as_dict() == third.as_dict()
        assert first.authority_transitions == 2
        assert first.category_counts == {"telemetry": 1, "task": 1, "authority": 2}


def test_rebuild_does_not_invent_an_owner_for_an_unawarded_task(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        store.append_event(_event(type="task_released", category=EventCategory.TASK, task_id="t-9"))
        model = rebuild_read_model(store)
        assert "t-9" not in model.task_owners


def test_a_durable_gap_makes_the_read_model_incomplete(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a", spool_capacity=2, auto_flush=False) as store:
        for _ in range(5):
            store.append_event(_event(category=EventCategory.SAFETY))
        store.flush()
        model = rebuild_read_model(store)
        assert model.durable_complete is False
        assert len(model.gaps) == 3
        assert model.as_dict()["durable_complete"] is False


# -------------------------------------------------------------------- recorder


def test_recorder_uses_two_separate_clock_domains(tmp_path: Path) -> None:
    from niharamesh.clocks import LogicalClock, MonotonicClock

    with EventStore(tmp_path, run_id="run-a") as store:
        recorder = Recorder(
            store,
            run_id="run-a",
            robot_id="r1",
            session_id="sess-r1",
            source_clock=LogicalClock(start_ns=500),
            observer_clock=MonotonicClock(),
        )
        recorder.emit("zone_granted", "r1", {"zone_id": "z-1"}, category=EventCategory.AUTHORITY)
        event = store.read_all_events()[0]
        assert event.event_time_ns == 500
        assert event.time_domain.value == "logical"
        assert event.receive_time_domain.value == "monotonic"
        assert event.receive_time_ns != event.event_time_ns


def test_recorder_refuses_a_source_supplied_receive_timestamp(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a") as store:
        recorder = Recorder(store, run_id="run-a", robot_id="r1", session_id="s")
        recorder.emit("x", "r1", {}, receive_time_ns=5)
        health = recorder.health()
        assert health["recorded"] == 0
        assert health["dropped"] == 1
        assert "receive_time_ns" in health["last_error"]
        assert store.event_count() == 0


def test_losing_the_observer_is_a_counted_no_op(tmp_path: Path) -> None:
    class DeadStore:
        def append_event(self, event: DomainEvent) -> int:
            raise OSError("observer volume is gone")

        def write_telemetry(self, sample: TelemetrySample) -> bool:
            raise OSError("observer volume is gone")

        def health(self) -> dict[str, object]:
            raise OSError("observer volume is gone")

    recorder = Recorder(DeadStore(), run_id="run-a", robot_id="r1", session_id="s")
    for _ in range(50):
        recorder.emit("tick", "r1", {"n": 1})  # must not raise
    recorder.record_telemetry(_sample(0))  # must not raise

    health = recorder.health()
    assert health["recorded"] == 0
    assert health["dropped"] == 50
    assert health["telemetry_dropped"] == 1
    assert "observer volume is gone" in str(health["last_error"])


def test_recorder_holds_no_reference_to_the_world(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "src" / "niharamesh" / "telemetry" / "recorder.py"
    text = source.read_text(encoding="utf-8")
    assert "niharamesh.simulator" not in text
    assert "niharamesh.api" not in text
    with EventStore(tmp_path, run_id="run-a") as store:
        recorder = Recorder(store, run_id="run-a", robot_id="r1", session_id="s")
        held = set(vars(recorder))
        assert held.isdisjoint({"world", "simulator", "sim", "engine", "world_port"})
        assert "world_port" not in dir(recorder)


def test_recorder_health_reports_spool_and_durability(tmp_path: Path) -> None:
    with EventStore(tmp_path, run_id="run-a", spool_capacity=8) as store:
        recorder = Recorder(store, run_id="run-a", robot_id="r1", session_id="s")
        recorder.emit("a", "r1", {})
        recorder.emit("b", "r1", {})
        recorder.record_telemetry(_sample(0))
        health = recorder.health()
        assert health["recorded"] == 2
        assert health["dropped"] == 0
        assert health["spool_capacity"] == 8
        assert health["spool_depth"] == 0
        assert health["gaps"] == 0
        assert health["durable_complete"] is True
        assert health["telemetry_seen"] == 1

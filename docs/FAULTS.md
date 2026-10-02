# Fault injection guide

A fault is a **declared, targeted, seeded** perturbation with an expected invariant.
Two channels exist and are never conflated:

| Channel | What it breaks | Consequence |
|---|---|---|
| `coordination` | robot ↔ robot protocol traffic | A genuine decentralisation experiment |
| `telemetry` | observer / dashboard data | A **data gap**, not a change in robot behaviour |

A fault may delay, drop, duplicate, reorder or partition bytes, perturb a *declared*
clock offset, or act on a process or object. **It never makes a decision for an
agent** and never synthesises or alters a message's semantic content.

> The fault layer may only move bytes. A fault that chose a route, an auction winner
> or a zone grant would not be a fault injection — it would be an authority.

---

## 1. Fault kinds

### Channel faults (need `sender` and/or `receiver`)

| Kind | Effect |
|---|---|
| `DELAY` | Deliver after a declared offset ± jitter |
| `LOSS` | Drop matching messages entirely |
| `DUPLICATE` | Deliver each matching message exactly twice |
| `REORDER` | Hold back a message so a later one overtakes it |
| `PARTITION` | Cut a directed channel. Set **both** `sender` and `receiver` for a bidirectional cut |

A channel fault naming neither endpoint is **rejected at validation**. The brief
requires directed injection, not a global toggle.

### Local faults

| Kind | Target | Purpose |
|---|---|---|
| `CLOCK_SKEW` | `robot` | Perturb the **declared** offset estimate, never the real clock |
| `SENSOR_STALE` | `robot` | Freeze observations so freshness handling is exercised |
| `SENSOR_DROPOUT` | `robot` | Drop observations entirely |
| `CONTROL_OVERLOAD` | `robot` | Delay the control loop so commands expire and the watchdog brakes |
| `PROCESS_CRASH` | `robot` | Terminate the agent process |
| `PROCESS_RESTART` | `robot` | Restart it with a **new** `session_id` |
| `JOURNAL_CORRUPT` | `robot` | Corrupt the authority journal → stopped/unknown recovery |
| `OBSTACLE_INSERT` / `OBSTACLE_REMOVE` | `position` | Change the physical environment mid-run |

Validation rejects `PROCESS_*` / `JOURNAL_CORRUPT` without `target.robot`, and
`OBSTACLE_*` without `target.position`.

---

## 2. What each fault is supposed to prove

Every fault carries an `expected_invariant` that is **checked after the run against
exported evidence**, not asserted in prose.

| Fault | Invariant under test |
|---|---|
| `PARTITION` | The partitioned robot **retains occupancy** of any held zone and stops before a stop line it can no longer confirm. Connected peers keep working. |
| `LOSS` of a release | The zone stays occupied. **No timer clears an aisle.** |
| `DUPLICATE` of a grant/cancel/release | The final state is identical to receiving each once, in order. No duplicate custody, no duplicate completion credit. |
| `REORDER` | Reordered delivery never produces conflicting authority. |
| `PROCESS_CRASH` holding a grant | The zone goes `FENCED`. There is no force-release. |
| `PROCESS_RESTART` | A new `session_id` cannot be confused with the old one. A stale promise is honoured, not forgotten. |
| `JOURNAL_CORRUPT` | The robot enters stopped/unknown recovery and grants **nothing**. |
| `CONTROL_OVERLOAD` | The watchdog brakes at the configured deceleration. Momentum decays; it never vanishes. |
| `CLOCK_SKEW` | A skewed peer reads `STALE` or `UNKNOWN`, never `FRESH`. |
| `SENSOR_STALE` | The robot stops on stale localisation rather than driving blind. |
| `OBSTACLE_INSERT` | The affected robot compares reroute cost against waiting, shows the comparison, and **never drives into the obstacle**. |
| `telemetry` channel fault | Robots keep deciding normally. The cockpit shows a gap, not zeros. |

---

## 3. Two kinds of injection

### Scheduled

Declared in the scenario's `faults` array. Becomes part of the **immutable
snapshot**, so it is quoted by the manifest and cannot be edited out of a completed
run.

### Manual

Injected from the fault laboratory. Becomes a **timestamped run event** with the
injecting operator recorded. Both kinds appear in the event log; the distinction is
preserved.

Validation warns when a fault's `end_at_s` exceeds the run's `max_sim_time_s`, since
its invariant could then never be observed.

---

## 4. Reproducible examples

### Asymmetric partition (shipped)

```jsonc
{
  "fault_id": "fx-part-a-to-b",
  "target": {
    "channel": "coordination",
    "kind": "partition",
    "sender": "amr-01",
    "receiver": "amr-02"
  },
  "start_at_s": 25.0,
  "duration_s": 45.0,
  "seed": 33,
  "expected_invariant": "amr-01 retains occupancy of any held zone and stops before a stop line it can no longer confirm, while amr-03 keeps delivering"
}
```

Run it:

```bash
uv run nihara run --scenario scenarios/asymmetric-partition.r1.json --mode deterministic
```

Expected: `amr-01 → amr-02` is cut **one way only**. `amr-02 → amr-01` still works,
so the pair sees *inconsistent* peer visibility — which is the interesting case.
`amr-03` is unaffected and keeps delivering.

### Delaying a peer's grants

```jsonc
{
  "fault_id": "fx-grant-delay",
  "target": { "channel": "coordination", "kind": "delay", "receiver": "amr-03",
              "message_kind": "zone_grant" },
  "start_at_s": 10.0,
  "duration_s": 20.0,
  "seed": 34,
  "params": { "delay_s": 0.6, "jitter_s": 0.1 },
  "expected_invariant": "amr-03 acquisition times out, cancels durably, and a late grant does not revive the cancelled request"
}
```

This is the case that separates real cancellation from best-effort acquisition.

### Obstruction insertion

```jsonc
{
  "fault_id": "fx-exit-block",
  "target": { "channel": "telemetry", "kind": "obstacle_insert",
              "robot": "amr-01", "position": [18.1, 9.4] },
  "start_at_s": 40.0,
  "duration_s": 60.0,
  "seed": 33,
  "params": { "length_m": 1.3, "width_m": 0.9, "theta": 0.0, "replace": "obs-pallet" },
  "expected_invariant": "the blocked robot detects the obstruction, compares reroute cost against waiting, and never drives into it"
}
```

### From the API

```bash
# Requires an Idempotency-Key, so a retry cannot create a second fault.
curl -X POST http://127.0.0.1:8100/api/v1/runs/$RUN/faults \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: fault-manual-001' \
  -d '{
        "fault_id": "fx-manual-partition",
        "target": {"channel":"coordination","kind":"partition","sender":"amr-02","receiver":"amr-03"},
        "start_at_s": 0.0, "duration_s": 15.0, "seed": 7,
        "expected_invariant": "amr-02 stops before an unconfirmed stop line; amr-01 unaffected"
      }'
```

Repeat the request with the same key: it returns the **same** fault record rather
than injecting twice.

---

## 5. Removing a fault

> **Removing a network fault restores communication, not movement permission.**

When a partition clears, messages flow again. The affected robots still hold
whatever stale beliefs they had, still retain occupancy of anything they could not
release, and must **reconcile before resuming**. They do not acquire a zone because
the network came back.

This is tested: `tests/unit/test_fault_layer.py` asserts on the transport's own
state that removal restores delivery and grants nothing.

---

## 6. Bounds and observability

| Bound | Behaviour |
|---|---|
| Inbox | Bounded. When full, **replaceable** messages (`peer_state`, telemetry) shed first; `zone_grant` / `zone_cancel` / `zone_release` never shed |
| Replay window | Bounded per-sender sequence window; a replayed or stale sequence is dropped and counted |
| Clock sync | 16 samples per peer, minimum-RTT selection |
| Journal | Bounded retention, but `prune_before` **refuses** to delete authority or custody records |
| Spool | Bounded; exhaustion produces an explicit `RecordingGap` rather than a silent drop |
| Jitter | Always from a **named** `SeededStreams` stream, so a run replays identically |

Every drop is counted by kind and reported by `health()`. A peer that is connected
but silent is reported as `connected_silent`, **not** as "no traffic" — because a
QoS mismatch is indistinguishable from silence, and reporting that as quiet would
hide a real integration fault. (This is exactly the ROS 2 failure mode recorded in
`docs/RESEARCH.md`.)

---

## 7. Honest reporting of fault runs

A run with faults active is labelled `DEGRADED` at best. It is not a clean
comparison point, and `docs/BENCHMARKS.md` requires that distinction to be stated
beside any aggregate.

Similarly, a run that violates its fault's `expected_invariant` produces a
`VIOLATION`-severity event. It is not silently downgraded to a warning, and it never
contributes to a safety claim.
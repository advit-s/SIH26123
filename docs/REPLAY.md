# Replay and evidence format

Replay answers one question honestly: **what did the system actually do at time T?**
It is built from an append-only event log, so it reconstructs state rather than
re-simulating it. Playback is visibly distinct from a fresh run, because it is.

---

## 1. Evidence layout

```text
var/runs/<run-id>/
  manifest.json        immutable: revisions, digests, policies, seeds, environment
  scenario.json        the exact immutable snapshot the run consumed
  events.jsonl         append-only durable event log
  telemetry.jsonl      replaceable high-rate samples (decimation allowed)
  commands.jsonl       operator command plane: requested/ack/applied/observed
  faults.jsonl         fault state changes
  result.json          RunResult: outcome, metrics, eligibility
  replay-index.json    ReplayIndex: counts, categories, gaps, completeness
```

All under `var/`, which is gitignored. Regenerate with the manifest's recorded
commands; compact authored fixtures and manifests are committed where appropriate.

---

## 2. The event log

One JSON object per line, append-only.

```jsonc
{
  "schema_version": "1.0.0",
  "run_id": "r-20260102-a1b2c3",
  "seq": 1841,                        // observer-assigned total order, gap-free
  "source": "amr-01",
  "source_session": "s-7f3a",
  "event_time_ns": 48200000000,       // SENDER's clock
  "time_domain": "logical",           // ...in its own domain
  "receive_time_ns": 1290560000000,   // OBSERVER's clock
  "receive_time_domain": "monotonic", // ...in a different domain
  "sim_time_s": 48.20,
  "type": "zone_granted",
  "category": "authority",            // authority | evaluation | task | safety
  "severity": "info",                 // info | attention | fault | violation
  "reason": "",
  "correlation_id": "txn-9f2c",
  "robot_id": "amr-01",
  "zone_id": "zn-headon-mid",
  "payload": { }
}
```

### Why both clocks are recorded

`event_time_ns` and `receive_time_ns` are in **different domains**. They are never
subtracted by the system. The separation exists because conflating them is exactly
how a message that was two seconds old ends up looking current: receipt time
always looks recent, which is why freshness must use a *conservative age lower
bound* computed from the sender's clock and a measured offset.

---

## 3. Categories, and which may be dropped

| Category | Loss effect |
|---|---|
| `AUTHORITY` | **Never dropped.** Lost grant/cancel/release evidence invalidates safety claims |
| `EVALUATION` | **Never dropped.** Without it, collisions and clearances are unverifiable |
| `TASK`, `SAFETY`, `FAULT`, `COMMAND` | **Never dropped** |
| `PLANNING`, `LIFECYCLE` | Recorded; not required for safety evidence |
| `TELEMETRY` | Replaceable. May be decimated under backpressure |

A telemetry decimation records an explicit `RecordingGap`:

```jsonc
{
  "category": "telemetry",
  "from_seq": 20100, "to_seq": 20999,
  "sim_time_from_s": 201.0, "sim_time_to_s": 209.99,
  "cause": "client backpressure: replaceable telemetry decimated",
  "recovered": true
}
```

A run with an **unrecovered** gap in a durable category is marked incomplete, and
its affected metrics are excluded from claims requiring complete evidence. The
evaluator never reconstructs a falsely complete run after an observer outage.

---

## 4. Replay semantics

### Rebuild, never re-simulate

State at a cursor is produced by **folding events from the start up to that
cursor**. It is never mutated forward and never patched backward. This is what
makes backward seeking correct by construction.

### Backward seek removes future state

Seeking from t=200 s back to t=120 s rebuilds from events ≤ 120 s. Therefore:

- task completions after 120 s **disappear**,
- grants issued after 120 s **disappear**,
- obstacles inserted after 120 s **disappear**,
- alerts after 120 s **disappear**.

There is no "undo" step, so there is no way for a stale future fact to survive.

### Playback vs re-simulation

| | Replay | Re-simulation |
|---|---|---|
| Source | Recorded events | Re-executes the system |
| Physics | Not re-integrated | Re-integrated |
| Deterministic mode | Exact | Exact, if the seed matches |
| Real-process mode | **The actual truth** | A different interleaving |
| Label in the UI | `replay` | `live` / `processes` |

The context bar shows the mode explicitly. A user must never confuse recorded
playback with a live run.

### Unknown event versions fail usefully

An event whose `schema_version` major version is unknown **fails with a visible
error** naming the version and the affected range. It never silently omits state —
silently dropping an unknown authority event would produce a replay that looks
plausible and is wrong.

---

## 5. Controls

| Control | Behaviour |
|---|---|
| Play / pause | Recorded playback only |
| Speed | 0.25× – 8× |
| Seek | Arbitrary timestamp; rebuilds by fold |
| Next / previous event | Steps by event, not by frame |
| Jump to first fault | First `severity >= fault` event |
| Jump to first invariant violation | First `severity == violation` event |
| Side-by-side baseline/candidate | Shared workload metadata, correct time domains |

"Next event" steps by **event**, because a frame-number match would desynchronise
two runs with different event densities. Comparing runs uses shared workload
metadata and correct time domains, never matching frame indices.

---

## 6. Side-by-side comparison

Two runs are comparable only when they agree on:

- the same scenario digest and map digest,
- the same seed,
- the same task set and release times,
- identical geometry, speed limits, sensing and stopping conditions.

A difference in any of these is **displayed as a configuration diff before the
comparison**, and the pair is marked non-comparable. The point is to make it
impossible to accidentally compare runs that differ in something material.

---

## 7. Determinism and repeatability

For a deterministic run, the same inputs and seed produce the same **canonical
normalised event/outcome hash**. Normalisation removes only genuinely
non-reproducible fields (wall-clock receive times, host ids, PIDs) — never event
content, never ordering.

For a real-process run, reproducibility means **complete traces and accurate
replay**, not a bit-identical outcome. A distributed execution with real sockets has
a genuinely different interleaving each time. Claiming bit-identical wall-clock
results would be false, so the system does not claim it.

---

## 8. Commands

```bash
uv run nihara replay --run var/runs/<run-id>     # inspect and validate
uv run nihara report --run var/runs/<run-id>    # render a report from evidence
```

The report is generated **from the exported artefacts**, so metrics can be
recomputed without rerunning the experiment. That property is what makes a number
evidence rather than an assertion.

---

## 9. Bounded resources

A multi-hour run must not exhaust memory. Bounded by construction:

| Resource | Bound |
|---|---|
| Client telemetry buffer | Decimated to a fixed window |
| Client chart history | Fixed-length ring |
| Stream backlog | Bounded; backpressure sheds replaceable telemetry only |
| Event spool (server) | Bounded; exhaustion → explicit `RecordingGap` |
| Replay frame cache | LRU, fixed size |
| Run retention | Explicit policy, prunable, and never pruning safety journals |

UI decimation **never** modifies raw evaluation evidence. The chart is a display
convenience; the artefact is the record.
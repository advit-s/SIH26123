# API reference

Base URL `http://127.0.0.1:8100` · all routes under `/api/v1` · JSON throughout.

This API is a **read model plus an explicitly labelled command plane**. It is not a
fleet planner and holds no authority. If a route here could grant a zone, award a
task or veto motion, the architecture would be broken — and
`tests/integration/test_authority_boundaries.py` checks exactly that.

OpenAPI is generated from the FastAPI app at `/api/v1/openapi.json`. Client types
are generated from the same Pydantic models that produce the JSON Schemas, so no
type is maintained twice.

---

## 1. Errors

Every error, from every route:

```jsonc
{
  "error": {
    "code": "scenario_path_outside_root",   // stable, snake_case, machine-usable
    "message": "scenario path '../etc/passwd' resolves outside the scenario root",
    "request_id": "req-8f2a1c",             // echoes X-Request-ID when supplied
    "details": { "field": "path" }          // validation specifics, when applicable
  }
}
```

| Status | Meaning |
|---|---|
| 400 | Invalid input — failed validation, impossible geometry, NaN/Inf |
| 404 | No such scenario / run / replay |
| 409 | Conflicting state — a run already terminal, an idempotency key reused with a different body |
| 413 | Payload or file above the size limit |
| 422 | Semantically valid shape, semantically impossible content |
| 429 | Rate limit (non-loopback mode only) |
| 503 | A required capability is unavailable (e.g. the world process is gone) |

Stable codes are part of the contract: the frontend branches on `code`, never on
message text.

---

## 2. Idempotency

Mutating routes accept `Idempotency-Key`. Reusing a key with the **same** body
returns the original result; reusing it with a **different** body returns `409`.

Without this, a browser retry would create a second run, a second fault or a second
task. Repeated clicks are a normal accident, not an attack, and must not corrupt
artefacts.

| Route | Key required |
|---|---|
| `POST /scenarios/{id}/launch` | **yes** |
| `POST /runs/{id}/commands` | **yes** |
| `POST /runs/{id}/faults` | **yes** |
| `POST /experiments` | **yes** |
| `POST /runs/{id}/export` | recommended |

---

## 3. Scenarios

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/scenarios` | Library listing with validation status |
| `GET` | `/scenarios/{id}` | Full authored JSON plus the validation report |
| `POST` | `/scenarios/validate` | Validate a draft **without saving it** |
| `POST` | `/scenarios` | Save a new revision |
| `POST` | `/scenarios/{id}/launch` | Freeze a snapshot and create a run |

`POST /scenarios/validate` is what the editor calls on every change. It returns the
full actionable issue list — never a repaired scenario.

```jsonc
{
  "scenario_id": "headon-aisle",
  "revision": 1,
  "launchable": true,
  "diagnostic_allowed": true,
  "issue_count": 1,
  "structural_count": 0,
  "workload_count": 0,
  "issues": [
    { "code": "reachability_is_estimated", "severity": "warning",
      "message": "reachability for 2 task leg(s) was estimated by a 0.25 m flood fill...",
      "remedy": "treat an UNREACHABLE planner result at run time as authoritative for that leg" }
  ],
  "checks_not_performed": [
    "multi-robot reachability and deadlock-freedom are not analysed statically"
  ]
}
```

`checks_not_performed` is always present. A validation that claims completeness it
does not have is worse than no validation.

---

## 4. Runs

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs` | All attempts, including failed, timed out and cancelled |
| `GET` | `/runs/{id}` | Manifest, state, result, recording health |
| `GET` | `/runs/{id}/state` | Context-bar snapshot |
| `GET` | `/runs/{id}/robots` | Robot inspections |
| `GET` | `/runs/{id}/zones` | Zone inspections |
| `GET` | `/runs/{id}/tasks` | Task inspections |
| `GET` | `/runs/{id}/events` | Paged durable events |
| `GET` | `/runs/{id}/telemetry` | Paged replaceable telemetry |
| `GET` | `/runs/{id}/communication` | Directed communication matrix |
| `GET` | `/runs/{id}/faults` | Fault records |
| `GET` | `/runs/{id}/commands` | Command plane history |
| `POST` | `/runs/{id}/export` | Write the evidence bundle |

`GET /runs` returns **every attempted run id**, including failures. Dropping failed
runs would be the easiest way to make a result look better than it is.

### Context bar payload

```jsonc
{
  "run_id": "r-20260102-a1b2c3",
  "mode": "deterministic",        // deterministic | processes | replay
  "scenario_id": "headon-aisle",
  "scenario_revision": 1,
  "map_digest": "41c69d9cdb90",
  "sim_time_s": 184.40,
  "wall_time_s": 12.80,           // null unless actually measured
  "speed_multiplier": 1.0,
  "robot_count": 3,
  "coordination_policy": "canonical_sequential",
  "connection": "live",           // live | reconnecting | stale | closed
  "recording_healthy": true,
  "recording_gaps": 0
}
```

`wall_time_s` is `null` unless measured. It is never filled with simulation time to
make the field look populated.

---

## 5. Inspections

### Robot

```jsonc
{
  "robot_id": "amr-01",
  "session_id": "s-7f3a",
  "pid": 18432, "host": "localhost",
  "pose_estimate": { "x": 13.5, "y": 8.4, "theta": 1.5708,
                     "observed_at_s": 184.30, "age_s": 0.10,
                     "uncertainty_m": 0.02, "uncertainty_rad": 0.01,
                     "stale": false },
  "velocity": { "linear_mps": 0.0, "angular_radps": 0.0 },
  "motion_state": { "actuator": "enabled", "stop_reason": "zone_authority_missing" },
  "battery": { "source": "simulated", "fraction": 0.91, "drain_model": "..." },
  "task": { "task_id": "t-headon-up", "ownership_version": 3,
            "state": "in_transit", "custody": "attached" },
  "planner": { "status": "traversing", "plan_version": 7, "goal": [24.2, 15.5],
               "zones_touched": ["zn-headon-mid"] },
  "occupied_zones": [],
  "requested_zones": ["zn-headon-mid"],
  "last_accepted_intent": { "from_seq": 88, "age_s": 0.2, "freshness": "fresh" },
  "why_waiting": {
    "waiting": true,
    "reason": "zone zn-headon-mid is PROMISED to amr-02",
    "blocking_resource": "zn-headon-mid",
    "blocking_peer": "amr-02",
    "evidence_age_s": 0.2,
    "recovery_condition": "reconciled release from amr-02, or the zone fenced"
  }
}
```

`why_waiting` is the single most important object in the API: it makes the fleet's
behaviour explainable rather than merely observable.

### Zone

```jsonc
{
  "zone_id": "zn-headon-mid",
  "state": "promised",
  "authority": { "requester": "amr-02", "requester_session": "s-2b91",
                 "request_version": 1, "grant_id": "a1f4...", "phase": "acquiring" },
  "request": { "movement": "forward", "entry_pose": [...], "exit_pose": [...],
               "transaction_id": "txn-9f2c" },
  "required_voters": ["amr-01", "amr-02", "amr-03"],
  "received_grants": ["amr-01"],
  "pending_voters": ["amr-02", "amr-03"],
  "required_set_digest": "9c1e...",
  "observed_set_digest": "4b70...",
  "digests_match": false,
  "entry_withheld_because": "grant set incomplete: 1 of 3",
  "queue": ["amr-01"],
  "stop_lines": ["sl-zn-headon-mid-in", "sl-zn-headon-mid-out"]
}
```

`digests_match` is computed, not asserted. A mismatch means the owner may **not**
enter, and the UI says so.

### Task

```jsonc
{
  "task_id": "t-headon-up",
  "state": "in_transit",
  "owner": { "robot_id": "amr-01", "ownership_version": 3, "allocation_round": 2 },
  "custody": { "state": "attached", "holder": "amr-01", "custody_version": 1 },
  "bid_set_digest": "5d2a...",
  "bids": [
    { "robot_id": "amr-01", "total_cost": 41.2, "feasible": true,
      "components": [ { "name": "travel_time_s", "value": 38.0, "unit": "s" },
                      { "name": "queue_delay_s", "value": 2.5, "unit": "s" },
                      { "name": "battery_cost_c", "value": 0.6, "unit": "c" },
                      { "name": "service_time_s", "value": 3.0, "unit": "s" } ] },
    { "robot_id": "amr-03", "total_cost": 52.8, "feasible": true, "components": [...] }
  ],
  "explicit_no_bid": [],
  "completion_credit": false,
  "completion_evidence": null
}
```

Bid components are shown verbatim rather than collapsed into a number, because
"why this robot" is the question an operator actually asks.

---

## 6. Command plane

Explicitly labelled, and recorded at four stages.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/runs/{id}/commands` | Issue a command |
| `GET` | `/runs/{id}/commands` | Command history |

```jsonc
// POST body
{
  "command": "request_stop",
  "params": { "robot_id": "amr-01", "reason": "operator inspection" },
  "idempotency_key": "stop-amr01-001"
}
```

```jsonc
// CommandRecord - all four stages, separately
{
  "command_id": "cmd-0031",
  "command": "request_stop",
  "requested_at_s": 184.40,
  "acknowledged_at_s": 184.42,
  "applied_at_s": 184.55,
  "observed_stopped_at_s": null,
  "status": "applied_not_observed",
  "reason": "operator inspection",
  "note": "command acknowledged and applied; motion not yet observed to have ceased"
}
```

| Command | Meaning |
|---|---|
| `start_simulation` | Harness control |
| `pause_simulation` / `resume_simulation` | Harness control — pauses logical deadlines |
| `request_stop` | **Requests** a controlled stop. Not an emergency stop |
| `inject_fault` | Fault laboratory |
| `cancel_run` | Cancels without corrupting artefacts |

`status` values distinguish `requested`, `acknowledged`, `applied`,
`applied_not_observed` and `observed_stopped`. **A sent command is not an observed
stop**, and the API never collapses the two.

Every command is labelled as controlling **the experiment harness**. None is a
certified physical emergency stop, because none exists.

---

## 7. Fault laboratory

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/runs/{id}/faults` | Active and elapsed faults |
| `POST` | `/runs/{id}/faults` | Inject (manual, timestamped) |
| `DELETE` | `/runs/{id}/faults/{fault_id}` | Remove |

```jsonc
{
  "fault_id": "fx-manual-partition",
  "state": "active",
  "target": { "channel": "coordination", "kind": "partition",
              "sender": "amr-02", "receiver": "amr-03" },
  "started_at_s": 60.0,
  "ended_at_s": null,
  "manual": true,
  "injected_by": "operator",
  "expected_invariant": "amr-02 stops before an unconfirmed stop line; amr-01 unaffected"
}
```

Validation rejects an untargeted channel fault with an actionable message, since the
brief requires directed injection rather than a global toggle.

---

## 8. Experiments

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/experiments` | Batch matrix |
| `POST` | `/experiments` | Run a batch over revisions × seeds × policies × fault profiles |
| `GET` | `/experiments/{batch_id}` | Runs, **configuration diff**, eligibility, paired table |
| `GET` | `/experiments/{batch_id}/report` | Markdown report plus raw CSV |

Run states: `queued`, `running`, `completed`, `unsafe`, `failed`, `timed_out`,
`cancelled`. All are preserved.

```jsonc
{
  "configuration_diff": [
    { "field": "policy.coordination", "baseline": "stop_and_wait",
      "candidate": "canonical_sequential", "material": true },
    { "field": "scenario.map_digest", "baseline": "41c6...", "candidate": "41c6...",
      "material": false }
  ],
  "pairs": [
    { "seed": 20260101, "baseline_makespan_s": 312.4, "candidate_makespan_s": 268.9,
      "reduction_pct": 13.9, "eligible": true },
    { "seed": 20260102, "baseline_makespan_s": null, "candidate_makespan_s": 301.0,
      "reduction_pct": null, "eligible": false,
      "excluded_reason": "baseline_timed_out: no makespan may be imputed" }
  ],
  "aggregate": {
    "eligible_pairs": 29, "excluded_pairs": 1,
    "median_reduction_pct": 17.2,
    "bootstrap_ci_95": [11.4, 22.8],
    "method": "bootstrap percentile on per-pair ratios, median point estimate, B=10000, seed=7",
    "caveat": "95% nominal; percentile intervals under-cover at small n"
  }
}
```

`reduction_pct` is `null` for an ineligible pair — never imputed. `excluded_pairs`
and the reason travel with every aggregate.

---

## 9. Replays

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/replays` | Available runs |
| `GET` | `/replays/{run_id}` | Replay index |
| `GET` | `/replays/{run_id}/events` | Events for reconstruction |

```jsonc
{
  "run_id": "r-20260102-a1b2c3",
  "event_count": 20184,
  "first_sim_time_s": 0.0, "last_sim_time_s": 321.6,
  "categories": { "authority": 312, "evaluation": 1204, "telemetry": 20184,
                  "task": 96, "safety": 48, "fault": 4, "command": 7 },
  "gaps": [],
  "complete": true
}
```

`complete: false` when an unrecovered gap exists in a durable category. A replay of
an incomplete run is usable but visibly labelled.

---

## 10. Streaming

```text
WS /api/v1/stream?run_id=<id>[&cursor=<last seen seq>]
```

```jsonc
type StreamEnvelope =
  | { kind: "snapshot"; run_id: string; cursor: number; payload: RunStateSnapshot }
  | { kind: "telemetry"; run_id: string; cursor: number; samples: TelemetrySample[] }
  | { kind: "event";    run_id: string; cursor: number; events: DomainEvent[] }
  | { kind: "gap";      run_id: string; cursor: number; gap: RecordingGap }
  | { kind: "status";   run_id: string; cursor: number;
      status: "live" | "stale" | "paused" | "reconnecting" | "closed"; since?: string }
```

### Semantics

| Rule | Behaviour |
|---|---|
| First connect | A `snapshot` frame, then deltas |
| Reconnect with `cursor` | Continue from that sequence |
| Cursor expired | A **fresh `snapshot`**, plus an explicit notice — never a silent gap |
| `has_more` on a page | Client refetches; gaps are never papered over |
| Backpressure | Server sheds **replaceable** telemetry only. Authority and evaluation events are never shed |
| Slow client | Bounded queue. A slow browser never blocks agent control |
| Client memory | Bounded buffers and ring-buffer chart history |

---

## 11. System

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness plus version identity |
| `GET` | `/system/doctor` | Runtime self-check |

```jsonc
{ "status": "ok", "version": "0.1.0",
  "schema_version": "1.0.0", "protocol_version": "1.0.0",
  "mode": "deterministic", "run_id": "r-20260102-a1b2c3",
  "recording_healthy": true, "uptime_s": 412.6 }
```

`/system/doctor` reports only values it actually collected. Latency and resource
figures appear **only when measured**; otherwise the field is `unavailable` rather
than `0`.

---

## 12. Conventions

| Concern | Rule |
|---|---|
| Versioning | `/api/v1`. Breaking changes mean a new prefix |
| Naming | Plural nouns for collections, `{id}` for members |
| Time | `*_at_s` for display, `*_ns` with an explicit domain for precision |
| Units | Field names carry units: `_m`, `_mps`, `_radps`, `_s`, `_ns`, `_c` |
| Unknown fields on input | Rejected (422). Never ignored |
| Pagination | `?limit=` + `?after_seq=`, always with `next_seq` |
| Filters | `?robot_id=`, `?zone_id=`, `?task_id=`, `?categories=` on events |
| Auth | None on loopback; optional bearer token off-loopback |
| CORS | Explicit origins, empty by default; no wildcard |

---

## 13. Command reference

```text
nihara doctor
nihara run      --scenario <file> [--mode deterministic|processes] [--report]
nihara benchmark --suite <file> --output <dir>
nihara replay   --run <dir>
nihara report   --run <dir>
nihara scenarios export | list | validate | show <id>
nihara serve    [--host 127.0.0.1] [--port 8100]
nihara agent    --robot <id> --scenario <file> --endpoint <host:port>
```

Exit codes: `0` ok · `1` error · `2` invalid input · `3` io/path problem ·
`4` degraded · `5` required capability unavailable.

| Command | Done |
|---|---|
| `nihara doctor` | Reports toolchain, contracts, scenarios, ports, storage; measured values only |
| `nihara scenarios export` | Rebuilds the 7 named scenarios from the builders |
| `nihara scenarios validate` | Full actionable issue list; non-zero exit on invalid input |
| `nihara run` | — |
| `nihara benchmark` | — |
| `nihara replay` / `report` | — |
| `nihara serve` | — |
| `nihara agent` | — |

Commands register **only** when their runtime module is importable, so the CLI never
offers something that cannot run. `nihara --help` names the absent ones and
`nihara doctor` explains why.
# Benchmark methodology, eligibility and results

**Read this before quoting any number from this project.**

The reported objective is a ≥20 % reduction in total task-completion time against
stop-and-wait on overlapping routes. That is a **target**, not a result. No paired
measurement had been executed when this document was written, so the figure is
reported neither way until `pnpm benchmark:full` produces an export.

---

## 1. What is being compared

Two separate comparisons, never conflated:

### Coordination-only
**Identical task assignments. Identical routing policy. Only the movement-coordination policy differs.**

This isolates the contribution of the coordination protocol, which is the project's
actual contribution. Assignments come from the scenario (`RobotStart.assigned_task_id`),
so both arms execute the same legs.

### End-to-end
**Declared assignment and routing policies may differ; the task set and initial conditions are identical.**

This measures the whole system, including the local auction and blocked-route
adaptation, but it cannot attribute the difference to coordination alone.

Both arms share, exactly:

- the same immutable scenario snapshot (map, tasks, fault schedule),
- the same robot geometry and speed limits,
- the same sensing model and noise seeds,
- the same actuator model and command TTL,
- the same task release times and service durations,
- the same stopping conditions and safety gate,
- the same seeds, paired.

If any of those differ between arms, the pair is **excluded**, not adjusted.

---

## 2. The two policies

### `stop_and_wait` — the frozen baseline

A robot reaching a constrained passage stops **completely** at the stop line and
waits until the passage is physically clear before proceeding. It then traverses at
its normal speed limit.

The baseline is **not** sabotaged. It uses:

- the same actuator model, so its stops and starts cost the same acceleration time,
- the same safety gate,
- the same sensing, including noise and latency,
- the same footprint and stopping-distance budget,
- the same planner and velocity profile,
- a real, correct implementation of waiting, not a sleep.

Weakening it would make the headline number meaningless. If the measured improvement
depends on handicapping the baseline, that is stated rather than concealed.

### `canonical_sequential` — the candidate

Exclusive zones acquired by canonical sequential grant protocol: every requester
acquires every voter, including its own, in one global order; at most one
outstanding grant per robot; conservative occupancy retention; freshness-aware
stopping. Full protocol in `docs/protocol/ZONE_PROTOCOL.md`.

The candidate is expected to be **slower per traversal** — it pays acquisition
latency. Its advantage is that robots pipeline instead of serialising: while one
robot traverses, others prepare, and waiting happens at berths rather than in
aisles. Whether that nets out is an empirical question, and the answer is whatever
the measurement says.

---

## 3. Metrics

### Headline

**Makespan** — elapsed simulation time from the declared common run start to
delivery of **every** required task in a completed workload.

```text
makespan = sim_time_of_last_required_delivery − sim_time_of_common_run_start
```

If the workload did not complete, makespan is `None`. **A deadlocked or timed-out
run never gets an imputed makespan.** Reporting an imputed value would let a
failure masquerade as a fast run.

### Paired reduction

```text
paired makespan reduction (%) = 100 × (baseline_makespan − candidate_makespan) / baseline_makespan
```

Computed **only** on eligible completed pairs, per seed.

Guards, all explicit:

| Guard | Behaviour |
|---|---|
| `baseline_makespan == 0` | Pair excluded; division by zero is never performed |
| Either arm ineligible | Pair **excluded and counted**, shown beside the aggregate |
| Either arm incomplete or unsafe | Pair excluded; the failure rate is reported |
| Seeds unpaired | Reported as unpaired; never silently dropped |
| Expected-failure scenario | Excluded from success comparison by construction |

An illustrative arithmetic example is not a result. Every published figure comes
from an exported artefact.

### Secondary

| Metric | Definition | Why |
|---|---|---|
| Task flow time | Delivery time − release time, per task | Where the time actually goes |
| Throughput | Completed tasks / makespan | Scale-free |
| Completion rate | Completed / required | Must be reported alongside any aggregate |
| Mean wait time | Total time below the speed limit while assigned | The coordination cost |
| Collision count | Independent evaluator observations | Zero is an observation, not a proof |
| Minimum clearance | Smallest observed body separation | Detects near-misses a count misses |
| Conflicting authority | Two robots authorised in one zone | Protocol violation, always reported |
| Stop-line violations | Crossing without the named authority | Independent geometric check |
| Duplicate custody | Two holders of one payload | Integrity violation |
| Timeouts / interventions | Count and reason | Operationally important |
| Planning duration | Wall-clock per plan, real-process mode only | Budget compliance |
| CPU / memory | Measured, or `unavailable` | Never zero-filled |
| Communication volume | Messages and bytes per robot | Cost of decentralisation |

A metric that was not collected is `MetricValue.unavailable(key, reason)`. **Never
`0`.**

---

## 4. Eligibility rules

A run is **eligible for a successful-completion comparison** only if **all** hold:

1. `outcome == SUCCESS`
2. `collisions == 0`
3. `tasks_completed == tasks_total`
4. `makespan_s is not None`
5. no unrecovered `RecordingGap` in a durable evidence category
6. the scenario is not an expected-failure diagnostic

Excluded pairs and failure rates are displayed **beside** any aggregate. An
incomplete or unsafe run never receives a success badge because its partial
duration was short.

---

## 5. Experimental design

### Seeds

The main family uses **at least 30 preselected seeds**, paired across policies:
identical `(scenario, seed, fault_profile)` for both arms.

| Suite | Seeds | Purpose | Runtime class |
|---|---|---|---|
| `scenarios/suites/smoke.json` | 3–5 | CI, catches obvious regressions | minutes |
| `scenarios/suites/main.json` | ≥30 | the reported measurement | hours |

**Predeclared.** Development tuning happens on the smoke suite and a separate
*development* seed set. The held-out seed set is not used for tuning. Any change to
the evaluation itself increments an evaluation version rather than being silently
folded in.

Failed and timed-out seeds are **recorded, not deleted**. Reducing the sample size
is permitted only with the reduction and its reason stated.

### Scenarios

Benchmark maps are **authored diagnostic maps** designed so that the contention is
the thing under test: head-on aisle, three-way junction, cycle with holding space.
Start/goal MAPF benchmarks are not used directly — see §7.

### Workload generation

Task generation is independent of assignment. The scenario declares pickup/drop
stations, release times and service durations; the auction is a separate concern.
Documented seeds and map hashes accompany every export.

---

## 6. Statistics

Primary estimator: **bootstrap percentile confidence interval on the per-pair
ratios**, with the **median** as the point estimate, plus a **sign test**.

Rationale, from `docs/RESEARCH.md`: NIST routes intractable location and median
intervals to the bootstrap; the median is robust to the outliers that a failed-but-
fast run produces, which matters here because one arm may occasionally be fast
*because* it gave up.

Reported explicitly:

- the interval is **95 % nominal**. Percentile intervals under-cover at small `n`;
  this is stated rather than hidden.
- `n`, the seed list, and the bootstrap seed are all reported.
- the per-pair ratios are exported so the interval can be recomputed independently.
- **a bootstrap is never computed from a single observation.**

Also reported: the count of excluded pairs, the reason for each exclusion, and the
failure rate per arm.

---

## 7. Benchmark map provenance

Authored maps are used for the main comparisons because the claim is about a
warehouse contention scenario, not about MAPF benchmark scores.

Moving AI MAPF benchmarks were reviewed with attribution (`docs/RESEARCH.md`,
`research/sources.json`). They are **not** used as-is, and the reason is recorded:

> A start/goal MAPF scenario is **not** a pickup-delivery workload. It has no
> payload, no service time at either end, no pickup confirmation, and no custody.

If MAPF-derived scenarios are ever added, the transformation must be documented
alongside the biases it introduces: pickup at the start cell, drop at the goal cell,
a declared service time at each, and a task release schedule. The map and scenario
file hashes are recorded with the results.

---

## 8. Ablations

Each ablation isolates a real design decision. All retain the safety gate except
where noted, and unsafe variants are marked `unsafe_research_variant` so their
results can never be presented as safety evidence.

| Ablation | Flag | Question |
|---|---|---|
| Fixed vs fairness-aware priority | `fairness_aware_priority` | Does FIFO queue order starve anyone? |
| Task reassignment on/off | `task_reassignment` | Does reassignment help or thrash? |
| Temporal vs spatial planning | `temporal_planning` | Does the approximate SIPP variant predictably reduce conflict? |
| Freshness handling variants | `freshness` variants | Does freshness-aware stopping cost throughput? |
| Timer-expiry occupancy | `timer_expiry_occupancy` **UNSAFE** | Quantifies the safety cost of the shortcut. Never enabled for physical actuation |
| No safety gate | `disable_safety_gate` **UNSAFE** | Quantifies how much the gate actually contributes |

The two unsafe ablations exist to **measure** what a shortcut would cost. Their runs
are research observations, never evidence of safety, and
`FeatureFlags.physical_actuation_permitted()` refuses to let them gate actuation.

---

## 9. Environment

Every export records the environment: OS and version, architecture, Python version,
CPU model and count, container status, and wall-clock start/end for real-process
runs. `EnvironmentRecord` is filled by `capture()`, so a missing field is
`unavailable` rather than invented.

Authoring machine (2026-10-02): Windows 11 win32, Python 3.12.14, Node 24.13.0.
Results measured on any other machine are labelled with that machine's record.

---

## 10. Reproducing a result

```bash
# fast CI suite
pnpm benchmark:smoke

# full paired suite (the reported measurement)
pnpm benchmark:full

# or explicitly
uv run nihara benchmark --suite scenarios/suites/main.json --output var/benchmarks/main

# recompute the headline from the raw export, independently
uv run nihara report --run var/benchmarks/main/<batch-id>
```

An export contains: the batch definition, every run manifest, per-run raw metrics,
the per-pair ratio table, the exclusions with reasons, the environment, and the
event-log paths. **Metrics can be recomputed from it without rerunning anything** —
which is the property that makes the number evidence rather than an assertion.

---

## 11. Results

**No paired benchmark result had been executed when this document was written.**

| Field | Value |
|---|---|
| Measured paired reduction | **unmeasured** |
| Eligible pairs | 0 |
| Excluded pairs | 0 |
| Seeds run | 0 |
| Observed collisions | **unmeasured** |

The ≥20 % objective is reported as **not yet measured**. When the suite runs, this
table is replaced with the actual figures, the environment, and the uncertainty —
achieved or not achieved. It is not estimated, and it is not projected.

See `docs/KNOWN_LIMITATIONS.md` §1 for the same statement in context, and
`docs/evidence/CLAIM_EVIDENCE.md` rows 3.7–3.9 for the per-claim status.
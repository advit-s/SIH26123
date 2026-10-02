# NĪHĀRAMESH — three-minute demo script

**Read this first.** The ≥20 % makespan-reduction target is a **target, not a result**.
It is reported as **unmeasured** until a paired benchmark suite is executed. This
script shows measured *behaviour* — coordination, degraded operation, replay,
evidence — and is explicit where a number does not yet exist.

Full walkthrough with examiner Q&A: [`docs/DEMO.md`](docs/DEMO.md).

---

## 0. Prepare (once)

```bash
pnpm bootstrap
pnpm doctor
```

`doctor` exits `0` when every required capability is present. Optional items (Docker,
ROS 2) may be reported as degraded — that is honest reporting, not failure.

---

## 1. One clean three-robot run

```bash
uv run nihara run --scenario scenarios/three-way-junction.r1.json --mode deterministic --report
```

Three agents contend for one junction zone. **One grant at a time.** The zone
inspector shows `required_voters` vs `received_grants` and a computed
`digests_match`; entry is withheld until they agree. Right of way follows canonical
acquisition order (ascending `robot_id`) — not arrival time, not a central arbiter.

> No leader exists. Each robot collects every grant itself.

## 2. A directed partition

```bash
uv run nihara run --scenario scenarios/asymmetric-partition.r1.json --mode processes --report
```

`amr-01 → amr-02` is cut for 45 s while `amr-03` stays connected.

- **Only that pair degrades.** `amr-03` keeps delivering.
- The affected robot **retains occupancy** and stops before a stop line it can no
  longer confirm. It does not assume the aisle is empty.
- The communication matrix distinguishes `amr-01 hears amr-02` from
  `amr-02 hears amr-01` — a one-way cut produces *inconsistent* peer visibility.
- Removing the fault restores **communication, not movement permission**.

> A lost heartbeat removes *permission to assume*. It never removes a physical robot
> from an aisle. There is no force-release, by design.

## 3. Crash a robot holding a zone

Inject `PROCESS_CRASH` on a robot currently **inside** a zone.

The zone moves to **`FENCED`** — explicitly unavailable, visibly reported. Others
queue. Nothing times out and frees the aisle, and **there is no force-release button**.
A restart still owes its promise from the durable journal.

> We removed the deadlock class structurally rather than detecting it. A robot holding
> a grant blocking its zone is a throughput cost we chose to pay rather than a safety
> risk we chose to take.

## 4. Kill the API — the architecture demonstration

With a run in progress, stop the dashboard and the API process.

The world keeps integrating. The robots keep planning, bidding, coordinating and
stopping. The cockpit shows a **data gap**, not zeros.

> Stopping the dashboard is not a decentralisation test. If the robots died with it,
> that would be a parent-process accident dressed up as decentralisation. The
> architecture test starts the world as an independent process tree for exactly this
> reason.

If the **world** stops, agents detect stale telemetry and stop conservatively.
Software simulation cannot integrate physics without its host.

## 5. Why is this robot waiting?

Select a waiting robot. The inspector answers all of it:

| Field | Shows |
|---|---|
| `why_waiting.reason` | `"zone zn-headon-mid is PROMISED to amr-02"` |
| `blocking_resource` / `blocking_peer` | Which zone, which robot |
| `evidence_age_s` | How old the evidence is |
| `freshness` | `fresh` / `stale` / `unknown` |
| `recovery_condition` | What would unblock it |

> Every wait is attributed. A stop the system cannot explain is a defect.

## 6. Replay it

**Replays** → the run → jump to first fault.

Play, pause, speed, seek, step by event. **Seek backwards** and future completions,
grants and alerts **disappear**. An unknown event version fails visibly rather than
silently omitting state. This is recorded playback, labelled as such.

> Replay rebuilds state by folding events up to the cursor. There is no undo step, so
> a future fact cannot survive a backward seek.

## 7. Experiments — what we can and cannot claim

The **configuration diff** between arms appears before comparison. Run states include
`unsafe`, `failed`, `timed_out`, all preserved. **Excluded pairs and failure rates sit
beside every aggregate.**

If no paired suite has been run, the headline reads **unmeasured**.

> The target is a 20 % reduction against stop-and-wait. We have not measured it yet,
> so we are not claiming it — in either direction. Our baseline is not handicapped: it
> pays the same stopping costs, same actuator model, same safety gate. See ADR 0012.

## 8. The evidence

```text
var/runs/<run-id>/
  manifest.json      revisions, digests, policies, seeds, environment
  scenario.json      the exact immutable snapshot
  events.jsonl       append-only durable log
  result.json        outcome, metrics, eligibility
```

> Every number traces to a manifest, an environment and an event log, and the metrics
> can be recomputed from those files without rerunning anything. A number you cannot
> recompute is a number you cannot defend.

---

## Then open the cockpit

```bash
pnpm dev
```

**http://127.0.0.1:5173**

1. **Operations** — the warehouse map dominates; select a robot and read *why waiting*.
2. **Scenarios** — the library, validation, the semantic editor, the fault laboratory.
3. **Experiments** — the run matrix and the paired comparison.
4. **Replays** — recorded playback with backward seek.
5. **System** — `doctor` output: processes, endpoints, journals, schema, recording health.

The context bar always shows execution mode, run id, scenario revision, simulation
time, speed, robot count, policy, connection and recording health — so replay, paused
simulation and a live process run are never confused with each other.

---

## If you are asked "is it safe?"

The honest answer is in three parts, and all three are in
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md):

1. **A zero collision count is an observation, not a proof.** Two independent
   algorithms check overlap, and the world genuinely applies colliding commands
   rather than suppressing them.
2. **Occupancy is retained conservatively.** No timer frees an aisle; there is no
   force-release.
3. **This is not a certified safety system**, and no software collision monitor in
   this project is one.

---

## Documentation index

| Document | Read it for |
|---|---|
| [`docs/DEMO.md`](docs/DEMO.md) | The full eight-act walkthrough and examiner Q&A |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Authority and failure boundaries |
| [`docs/protocol/ZONE_PROTOCOL.md`](docs/protocol/ZONE_PROTOCOL.md) | Protocol states, transitions, progress argument |
| [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) | Methodology, eligibility, results (**unmeasured**) |
| [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) | What is *not* proven, and why |
| [`docs/evidence/CLAIM_EVIDENCE.md`](docs/evidence/CLAIM_EVIDENCE.md) | Every claim → its evidence |
| [`docs/adr/`](docs/adr/) | Why each decision was made, and what would change it |
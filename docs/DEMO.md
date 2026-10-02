# Demo script

The three-minute path, matching the actual application. Every command below is real
and every claim below is one the application can display.

> **Read this first.** The ≥20 % target is **unmeasured**. The demo shows measured
> *behaviour* — coordination, degraded operation, replay, evidence — and the
> Experiments page shows **not measured** where a number has not been produced.
> Nothing here claims a performance result.

---

## Before you start

```bash
pnpm bootstrap        # install deps, generate contracts, export scenarios
pnpm doctor           # confirm the toolchain; exit 0 means all required capabilities present
```

Expected from `doctor`: no required capability missing. Optional items may be
reported as degraded (Docker absent, ROS absent) — that is honest, not a failure.

---

## Act 1 — One clean three-robot run (≈60 s)

```bash
uv run nihara run --scenario scenarios/three-way-junction.r1.json --mode deterministic --report
```

Three robots, one junction zone, contending for right of way.

**What to point at:**

- Three agents, **one grant at a time**. The other two hold at named berths.
- The zone inspector shows `required_voters` vs `received_grants`, and
  `digests_match`. Entry is withheld until both agree.
- Right of way follows **canonical acquisition order** (ascending `robot_id`) — not
  arrival time, and not a central arbiter.
- Each robot made the decision **in its own process**. The API is not in the loop.

**Command to say:** *"There is no leader. Each robot collects every grant itself, in
the same global order, and refuses to move until its own computed digest matches what
the voters recorded."*

---

## Act 2 — Inject a partition (≈60 s)

Open the cockpit, or:

```bash
uv run nihara run --scenario scenarios/asymmetric-partition.r1.json --mode processes --report
```

The directed channel `amr-01 → amr-02` is cut for 45 s while `amr-03` stays fully
connected.

**What to point at:**

- **Only that pair degrades.** `amr-03` keeps delivering.
- The affected robot **retains occupancy** of anything it held and **stops before a
  stop line it can no longer confirm**. It does not assume the aisle is empty.
- The communication matrix distinguishes `amr-01 hears amr-02` from
  `amr-02 hears amr-01`. The cut is one-way, so the pair sees *inconsistent* peer
  visibility.
- Fault removed → **communication restored, movement permission not restored.** The
  robots must reconcile before resuming.

**Command to say:** *"A lost heartbeat removes permission to assume. It never removes
a physical robot from an aisle. There is no force-release, by design."*

---

## Act 3 — Crash a robot holding a zone (≈45 s)

Inject `PROCESS_CRASH` on a robot that is currently **inside** a zone.

**What to point at:**

- The zone goes to **`FENCED`** — explicitly unavailable, visibly reported.
- Other robots **queue**. Nothing times out and frees the aisle.
- There is **no force-release button**. Recovery is a supervised, operator-visible
  transition.
- The authority journal survives in the crashed robot's own process state, so a
  restart **still owes its promise** rather than forgetting it.

**Command to say:** *"We removed the deadlock class structurally instead of detecting
it. A robot holding a grant blocks its zone, and that is a throughput cost we chose to
pay rather than a safety risk we chose to take."*

---

## Act 4 — Crash the API (≈30 s) — the architecture demonstration

With a run in progress, stop the dashboard and the API process.

**What to point at:**

- The world **keeps integrating**. The robots **keep planning, bidding, coordinating
  and stopping**.
- Their authority journals keep advancing.
- The cockpit shows a **data gap** — not a set of zeros.

**Command to say:** *"Stopping the dashboard is not a decentralisation test. If the
robots died with it, that would be a parent-process accident dressed up as
decentralisation. The architecture test starts the world as an independent process
tree for exactly this reason."*

Then note the separate case: if the **world** stops, agents detect stale telemetry and
stop conservatively. Software simulation cannot integrate physics without its host.

---

## Act 5 — Why is this robot waiting? (≈45 s)

Select a waiting robot.

**What to point at** — the inspector answers all of it:

| Field | Shows |
|---|---|
| `why_waiting.reason` | `"zone zn-headon-mid is PROMISED to amr-02"` |
| `blocking_resource` / `blocking_peer` | Which zone, which robot |
| `evidence_age_s` | How old the evidence is |
| `freshness` | `fresh` / `stale` / `unknown` |
| `recovery_condition` | What would unblock it |

**Command to say:** *"Every wait is attributed. If the system cannot explain a
stop, that is a defect, not a limitation of the display."*

---

## Act 6 — Replay it (≈60 s)

Open **Replays** → the run → jump to first fault.

**What to point at:**

- Play, pause, speed, seek, step by event.
- **Seek backwards** and watch future task completions, grants and alerts **disappear**.
- An **unknown event version fails visibly** rather than silently omitting state.
- This is **recorded playback**, labelled as such — not a fresh re-simulation.

**Command to say:** *"Replay rebuilds state by folding events up to the cursor. There is
no undo step, so a future fact cannot survive a backward seek."*

---

## Act 7 — Experiments: what we can and cannot claim (≈60 s)

Open **Experiments**.

**What to point at:**

- The **configuration diff** between arms, shown *before* comparison.
- Run states including `unsafe`, `failed`, `timed_out` — all preserved.
- **Excluded pairs and failure rates beside every aggregate.**
- If no paired suite has been run, the headline reads **"unmeasured"**. Say so.

**Command to say:** *"The target is a twenty percent reduction against stop-and-wait.
We have not measured it yet, so we are not claiming it — in either direction. Our
baseline is not handicapped: it pays the same stopping costs, uses the same actuator
model and the same safety gate. See the ADR."*

---

## Act 8 — Evidence (≈30 s)

Show one exported run directory:

```text
var/runs/<run-id>/
  manifest.json      revisions, digests, policies, seeds, environment
  scenario.json      the exact immutable snapshot
  events.jsonl       append-only durable log
  result.json        outcome, metrics, eligibility
```

**Command to say:** *"Every number traces to a manifest, an environment and an event
log. The metrics can be recomputed from these files without rerunning anything. A
number you cannot recompute is a number you cannot defend."*

---

## Questions an examiner is likely to ask

**"How do you know it is decentralised?"**
Each robot collects every grant itself in one global order. There is no leader, no
central arbiter, and no MAPF solver in the backend. The API holds no authority — the
architecture test asserts the import graph, not a claim. `transport/` and
`coordination/` do not import the API.

**"What happens when two robots want the same aisle?"**
Exactly one traverses. The other holds at a named berth. The zone inspector shows the
blocking request, peer, resource, evidence age and recovery condition.

**"Isn't serialised acquisition slow?"**
Yes, and it is measured rather than argued. Acquisition costs one round trip per
voter. The candidate's advantage is pipelining: while one robot traverses, others
prepare. Whether that nets out is what the benchmark measures. The availability cost
is documented in ADR 0003.

**"How do you know there were no collisions?"**
We do **not** claim collision freedom. Two independent algorithms check for overlap —
a swept-hull test and a fine-sampling oracle — and the world genuinely applies
colliding commands rather than suppressing them. A zero count is an **observation**
under this geometry and timing, not a proof.

**"What if a robot crashes holding an aisle?"**
The zone is fenced and stays unavailable. There is no force-release, because the
crashed robot may be physically inside it. That is a deliberate throughput cost.

**"How is the 20 % target measured?"**
Paired seeds, identical geometry, speed limits, sensing and stopping conditions in both
arms; eligibility rules that exclude incomplete or unsafe runs; excluded pairs
reported beside the aggregate; a bootstrap percentile interval on per-pair ratios with
the median as the point estimate. Currently: **unmeasured**. See `docs/BENCHMARKS.md`.

**"What is the AI here, precisely?"**
Onboard A* search, constrained velocity profiles, intent prediction from a spatial
plan, and multi-agent negotiation. Not an LLM, and not a learned model. No learned
component is shipped, because shipping an untrained one described as working would be
worse.

**"Can this run on a robot?"**
Not as shipped. Physical actuation is disabled by default and there is no API endpoint
that reaches hardware. There is a ROS 2 interface boundary and a fixture-tested
adapter, but no `colcon build` has been executed, and we say so rather than implying
otherwise.

---

## What to avoid claiming

| Do not claim | Say instead |
|---|---|
| "Zero collisions, therefore safe" | "No collision was observed in this run" |
| "We improved throughput by 20 %" | "The target is unmeasured; here is the methodology" |
| "It uses AI" | "It uses search, constrained decisions, prediction and negotiation" |
| "ROS 2 compatible" | "A ROS 2 interface boundary exists and its adapter is fixture-tested; the build is unexecuted" |
| "Industrial safety certified" | "Not certified; this is a simulation laboratory" |
| "Deadlock-free" | "Order-inversion-free by construction; liveness is not guaranteed once a holder fails" |

Every one of these is in `docs/KNOWN_LIMITATIONS.md` with the reason.
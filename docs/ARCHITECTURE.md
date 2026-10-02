# Architecture and authority boundaries

NĪHĀRAMESH is a warehouse fleet-coordination **laboratory**. This document
describes who is allowed to decide what, and what happens when each component
dies. Both questions matter more than the component list, because the project's
central claim is about *where authority lives* and what survives its loss.

---

## 1. Processes and responsibilities

```text
                       ┌──────────────────────────────────────────────┐
                       │  Application API  (FastAPI, 127.0.0.1:8100)│
                       │  scenarios · runs · events · replay          │
                       │  read models · labelled command plane        │
                       └───────────────▲──────────────────────────────┘
                           telemetry   │   commands (all labelled)
                       ┌───────────────┴──────────────────────────────┐
                       │  Recorder / observer  (projections only)    │
                       │  durable event log · read models · gaps     │
                       └───────────────▲──────────────────────────────┘
             events                    │ events
  ┌──────────────┬──────────────┬──────┴───────┬──────────────┐
  │  robot AMR1  │  robot AMR2  │  robot AMR3  │  ...         │  separate OS
  │              │              │              │              │  processes
  │  planner     │  planner     │  planner     │              │
  │  task agent  │  task agent  │  task agent  │              │
  │  coordinator │  coordinator │  coordinator  │              │
  │  SAFETY GATE │  SAFETY GATE │  SAFETY GATE │              │
  │  authority   │  authority   │  authority   │              │
  │  journal     │  journal     │  journal     │              │
  └──────┬───────┴──────┬───────┴──────┬───────┴──────────────┘
         │              │              │
         └──────────────┴──────┬───────┘
                    direct peer messages, framed TCP, fault layer between
                              │ MotionCommand (vetoed by the safety gate)
                   ┌──────────▼─────────────────────────────────────┐
                   │  World / simulator process                    │
                   │  ground truth · integration · physics ·       │
                   │  sensor generation                           │
                   │  NO routing · NO auctions · NO grants ·       │
                   │  NO collision suppression                    │
                   └──────────────────────────────────────────────┘
```

| Component | Owns | Explicitly does **not** own |
|---|---|---|
| World / simulator | Physical ground truth, integration, environment changes, sensor generation | Routes, task winners, zone authority |
| Robot agent process | Its own planner, bids, coordinator, safety gate, authority journal | Anything about another robot except genuine peer messages |
| Peer network | Message delivery | Any decision |
| Recorder / observer | Durable events, read models | Any decision; losing it must not stop the world |
| Application API | Scenarios, run metadata, read models, replay, explicit commands | Fleet coordination of any kind |
| Frontend | Rendering, display interpolation | Robot truth, completions, grants |
| Launcher / supervisor | Process lifecycle, immutable config, diagnostics | Traffic resolution |

### The dependency graph is the enforcement

`src/niharamesh/ports.py` declares the seams as `typing.Protocol`. Concrete
modules implement them, and the import direction is one-way:

```text
agent  ──▶  ports  ◀──  simulator / transport / persistence / planner
api    ──▶  ports  ◀──  telemetry read models
```

Nothing in `transport/` or `coordination/` may import the API. Nothing in
`simulator/` may import `planning/`, `allocation/` or `coordination/`. These are
enforced by `tests/integration/test_authority_boundaries.py`, which reads the
import graph rather than trusting a docstring.

---

## 2. The authority questions, answered once

| Question | Who answers it | Where it is recorded |
|---|---|---|
| Where is this robot, really? | World process only | `World.truth()` — labelled evaluator/UI-only |
| Where does *this* robot think it is? | The robot's own localisation | `PoseEstimate` with uncertainty and observation time |
| May I enter this zone? | **The robot's own coordinator**, after the full grant set | Durable authority journal, then peers |
| Who has this task? | Each robot computes the same auction outcome locally | `TaskOwnership` with a monotonic version |
| Who holds this payload? | Physical custody, recorded separately from ownership | `PayloadCustody` |
| Is this motion safe? | The robot's own safety gate | Veto decision with a named constraint |
| Is the run a success? | The evaluator, from recorded evidence | `RunResult` with eligibility rules |

Every one of those has exactly one writer. That is what makes the system
decentralised in the meaningful sense: no component can be asked "why did you
decide that?" and point at another component.

---

## 3. Failure boundaries

### 3.1 Dashboard or API stops — robots keep deciding

**Expected:** the world continues to integrate, agents continue to plan,
coordinate, bid and stop, and continue to write their own authority journals. The
run simply stops being *observable* until the API returns.

The API is a read model plus a command endpoint. It holds no authority, so losing
it cannot remove any. The recorder's failure path is a no-op for the agents by
construction: `ObservationSink` has no reference to the world.

**Verified by:** `tests/integration/test_api_outage_continuity.py`, which runs the
world as an independent process tree (not a dashboard child) and kills the API
mid-run, then asserts the agents' journal and event log kept advancing.

> This is deliberately *not* implemented as "stop the dashboard and watch the
> robots die". That would be a parent-process accident dressed up as a
> decentralisation test.

### 3.2 The world process stops — physics cannot continue

**Expected:** agents detect stale telemetry, stop conservatively, and report
*degraded / stopped*. Robot decision authority is retained; physical integration
is not.

Software simulation cannot continue integration without its physics host. This is
reported as a world failure, distinct from a coordination failure. Restarting the
world is an operator action, and a resumed world is a **new run segment** with its
own manifest entry rather than a silent continuation.

### 3.3 One robot crashes — its zones are fenced, not freed

**Expected:** any zone the crashed robot held transitions to `FENCED`. Other robots
queue. There is no force-release.

This is the deliberate availability cost of conservative occupancy. A timed
release would be unsafe (the crashed robot is still physically there); a majority
vote would be worse (it is not physical clearance). Recovery is an explicit,
operator-visible `ZoneFenceBody` transition.

### 3.4 A partition — degraded operation, not a fleet-wide stop

**Expected:** robots that cannot confirm peer freshness stop before any stop line
they cannot verify. Robots that remain fully connected keep working.

The asymmetric-partition scenario exercises exactly this: cutting `amr-01 →
amr-02` must degrade only that pair while `amr-03` continues delivering. Freshness
expiry removes *permission to assume*, never *physical occupancy*.

### 3.5 One robot reboots — old-session messages refused

Every message carries `session_id`. A message from a superseded session is
rejected with `RejectionReason.REQUESTER_SESSION_STALE`, never merged. A corrupt or
missing authority journal enters **stopped/unknown recovery** and grants nothing.

---

## 4. Time model

Five clock domains, never mixed:

| Domain | Used by | Notes |
|---|---|---|
| `LOGICAL` | Deterministic mode | Injected; pauses freeze deadlines; acceleration never changes scenario timing |
| `SIM_SECONDS` | Run durations, metrics | Elapsed since the declared common run start |
| `MONOTONIC` | Real agent processes | Never comparable across processes without a measured offset *and* an uncertainty bound |
| `DISPLAY_UTC` | Human timestamps | Never used for expiry |
| sensor `observed_at_ns` | Simulated latency | Separate from delivery time; observation age is the difference |

`DomainEvent` carries **both** the sender's event clock and the observer's receive
clock, in named domains, precisely so no consumer can subtract across them by
accident.

Freshness uses `SharedClockEstimator.lower_bound_age_ns`, a *conservative* bound.
A negative raw age is classified `UNKNOWN`, never `FRESH`: an apparent future
timestamp means the clock relationship is not established, and guessing is worse
than admitting ignorance.

---

## 5. Determinism versus real-process execution

| | Deterministic mode | Real process mode |
|---|---|---|
| Clock | Injected logical clock | Real monotonic timers per process |
| Scheduling | Fixed-step, canonical tie-break `(time, priority, source, seq)` | Independent OS scheduling |
| Reproducibility | Repeatable canonical outcomes for the same inputs | Complete traces and accurate replay |
| Used for | Property tests, benchmark suites, regression | Wall-clock latency, CPU/memory, crash and watchdog behaviour |

These are two honest modes with the *same agent logic* where practical. A
single-process harness with isolated per-agent state and declared inboxes is
acceptable evidence for algorithm correctness, but it is **not** evidence of
process isolation — so the product also runs real separate processes, and the
architecture tests cover the real thing.

Accelerated logical timing is never reported as edge latency.

---

## 6. Data flow and durability

```text
agent  ──(its own authority journal, fsync before ack)──▶  durable promises
agent  ──(event sink)──▶  recorder ──▶  JSONL event log ──▶  SQLite read model
                                              │
                                              └──▶  gaps recorded explicitly
```

- **Authority and evaluation events are never dropped.** Only replaceable
  telemetry may be decimated, and any such drop becomes an explicit
  `RecordingGap`.
- A run with an unrecovered gap in a durable category is marked incomplete and
  excluded from claims requiring complete evidence.
- An authority transition that cannot be persisted **cannot authorise movement**.
- Safety journals are never pruned to satisfy a retention limit.
- Restarting the API rebuilds its read model by replaying stored events, without
  resetting the fleet or re-assigning tasks.

---

## 7. The operator command plane

Commands are explicitly labelled and separately recorded at four stages:

```text
requested  →  acknowledged  →  applied  →  observed
```

A sent command is not an observed stop. The UI shows all four states, and a
command that was never observed says so. No browser button is presented as a
certified physical emergency stop, because none is: physical actuation is disabled
by default and requires configured devices, a controlled test area and operator
authorisation.

---

## 8. Where to look next

| Question | Document |
|---|---|
| Why does a robot wait? | `docs/protocol/ZONE_PROTOCOL.md` |
| What do these terms mean, and in what units? | `docs/GLOSSARY.md` |
| Is that claim true? | `docs/evidence/CLAIM_EVIDENCE.md` |
| What is *not* proven? | `docs/KNOWN_LIMITATIONS.md` |
| Why was the algorithm chosen? | `docs/adr/` |
| How are the numbers produced? | `docs/BENCHMARKS.md` |
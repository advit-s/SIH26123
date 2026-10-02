# Domain glossary, units and clock model

Every term the system uses in a specific sense, and every unit. Where a term has a
tempting wrong meaning, that is stated explicitly — most of the confusion in
multi-robot systems comes from using one word for two ideas.

---

## 1. Units

| Quantity | Unit | Notes |
|---|---|---|
| Length, position, clearance | metres (`m`) | Never centimetres, never cells in an API |
| Angle, heading | radians (`rad`) | CCW from `+x`, wrapped to `(-pi, pi]` |
| Time, duration | integer **nanoseconds** (`int`) | Always paired with a `TimeDomain` |
| Simulation time | seconds (`sim_seconds`) | Elapsed since the declared common run start |
| Linear velocity | metres/second | Signed; negative is reverse |
| Angular velocity | radians/second | Pivot turns permitted (`v == 0`, `ω != 0`) |
| Acceleration | metres/second² | `accel_mps2` when speeding up |
| Deceleration | metres/second² | `decel_mps2` when slowing down; used for braking |
| Probability | `0.0 … 1.0` | Never a percentage in the API |
| Battery | fraction `0.0 … 1.0` | Always with a `BatterySource` |

Grid resolution (`map.grid_resolution_m`) is a **planner** parameter only. It never
appears in the API and never defines physical truth — the physics operates on exact
geometry.

---

## 2. Clock model

Five named domains. Values from two domains are never subtracted; the type system
requires a domain, so a bare timestamp cannot be passed around.

| Domain | Meaning | Used by | Never used for |
|---|---|---|---|
| `LOGICAL` | Injected simulation time | Deterministic harness | Wall-clock claims |
| `SIM_SECONDS` | Elapsed since run start | Metrics, timeline | Anything requiring sub-second resolution |
| `MONOTONIC` | `time.monotonic_ns()` within one process | Real agent deadlines | Cross-process comparison without a measured offset |
| `DISPLAY_UTC` | Wall-clock UTC | Human timestamps | **Any** expiry or ordering decision |
| sensor `observed_at_ns` / `delivered_at_ns` | When a measurement was taken vs received | Observation-age reasoning | Treating delivery time as measurement time |

**Freshness** is computed from `SharedClockEstimator.lower_bound_age_ns`, a
*conservative lower bound* on a message's age. If no offset estimate exists, or the
uncertainty is not small relative to the horizon, the result is `UNKNOWN` — and
`UNKNOWN` is treated exactly like `STALE` for permissions while being *reported*
distinctly.

> **A negative raw age is never "fresh".** A message timestamped in the future
> means the clock relationship is not established. Guessing "probably fine" is how
> a stale-intent bug reaches production.

**Pause** freezes logical deadlines. **Acceleration** changes how fast simulation
time passes, never when a scheduled fault fires: a fault scheduled for simulation
second 12.0 happens at simulation second 12.0 regardless of speed.

---

## 3. Authority and identity

**Robot identity** — the persistent `robot_id`: who the machine is.

**Session (boot) identity** — `session_id` + `started_at_ns`: which incarnation of
that machine is speaking. A message from a superseded session is refused, never
merged. This is the distinction that stops a rebooted robot's stale promises from
being honoured as if they were current.

**Membership** — the immutable peer set for one run epoch, with a canonical order
(ascending `robot_id`) and a reconciliation state (`FROZEN`, `RECONCILING`,
`FENCED`). While not `FROZEN`, no new authority may be exercised, so no grant can
be split across two peer sets.

**Admission** — whether an identity/session may participate. Decided by one shared
function so the launcher, the transport and the tests cannot disagree.

**Authority** — a durable, explicit right to do something: occupy a zone, hold a
payload, move under a granted permission. Authority is granted by a protocol, is
persisted before it is acknowledged, and is *never* implied by proximity, priority,
liveness or a timer.

**Authority journal** — a robot's append-only durable record of promises and
custody. A promise is written and fsynced *before* it is acknowledged. Missing or
corrupt persistence enters stopped/unknown recovery, never normal operation.

**Canonical sequential acquisition** — the acquisition protocol. Every requester
acquires **every** voter, including its own local voter, in one global order.

**Single outstanding grant** — a robot owes at most one grant **globally**, across
all zones. This is what makes the wait-for graph among healthy robots acyclic, and
therefore deadlock-free without needing deadlock detection.

**Fencing** — the only alternative to a release. When a holder fails, its zone moves
to `FENCED` and stays unavailable until a supervised transition. **There is no
force-release.**

**Compound zone** — one zone covering several connected passages, used where a
traversal needs two resources with no safe stopping point between them. Requires
disjoint protected geometry against every other exclusive zone.

**Disjoint protected geometry** — the invariant that two different zone ids cannot
authorise physically conflicting movements. Validated at map import and at
admission.

---

## 4. Freshness and evidence

**Freshness** — whether a peer message is usable *now*. Three classes:

| Class | Meaning | Permission effect |
|---|---|---|
| `FRESH` | Age lower bound within the horizon, uncertainty small | Usable |
| `STALE` | Age exceeds the horizon | Unusable |
| `UNKNOWN` | Clock relationship not established | **Treated as `STALE`** for permissions; reported distinctly |

**Validity horizon** — how long a message remains a fair claim. An intent past its
horizon is stale even if the transport delivered it reliably. *Reliable transport
does not make a message current.*

**Liveness vs usability** — a heartbeat proves a peer is alive. It is **not**
usable intent and **not** clearance. `Heartbeat` exists precisely so liveness is
never mistaken for information.

**Intent** — a *prediction* of a path and the resources it expects to need.
Receiving an intent grants nothing. A predicted path is not authorization.

**Observation** — what a robot's sensors reported, with the measurement time, the
delivery time, and the age at use. An observation can be stale, and dropping
observations is modelled.

**Evidence age** — how old the evidence behind a decision is. Every "why waiting"
explanation carries it.

**Freshness expiry removes permission to assume, never physical occupancy.** This
is the single most important sentence in the system.

---

## 5. Motion and geometry

**Pose** — `(x, y, theta)`: position and heading. A *measured* pose.

**Pose estimate** — a pose with declared uncertainty and an observation time. This
is what an agent actually has. It can be stale; `localisation_stale` says so.

**Pose / pose estimate / truth** — three different things, never conflated:
a mathematical pose · a noisy belief about it · the exact simulator state.

**Footprint** — finite robot geometry: chassis length and width, plus payload
dimensions and offset. Payload overhang is included in every collision and
clearance test.

**Clearance radius** — a conservative circumscribed radius used for planner
inflation and broad-phase rejection. Exact oriented-box tests are used wherever it
matters.

**Turning sweep** — the area covered by the corners while rotating in place. Tested
explicitly: a pivot can hit a post that both endpoint poses clear.

**Stopping distance** — `reaction + braking + margin`, where braking is `v²/(2a)`.
A *configured assumption* derived from the actuator model, not a certified bound.

**Actuator watchdog** — a stale command triggers braking at the configured
deceleration. Momentum decays over several steps; it never teleports to zero.

**Motion command** — the only thing an agent may hand to the world: linear and
angular velocity plus an expiry in a declared time domain.

**Motion state** — observed velocities, the command asked for, the actuator state
and the stop reason. A sent command is not an observed motion.

**Stop line** — a physical line a robot may not cross without the named zone's
authority. The geometric anchor for a stop-line violation, checked independently
by the evaluator.

---

## 6. Zones

**Zone** — an exclusive resource with disjoint protected geometry: geometry, entry
and exit poses, stop lines, a queue berth and a safe exit berth.

**Zone state** — `FREE` · `PROMISED` (durable grant outstanding) · `OCCUPIED`
(physically inside) · `FENCED` (holder failed; unavailable until a supervised
transition).

**Acquisition phase** — the owner's lifecycle: `INITIATED` → `ACQUIRING` →
`GRANTED` → `OCCUPYING` → `OCCUPIED` → `RELEASING` → `RELEASED`, plus
`CANCELLING` / `CANCELLED` / `REJECTED` / `FAILED`.

**Entry vs possession vs movement** — three distinct things:

| Concept | Meaning |
|---|---|
| **Entry** | the owner declares it is crossing the stop line |
| **Possession** | a peer records the zone as `OCCUPIED` |
| **Movement** | the body is actually moving; independently observed by the evaluator |

A command sent is not a body moving. The UI shows all three separately.

**Protected geometry** — the rectangle that defines exclusivity, grown by the robot
clearance radius on every side. Two robots inside the same aisle are in conflict
even when their centres are a full aisle width apart.

---

## 7. Tasks and custody

**Task** — a transport job: pickup station, drop station, release time, service
time, required capabilities, priority.

**Task state** — `AVAILABLE` → `CLAIMED` → `PICKUP_CONFIRMED` → `IN_TRANSIT` →
`DELIVERED`, plus `RECOVERY_REQUIRED` and `ABANDONED`. Transitions are defined once
in `TASK_TRANSITIONS`.

**Logical ownership** — whose plan includes the task. Versioned monotonically; a
transition carrying a stale version is refused.

**Physical custody** — who actually holds the load. Recorded **separately** from
ownership, because they diverge exactly when things go wrong.

**Recovery required** — custody is held but the owner cannot continue. The task is
**not** re-awarded as a fresh job; that would duplicate a physical load.

**Allocation round** — an immutable round identity with a snapshot digest. Rounds
are serialised so a robot cannot win two auctions against the same availability.

**Bid set digest** — a hash over the sorted bid set. Every robot computes the award
independently and must reach the same digest. A disagreement is an explicit
inconsistency event, not something to paper over.

**Explicit no-bid** — a recorded "I cannot serve this". Silence is never an
acceptable substitute.

**Idempotency** — a duplicated message must not create a second payload, a second
pickup, a second delivery reward or a second benchmark completion credit.

---

## 8. Experiments and measurement

**Configured assumption** — a value we chose. Robot size, speed limit, sensor noise,
battery model, timing budget. Labelled as simulation configuration wherever shown.

**Implemented and verified** — code exists, checks were executed, evidence path
recorded.

**Measured outcome** — a number from a specific run artefact with a manifest, an
environment and a trace.

These three are never mixed. A configured 0.4 m/s speed limit is not a measured
throughput.

**Makespan** — elapsed time from the declared common run start to delivery of every
required task in a completed workload. `None` unless the workload actually
completed; a deadlocked run never gets an imputed makespan.

**Paired makespan reduction** —
`100 × (baseline − candidate) / baseline`, computed **only** on eligible completed
pairs, with excluded pairs and failure rates displayed beside any aggregate.

**Eligibility** — a run qualifies for a successful-completion comparison only if it
succeeded, had zero collisions, completed every required task, produced a makespan,
and has no unrecovered gap in a durable evidence category.

**Excluded pair** — a baseline/candidate pair that cannot be compared. Reported,
never silently dropped.

**Unsafe run** — one where an independent evaluator observed a collision, a
stop-line violation, conflicting authority, or duplicate custody. Presented as
unsafe; never given a performance badge because its duration happened to be short.

**Recording gap** — an explicit hole in durable evidence. Never a silent drop.

**Deterministic repeatability** — the same inputs and seed produce the same
canonical event/outcome hash.

**Replay equivalence** — rebuilding state at a timestamp from recorded events
matches the recorded state at that timestamp.

**Evaluator truth** — exact simulator state, visible in the UI overlay and
explicitly labelled as evaluator knowledge. It is never available to an agent.

---

## 9. Vocabulary to avoid

| Do not say | Say instead |
|---|---|
| "the robot is at X" (from a belief) | "the robot's pose estimate is X, age A s, uncertainty U" |
| "the robot sent a stop" | "a stop was **requested** at T; observed stopped at T+Δ" |
| "the collision count is 0, therefore safe" | "no collision was **observed** in this run" |
| "20 % faster" | "the measured paired reduction on N eligible pairs was X% (CI …)" |
| "the leader decided" | "robot R's own coordinator decided, after collecting grants from every voter" |
| "the system is collision-free" | "no collision was observed under this geometry and timing" |
| "the aisle is empty" (after a timeout) | "the aisle is **still assumed occupied**; no reconciled release was received" |
| "AI powered" | "onboard A* search, constrained velocity profiles, intent prediction, multi-agent negotiation" |

---

## 10. Source of record

Types: `src/niharamesh/domain/**`. Generated schemas:
`src/niharamesh/contracts/schemas/**`. Protocol states:
`docs/protocol/ZONE_PROTOCOL.md`. Decisions and their revisiting conditions:
`docs/adr/`.
# CONTINUE

## Where this is right now

`feat/niharamesh-platform`. Head is `eee4502` ("Close the Gate B gaps: task feed,
peer publication, deadlines, real safety"); Milestone B is `6b21f40`, Milestone A is
`b492bfd`. Working tree clean apart from three deliberately untracked prompt files:
`NiharaMesh_OpenCode_Master_Build_Prompt.md`,
`docs/superpowers/plans/2026-10-02-opencode-continuation-prompt.md` and
`docs/superpowers/plans/2026-10-02-opencode-next-after-milestone-b.md`.

Verified in this checkout after the three gates of 2026-10-03:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --timeout=900
# 570 passed, 1 skipped in 341.50s
.\.venv\Scripts\python.exe -m ruff check src tests scripts --no-cache   # clean
.\.venv\Scripts\python.exe -m mypy --cache-dir var/mypy-next              # 71 modules, clean
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/network
# 6 passed in 9.67s
```

If any of those disagree with reality, believe the command, not this file.

**The one skip is not a hidden failure.** It is
`test_two_robots_never_occupy_the_same_space`, which skips when the collision it
documents no longer reproduces. The defect, its measurement and its root cause are
preserved in that file's docstring.

**The single most important thing this file has to say:** Milestones C–G are
untouched, and **no authored scenario has yet reached `success`**. The ≥20 %
makespan target remains **unmeasured**.

---

## What now works, measured

`three-way-junction`, 250 s budget, 89 s wall clock:

```text
outcome incomplete   dur 250.0
   amr-01 done ['t-junction-0']   stops {'scheduled_stop': 3059, 'obstacle_in_path': 37}
   amr-02 done []   zones ['zn-junction']   stops {'zone_authority_missing': 4392}
   amr-03 done []   zones ['zn-junction']   stops {'zone_authority_missing': 620,
                                                    'obstacle_in_path': 3689}
   amr-01 waiting  task delivered  completion_credited True
events: [('zone_occupied','zn-junction'), ('zone_occupied','zn-junction'),
         ('task_completed','t-junction-0')]
```

One robot completes a real pickup-and-delivery with exactly one completion credit,
declared from real custody events. Two robots enter and clear the junction through
the canonical protocol. That is **implemented and verified**; the run is still
`incomplete` because the other two tasks are not finished in the budget, which is a
throughput problem, not a safety one.

---

## Findings 20-27

### 20 — Two tasks that had no destination (Milestone B)

`mark_entered`/`release` existed but were never called, so no robot ever entered or
left a zone; amr-02 held `zn-junction` for the entire run and amr-03 starved behind
it. Entry is now declared when the robot's **own body** is inside the protected
geometry it holds, and release only when that body has **left** it. Neither is
timer-driven.

### 21 — A refusal became an arrival

`_at_station` asked "is *a* station nearby" and the answer was used with the *goal*
station. amr-01 picked up at `stn-pick-a`, was still standing at `stn-pick-a`, that
counted as an arrival, it asked the world to service `stn-drop-b` 22 m away, the
world refused, and it sat there for the rest of the run with a 233-waypoint plan it
never followed. Arrival is now judged against the station the robot is actually
going to.

### 22 — An edge-triggered event read as a level

`_RobotActuator.service_running` used `World.service_complete`, which is cleared at
the start of every step. A caller polling once per control period reads "not
servicing" from the tick *after* the visit ended. `World.is_servicing` is the level
query; `service_complete` stays the event.

### 23 — Two records of one task lifecycle

The runtime kept its own `TaskState` while the custody ledger kept an authoritative
one. They disagreed, and every delivery failed as `ILLEGAL_TASK_TRANSITION`: the
ledger requires `PICKUP_CONFIRMED -> IN_TRANSIT -> DELIVERED` and the runtime went
straight from pickup to delivery. Departure is now an explicit declared step, and
`progress.state` is **derived** from the ledger.

### 24 — A delivered task was still a destination

After delivering, the robot was still standing at the drop station, so it counted as
an arrival and serviced the same delivery for the rest of the run. A `DELIVERED` or
`ABANDONED` task now has no destination.

### 25 — A finished transaction still counted as outstanding

`_acquiring` matched on zone id alone. Once a release settled, the finished
acquisition still counted as live, so the robot never asked again and queued for a
zone it had itself released. `_acquiring` now also requires a non-terminal phase.

### 26 — A promise kept after its reason had gone (found by running it)

amr-01 delivered its task, had no destination, and went on holding a `PROMISED` grant
at its voter. amr-02's canonical walk was refused by that promise for the rest of
the run. A robot now cancels a transaction it no longer needs — but never one it is
physically inside, and never one it holds authority for.

That second guard was **my own bug, introduced by the first fix**:
`_next_zone_ahead` deliberately skips zones the robot already holds, so "nothing
ahead needs a zone" is also true of a robot that has just been granted the zone it
is driving into. Without the guard it cancelled its own grant on the next tick,
every time, and the junction never cleared once.

### 27 — A rejected attempt never withdrew the promises it had collected

**SUPERSEDED 2026-10-03. The defect described here does not exist.**

> `ZoneRequester.tick` emitted cancellation only when `durably_non_executable`. The
> protocol deliberately retries with a **fresh** `request_version` (see `retry_due`),
> so a voter still holding a promise from the failed attempt refuses the retry with
> `ZONE_PROMISED` — same zone, same robot. The promise can never match the new
> version, so the retry can never succeed: a livelock, not a leak. A rejected attempt
> now cancels the promises it collected, which is safe precisely because it never
> reached `GRANTED`, so nobody could have entered on it.

The independent protocol reviewer fuzzed the real `ZoneRequester` and `ZoneVoter`
(120 seeds x 120 steps, adversarial drop/duplicate/delay) and measured **6 034
observations with a non-empty `cancel_targets`, of which none had phase `REJECTED`**.
The added condition held 14 095 times and **every single time with an empty target
set**. `REJECTED` is only reachable with nothing to reconcile, so the branch could
never emit a message the pre-existing durable branch would not.

The branch is **reverted**. What actually got fixed in that area is a different,
real defect the review found: cancellation was sent once and never re-sent, which
wedged the zone permanently for a robot that lost one frame. See
`docs/KNOWN_LIMITATIONS.md` item 12 and the Gate 1 section of `docs/STATUS.md`.

> **This was the one change in `src/niharamesh/coordination/` outside the
> integration owner's own files, and it is now reviewed. It removed nothing real
> and added nothing real, which is exactly why the review was worth running.**

---

## Independent review of Milestone A — findings and disposition

A read-only reviewer audited `b492bfd` and reproduced its central finding against the
real agent, gate, kinematics and map. Full detail is in the commit message and
`docs/STATUS.md`. Disposition:

| Finding | Disposition |
|---|---|
| **B1** — the swept-volume witness was not a bound; a real command was permitted that drove the chassis **44 mm into a shelf** | **Fixed.** `swept_body_bound` in `domain/geometry.py` now decomposes translation (along the heading), rotation (isotropic corner arc) and the centre's own arc deviation, and counts the post-expiry spin-down. Covered by `tests/integration/test_swept_volume_bound.py`, which **integrates the physics** rather than comparing boxes — the gap that let B1 through |
| **B2** — a late/duplicate grant moved `GRANTED` to `CANCELLING` and freed the aisle with no reconciled release | **Fixed** in the runtime: `_local_occupancy` records physical occupancy independently of the transaction and `authority_zone()` falls back to it, so a cancellation cannot make a robot abandon an aisle its body is in |
| **B3** — the runtime never entered or left the occupancy state machine | **Fixed** — findings 20 and 26 |
| **N1** — a backwards clock was clamped to an age of zero and reported "live" | **Fixed.** A negative gap is now a clock fault that fails closed, not a healthy loop |
| **N3** — the zone witness ignored its own command and was conservative by accident of the shipped numbers | **Fixed.** The witness is built from the command, through the same shared formula as the gate |
| **N4** — the admission callback could livelock a robot with too little clearance | **Fixed** by refusing nothing on current clearance: that is a per-tick question the gate already answers |
| **N5** — the harness publishes no `peer_state`, so `may_enter`'s suspend guard is inert in every harness run | **Open.** See below |
| **Drift 2/3** — `App.tsx` read a `RunManifest` field that did not exist, and neither actuation switch was in the manifest | **Fixed.** Both switches are now manifest fields, regenerated into the contracts |

Test gaps the review named are also closed: combined translate-and-rotate coverage
over a parameter grid, integrated-physics verification, and a `CANCELLING` case.

---

## Next command

### Done on 2026-10-03 (commit `eee4502`)

1. **Protocol review of `coordination/requester.py` finding 27.** Completed. The
   change was **dead code** and is reverted; five real blocking defects the review
   found alongside it are fixed. See the Gate 1 section of `docs/STATUS.md`.
2. **Feed the scenario task feed into `LocalAuction`.** Completed for
   `dynamic-arrivals`. Round identity is a pure function of the clock; every member
   reports on every released task; an award is announced only once every member has
   reported.
3. **N5: the harness now publishes `peer_state` and `peer_intent`.** Closed.
   `may_enter`'s suspend guard is exercised, and a cached `FRESH` verdict expires
   with no new incoming message.
4. **`asymmetric-partition` now injects a real partition** into harness routing,
   through the same `FaultLayer` the process transport uses.
5. **The harness no longer quantises `max_sim_time_s`.** Discrete fixed-step
   semantics, declared and tested at the boundaries.

### Still to do

1. **Throughput, root cause first.** Two of `three-way-junction`'s three tasks and
   most of `dynamic-arrivals`' four do not finish inside their budgets. Measured
   causes so far: a mutual standoff in a 1.4 m aisle with no passing place
   (`amr-01`/`amr-02` head-on in the bottom row), and long stretches stopped under
   `obstacle_in_path`. **Whether the clearance governor is too timid or the geometry
   is genuinely too tight is still a hypothesis.** Measure before changing either,
   and do not enlarge a deadline to hide it.
2. **`infeasible-layout` must reach `expected_safe_stop`** with evidence, not merely
   with its clock expired. The planner loop that made it unrunnable (an exhaustive
   A* re-run every physics tick) is not yet fixed — see the next section.
3. **Measure `asymmetric-partition`'s actual behaviour** under its declared cut, not
   just that the event fired.
4. **Milestones C–G, all untouched:** no API server, no replay reducer, no
   `evaluation/**`, no `scenarios/suites/{smoke,main}.json`, no CLI
   `run`/`benchmark`/`serve`/`agent`/`replay`, no cockpit integration against a real
   backend, no Docker/ROS 2/edge profiles. **The 20 % makespan target remains
   unmeasured.**

### Known performance defect, not yet fixed

`infeasible-layout` re-runs a full A* search **every physics tick** once its goal is
unreachable. Measured: a single unreachable plan costs **7.07 s** and expands
119 136 cells; the inner loop repeats it at 20 Hz for every robot with no task. A
30 s budget does not finish in 300 s of wall clock.

The cause is in `RobotAgent._decide`: the unreachable verdict is returned *before*
`self._goal` is set, so `self._goal != goal` stays true and the plan is retried on
every tick. The fix is to latch the verdict with a declared invalidation condition
(new goal, custody change, map version change) — **not** to reduce the planner's
expansion budget, which would weaken the planner to hide the cost.

---

## Ownership

`src/niharamesh/coordination/**` and `src/niharamesh/transport/**` are reviewed
packages: one implementer, one independent reviewer, never the same agent. Changes to
them are fixed here from a review finding and re-reviewed on the next pass.
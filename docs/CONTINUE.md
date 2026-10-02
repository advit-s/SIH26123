# CONTINUE

## Where this is right now

`feat/niharamesh-platform`. Head is the Milestone B commit below; Milestone A is
`b492bfd`. Working tree clean apart from two deliberately untracked files:
`NiharaMesh_OpenCode_Master_Build_Prompt.md` and
`docs/superpowers/plans/2026-10-02-opencode-continuation-prompt.md`.

Verified in this checkout after Milestone B:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider    # 526 passed
.\.venv\Scripts\python.exe -m ruff check src tests scripts --no-cache   # clean
.\.venv\Scripts\python.exe -m mypy --cache-dir var/mypy-c     # 71 modules, clean
pnpm --filter @niharamesh/web exec tsc --noEmit                # exit 0
node packages/contracts/generate.mjs                          # byte-identical on repeat
```

If any of those disagree with reality, believe the command, not this file.

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

`ZoneRequester.tick` emitted cancellation only when `durably_non_executable`. The
protocol deliberately retries with a **fresh** `request_version` (see `retry_due`),
so a voter still holding a promise from the failed attempt refuses the retry with
`ZONE_PROMISED` — same zone, same robot. The promise can never match the new
version, so the retry can never succeed: a livelock, not a leak. A rejected attempt
now cancels the promises it collected, which is safe precisely because it never
reached `GRANTED`, so nobody could have entered on it.

> **This is the one change in `src/niharamesh/coordination/`, which that package's
> reviewer treats as read-only.** It is surgical and it is covered by the existing
> 89 protocol and property tests, but it needs an independent protocol review before
> it is relied on. It is the first item on the review list.

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

1. **Protocol review of `coordination/requester.py` line 417** (finding 27), the only
   un-reviewed change made outside the integration owner's own files.
2. **Feed the scenario task feed into `LocalAuction`.** `dynamic-arrivals` and
   `infeasible-layout` still report "no task is currently assigned to this robot";
   both need real awards, and `infeasible-layout` then needs the evidence-backed
   `expected_safe_stop` classification that Gate B requires.
3. **Throughput.** Two of three tasks in `three-way-junction` are unfinished at 250 s.
   `amr-03` spends ~3700 ticks under `obstacle_in_path` while creeping out of the
   junction under the clearance governor. Either the governor is too timid or the
   junction is too tight for a 0.32 m turning radius — measure before changing
   either, and do not enlarge the deadline to hide it.
4. **N5: make the harness publish `peer_state` and `peer_intent`.** Until then
   `may_enter` never suspends in deterministic mode and every harness test asserts a
   weaker property than process mode gives. The three-real-process test does exercise
   the real path.
5. `asymmetric-partition` does not yet inject a partition into transport.
6. The harness quantises `max_sim_time_s` to whole seconds, so a 0.05 s budget runs a
   full second. This is why no short scenario probe works.

Milestones C through G are untouched: no API server, no replay reducer, no
evaluation module, no benchmark suites, no ROS 2, no Docker. The 20 % makespan
target remains **unmeasured**.
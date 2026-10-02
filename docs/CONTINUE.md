# CONTINUE

## Where this is right now

`feat/niharamesh-platform`, head `b492bfd` "Repair the simulated-motion and safety
boundary (Milestone A)". Working tree clean apart from two deliberately
untracked files: `NiharaMesh_OpenCode_Master_Build_Prompt.md` and
`docs/superpowers/plans/2026-10-02-opencode-continuation-prompt.md`.

**Milestone A is done and committed.** Eleven defects, listed with root causes in
`docs/STATUS.md` and in the commit message itself. The approved contract is
`docs/superpowers/plans/milestone-a-contract.md`.

Verified in this checkout at `b492bfd`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider    # 512 passed, exit 0
.\.venv\Scripts\python.exe -m ruff check src tests scripts --no-cache   # clean
.\.venv\Scripts\python.exe -m mypy --cache-dir var/mypy-milestone-a     # 71 modules, clean
pnpm --filter @niharamesh/web exec tsc --noEmit              # exit 0
pnpm --filter @niharamesh/web test                           # 63 passed
pnpm --filter @niharamesh/web build                          # succeeded
```

If any of those disagree with reality, believe the command, not this file.

---

## Finding 14 — every tick was vetoed as `actuator_fault`

**Symptom.** All three named scenarios ran to their deadline with zero completed
tasks and 1200/1200 vetoed ticks each:

```text
three-way-junction -> incomplete duration 60.0
   amr-01 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
```

**Root cause.** `SimulationConfig.physical_actuation_enabled` answered two
different questions at once. `World.apply_command` read it as "is the actuator
chain live", refused every command in the default configuration, and
`Observation.motion.actuation_enabled` therefore reported a dead chain, which the
safety gate's very first check turned into `ACTUATOR_FAULT`. Nothing could start.

**Lesson worth keeping.** The previous advice to drain `requester.outbox` was
wrong for this checkout, and the relay was *not* the blocker. One flag silently
answering two questions was. The failing signal was uniform and specific
(`actuation_disabled` on every tick), which is what should have been read as a
configuration mistake rather than a coordination one.

---

## Finding 15 — an authority bypass through a zone on the plan

**Symptom.** `_to_command` discarded `_decide`'s `SafetyDecision(False, ...)` and
called `_pursue` regardless, so a robot queued for a zone it did not hold emitted
a full-speed pursuit command. The gate did not catch it, because
`GateContext.inside_zone` was filled from `_zone_in_progress` — the next zone
*anywhere on the remaining plan* — which satisfied the blanket
`if inside_zone is None and zone_authority is None: veto` rule from ten metres
away.

Reproduced directly against the unmodified gate:

```text
TODAY open-space motion (no authority, sweeping clear of every zone):
    SafetyDecision(permitted=False, reason=zone_authority_missing, constraint='no_zone_authority')
TODAY a robot naming a zone ten metres away on its plan:
    SafetyDecision(permitted=True, reason=none, constraint='')
```

**Lesson worth keeping.** The two halves were individually defensible and jointly
a bypass. One field meant "the zone I intend to need", the other asked "do I have
authority for anything at all". Splitting them into four separately named facts
(`occupied_zone`, `entry_permission`, `zone_authority`, `swept_body`) removed the
ambiguity rather than patching either half.

---

## Finding 16 — a false measurement that refused honestly

**Symptom.** `_box_gap` accumulated its per-axis separating-axis projections with
`min` where the theorem requires `max`. For any body not facing roughly east, one
axis produced a large negative value, the minimum went negative, and
`max(0.0, ...)` reported a genuine 0.30 m clearance as `0.0`. The gate then vetoed
with `obstacle_0.000m<0.320m` and a robot standing in a clear aisle could not
move at all.

**Lesson worth keeping.** The gate errs towards refusing, so this looked like
conservative behaviour rather than a bug. It is not: it told an operator an
obstacle existed where none did, and it made the whole laboratory unable to
demonstrate anything. A wrong measurement is a defect in the safe direction too.

---

## Finding 17 — the lateral shelf, and a robot that could not turn away

**Symptom.** Two of three robots in `headon-aisle` were frozen on
`obstacle_in_path` for 2900 of 3000 ticks. Two separate causes:

1. The stopping budget is **longitudinal** (`v·t_r + v²/2a + margin`) but was
   compared against the nearest obstacle in **any** direction. A shelf 0.26 m away
   *beside* a robot driving parallel to it is not a stopping hazard.
2. A veto zeroed `angular_radps` as well as `linear_mps`. A robot pointed at a
   shelf it needed to reverse away from could not translate, could not steer, and
   therefore stayed pointed at the shelf for the rest of the run.

**Fix.** Exact geometric tests — the body, and the body carried *forward* by its
own stopping reach and widened by its corner sweep, must not overlap static
geometry. The pivot is offered to the gate as its own command and gets its own
decision, and the corner-sweep term is what makes letting it steer safe.

**Lesson worth keeping.** "Refuse" is not "stop". Braking is longitudinal; a
command with zero requested velocity is not instantaneous rest, and a veto that
removes the ability to *steer* can be a livelock rather than a brake.

---

## Finding 18 — invariant 6, enforced by the protocol and violated by the caller

**Symptom.** `cycle-with-holding` crashed outright:

```text
RuntimeError: robot amr-02 already holds an outstanding transaction for
'zn-cycle-bottom' (granted); invariant 6 permits one outstanding grant globally
```

**Root cause.** With authority held for one zone and a *different* zone next on
the plan, `_decide` called `begin_acquire` anyway. The requester was correct to
raise; the runtime had to respect the rule rather than discover it.

**Lesson worth keeping.** A protocol that raises is doing its job. The caller is
the defect.

---

## Finding 19 — world-frame bearings read as body-frame (found while fixing 17)

`_forward_clearance_m` filtered `abs(ray.bearing_rad) <= pi/2`, which measures
the wedge around the world `+x` axis. `RangeRay.bearing_rad` is **world**-frame.
Any robot not facing east therefore reported *no forward evidence at all* and
silently fell back on the exact map test alone — which is how the measured half
of the obstacle check disappeared for two of three robots, without any error.

Introduced by the fix for finding 17 and caught by reading `sensors.py` rather
than by a test. Worth remembering: a change that makes a safety check *absent*
produces no symptom of its own.

---

## Two latent test defects found by running the suite

Neither is a product defect; both would have hidden a real one.

- `tests/property/test_allocation_properties.py::test_total_cost_is_monotonic_in_travel_time_s`
  asserted that quantising two totals can never move their difference by more than
  `2 x step`. Hypothesis found two counterexamples. The correct bound is
  `3 x max(step, ulp)`: each total is rounded to a grid of spacing
  `max(step, ulp)` (rounding 2.1e9 to seven decimals asks for a resolution the
  double does not have), each rounding contributes up to half of that, and
  computing the difference contributes one more.
- `tests/unit/test_world.py` built its config with `physical_actuation_enabled=True`
  purely so robots would move, which meant it never exercised the shipped default
  and quietly opted into a hardware boundary. Removed.

---

## Next command

Milestone B — complete task and zone lifecycles. Milestone A made motion honest;
nothing completes a task yet. In rough dependency order:

1. **`RobotAgent` declares zone entry and release.** Nothing ever enters a zone,
   so nothing is ever released: in `three-way-junction` amr-02 holds `zn-junction`
   for the whole run and amr-03 starves behind it for 3000 ticks. Needs
   `coordinator.mark_entered()` when the robot's own body crosses into the zone it
   holds, and `coordinator.release()` only when the body has actually cleared —
   asserted on the robot's own geometry, never on a timer.
2. **Station service.** `World.begin_service` / `service_complete` exist and are
   unwired. Neither a timer started far from a station nor proximity alone proves a
   delivery; the world reports the physical fact and the agent/custody system owns
   task authority.
3. **Feed the scenario task feed into `LocalAuction`.** `dynamic-arrivals` has all
   three robots reporting "no reachable task remains for this robot", and
   `infeasible-layout` reports the same. Bind claims and capacity to actual awards.
   No harness-side allocator.
4. **Custody and exactly-once completion credit.** Derive `tasks_completed` from
   real task events. Never populate it to satisfy the harness outcome check.
5. **Honest `_classify`.** Inspect it rather than trusting its name. A known
   collision must never be reported as success or as an expected safe stop. Gate B
   requires `three-way-junction` to complete its tasks and `infeasible-layout` to
   produce an evidence-backed `expected_safe_stop` — without altering maps,
   deleting tasks, changing expected outcomes or enlarging time budgets.
6. **Make every advertised fault affect its intended subsystem.** Logging
   `fault_injected` without applying the fault is not implementation.

Also still open from earlier milestones: the harness quantises `max_sim_time_s` to
whole seconds (`while clock.now_s() < deadline` over an inner 20-step block), so a
1-second budget runs a full second and a 0.05-second budget does the same.
`asymmetric-partition` does not yet inject a partition into transport.
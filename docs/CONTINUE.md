# Continuation state

Dated: 2026-10-02 · Branch `feat/niharamesh-platform`

This file answers "where was I, what is the exact next command, and what is still
broken" for a fresh context. It is updated at every milestone and is **not** a plan
— read `docs/STATUS.md` for what is verified and `docs/KNOWN_LIMITATIONS.md` for
what is honestly unproven.

---

## Where the build stands

Phases 0–1 are complete and committed. Phases 2–4 were delegated to parallel
subagents with non-overlapping file ownership and are landing. The integration
layer (CLI, run orchestration, docs, tooling) is being built by the integration
owner.

### Committed

| Commit | Contents |
|---|---|
| `f9cb92a` | Repo bootstrap, `opencode.jsonc` (v2 schema), 10 invariants, domain contracts, 55 JSON Schemas |
| `816ccc5` | Scenario library (7 named scenarios), validation, path-safe IO, clocks, ports, CLI, research register |

### In flight (uncommitted, owned by subagents — do not edit)

| Area | Files | Owner |
|---|---|---|
| simulator + collision | `src/niharamesh/simulator/**`, `src/niharamesh/safety/**`, `tests/unit/test_{collision,oracle_agreement,kinematics,sensors,world}.py`, `tests/property/test_motion_properties.py` | simulation workstream |
| coordination | `src/niharamesh/coordination/**`, `docs/protocol/**`, `docs/adr/000{2,3}-*`, `tests/protocol/**` | coordination workstream |
| planning + allocation | `src/niharamesh/planning/**`, `src/niharamesh/allocation/**`, `tests/unit/test_{planner,path_smoothing,blocked_reroute,auction,custody,temporal_planner}.py`, `tests/property/test_allocation_properties.py` | planning workstream |
| transport + persistence | `src/niharamesh/transport/**`, `src/niharamesh/persistence/**`, `src/niharamesh/telemetry/**`, `tests/unit/test_{framing,codec,fault_layer,journal,eventstore}.py`, `tests/network/**` | transport workstream |
| web cockpit | `apps/web/**`, `e2e/**`, `playwright.config.ts`, `packages/contracts/generated/**` | frontend workstream |

**Do not edit files in these areas while their subagent is running.** Doing so
causes lost work — this happened once already when `safety/collision.py` was
overwritten mid-review.

### Integration owner's remaining work

1. `src/niharamesh/agent/**` — the per-robot runtime tying planner + allocator +
   coordinator + safety gate together. **Blocked** until the four workstreams land.
2. `src/niharamesh/api/**` — FastAPI app, WebSocket stream, command plane.
   Partially specified; the frontend is coding against the agreed contract.
3. `src/niharamesh/evaluation/**` — metrics, eligibility, gaps, paired analysis.
4. `src/niharamesh/replay/**` — reducer, version handling.
5. `src/niharamesh/cli/{run,agent,serve,bench,replay}.py` — the remaining CLI
   commands. `doctor` and `scenarios` already work; the others register only once
   their runtime module exists, and `nihara --help` says which are absent.
6. `scenarios/suites/{smoke,main}.json` — benchmark suite definitions.
7. `deployment/`, `ros2/`, `.github/workflows/`.
8. Remaining docs: `ARCHITECTURE.md`, `GLOSSARY.md`, `BENCHMARKS.md`,
   `SCENARIOS.md`, `FAULTS.md`, `REPLAY.md`, `API.md`, `EDGE.md`, `SECURITY.md`,
   `SKILLS.md`, `DEMO.md`, `THIRD_PARTY.md`, `DECISIONS.md`.

---

## Exact commands

```bash
# environment (verified 2026-10-02)
uv sync --extra dev            # Python env, Python 3.12.14
pnpm install                   # JS workspace
pnpm --filter @niharamesh/contracts generate

# quality gates
uv run ruff check src tests scripts
uv run mypy
pnpm --filter @niharamesh/web exec tsc --noEmit

# tests
uv run pytest tests/unit -q
uv run pytest tests/protocol -q
uv run pytest tests/property -q
uv run pytest tests/integration -q
uv run pytest tests/network -q
pnpm test:e2e

# scenarios
uv run nihara scenarios export
uv run nihara scenarios validate --structural-only
uv run nihara doctor

# run + evidence
uv run nihara run --scenario scenarios/three-way-junction.r1.json --mode deterministic
uv run nihara benchmark --suite scenarios/suites/smoke.json --output var/benchmarks/smoke
```

Full release path: `pnpm verify`.

---

## Environment (recorded, do not re-derive)

| Component | Version |
|---|---|
| OS | Windows 11 win32, PowerShell 5.1 |
| Git | 2.53.0.windows.2, identity present |
| Node.js | v24.13.0 |
| pnpm | 11.22.0 |
| uv | 0.12.7 |
| CPython (uv-managed) | 3.12.14 |
| OpenCode | **2.0.22 — v2 schema** (`agents`, `permissions`, `mode: subagent`) |
| Docker | **absent** |
| Skills discovery | `.agents/skills/` (project compatibility path) and `.opencode/skills/` |

---

## Unresolved failures and decisions taken during debugging

These are recorded so the next context does not re-derive them.

### 1. Kinematics: rectangle-rule under-travel during braking (FIXED)

`step()` advanced position by `next_v * dt` while `distance_m` reported the
trapezoid `0.5*(v+next_v)*dt`. Over a full stop that made the robot travel ~10 %
less than the analytic `v²/(2a)` — enough to fail any comparison against the
stopping-distance argument the safety gate relies on. **Fix:** integrate position
with the same trapezoid, so reported and travelled distances agree. Now
0.100000 m measured vs 0.100000 m analytic.

### 2. Kinematics: test harness reset momentum every step (FIXED)

`tests/unit/test_kinematics.py::_run` fed back `x, y, theta` but not `v, omega`,
so velocity never accumulated and every multi-step test was meaningless. The
assertion "velocity reaches the max" failed at 0.025 m/s for exactly this reason.

### 3. Kinematics test asserted degrees where the API is rad/s (FIXED)

`test_pivot_turn_keeps_the_position_fixed` compared against
`math.radians(0.8) * 20 * dt` — treating a rad/s command as degrees. Replaced with
the integral of the recorded rate plus a no-ramp upper bound, which also accounts
for the angular acceleration ramp.

### 4. Collision: residual inflation created false positives (FIXED)

`swept_body_overlap` substepped by translation fraction and, on exceeding
`max_substeps`, inflated both bodies by half the residual bound. That is
conservative in the safety direction but **manufactures penetration out of real
clearance** — it disagreed with the independent oracle on 3 of 300 randomised
cases and on the thin-body adversarial set, all in the false-positive direction.

Root cause: translation never needed substepping at all. The Minkowski sum of a
convex body with a translation segment *is* the convex hull of its endpoint
corners, so one separating-axis test decides translation **exactly**.

**Fix:** substeps are rotation-driven only; each substep tests
`_swept_translation_hits` (exact hull) plus the substep midpoint inflated by the
exact arc sagitta `r(1 − cos(φ/2))`. Exceeding `max_substeps` now **raises**
instead of silently coarsening. `MAX_RUNTIME_SUBSTEPS` raised 64 → 128 so the
documented worst case (a quarter turn) resolves at full resolution.

### 5. Collision: touching exactly was reported as clear (FIXED)

`sat_overlap` requires strictly positive penetration, so two 1 m boxes at exactly
1 m apart — sharing a face — were reported as clear by the runtime path while the
oracle called it a collision. Added `_runtime_hits_box`, which consults the
closed-set `_runtime_touching` as well. Zero clearance is not safe clearance in
this system.

### 6. Oracle agreement tests asserted a property the new algorithm invalidates (REWRITTEN)

Two tests asserted "the oracle's residual is strictly below the runtime's" and
"the oracle samples ≥5× finer". Both encoded the *old* design assumption that the
runtime checker was the coarser of the two. With translation exact, the runtime
residual is *smaller* — which is the desired outcome. Replaced with tests that
assert what actually matters now:
- the runtime residual is **independent of travel** (translation contributes zero),
- the runtime residual is **bounded by the documented sagitta**,
- the oracle's residual stays **positive**, so it can still falsify the runtime.

### 7. Scenario zone/berth geometry was wrong (FIXED by the validator)

The first authored zones placed queue berths on the aisle centre line at a
cross-aisle `y`, which fell **inside** the zone's inflated protected area — a
berth inside a zone means a robot stopping there still holds another robot's
resource. `validate_berth_separation` caught it. Fixed by offsetting interior-aisle
berths ±1.5 m laterally into the cross aisle, and by re-authoring zones per shelf
row (`row_zone`) so consecutive zones along an aisle are always separated by a
whole cross aisle — which is what makes "one outstanding grant per robot"
practical without deadlock.

### 8. Scenario path resolution double-joined (FIXED)

`resolve_scenario_path(base, "scenarios/x.json")` produced `scenarios/scenarios/…`.
Now tries CWD-relative and root-relative, accepting whichever lands inside the root,
and still refuses any escape.

---

## Invariants that must survive integration

1. Simulator never plans/awards/grants; API never coordinates; browser never
   advances truth.
2. No agent function returns another agent's truth or the evaluator's verdict.
3. Occupancy is never cleared by a timer; there is no force-release.
4. Cancellation is durable at the owner before peer reconciliation.
5. One outstanding grant per robot; canonical order includes the requester's own
   voter.
6. Every actuator command passes the safety gate.
7. Clock domains never mix.
8. Scenario snapshot immutable per run.
9. Missing metric = `unavailable`, never `0`.
10. Failure states are visible, never green.

---

## Honest gaps carried forward

- **20 % target: unmeasured.** Report as achieved or not achieved from a paired run
  set. Never estimated.
- Docker, ROS 2 and ARM edge hardware are **unavailable here**; those paths are
  authored and reviewed but unexecuted, and must be labelled that way.
- Protocol interleaving verification is **bounded**, not unbounded.
- No learned component is shipped; the AI is search + constrained decisions +
  intent prediction + negotiation, described precisely.

See `docs/KNOWN_LIMITATIONS.md` for the full list.
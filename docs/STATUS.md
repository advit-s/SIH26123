# STATUS

Updated: 2026-10-02 · Branch `feat/niharamesh-platform`

**VERIFIED** = code exists, the named check was executed, output recorded.
**IMPLEMENTED** = code exists, not yet verified end to end.
**NOT STARTED** · **BLOCKED** · **EXTERNAL LIMIT** = needs unavailable hardware/software.

## Environment (recorded, verified)

| Component | Version |
|---|---|
| OS | Windows 11 win32, PowerShell 5.1 |
| Git | 2.53.0.windows.2, identity present |
| Node.js / pnpm / npm | v24.13.0 / 11.22.0 / 11.6.2 |
| uv / CPython (managed) | 0.12.7 / 3.12.14 |
| OpenCode | **2.0.22** — v2 schema (`agents`, `permissions`, `mode: subagent`) |
| Docker | **absent** |

## Quality gates — all green

```
uv run ruff check src tests scripts   → All checks passed!
uv run mypy                           → Success: no issues found in 71 source files
uv run pytest tests/unit tests/protocol tests/property tests/network -q
                                      → 424 passed
pnpm --filter @niharamesh/web exec tsc --noEmit      -> exit 0 (strict)
pnpm --filter @niharamesh/web test                   -> 63 passed (7 files)
pnpm --filter @niharamesh/web build                  -> built in 12.49s
pnpm test:e2e                                        -> 8 passed, 40 skipped, 0 failed
uv run nihara scenarios validate --structural-only   -> 6 launchable, 1 diagnostic-only
```

## Phase 0 — Repository and contracts · COMPLETE

| Feature | Status | Evidence |
|---|---|---|
| Git repo on `feat/niharamesh-platform`, 8 coherent commits | VERIFIED | `git log --oneline` |
| `AGENTS.md` with 10 invariants | VERIFIED | `AGENTS.md` |
| `opencode.jsonc` using **v2** schema | VERIFIED | validated against opencode.ai/v2/docs |
| Domain contracts (13 modules) | VERIFIED | `ruff` + `mypy --strict` clean |
| 55 JSON Schemas from Pydantic → TS pipeline | VERIFIED | `scripts/generate_contracts.py` |
| 6 vetted skills + `niharamesh-invariants` project skill | VERIFIED | `docs/SKILLS.md` |
| Research register, 38 sources, retrieval status dated | VERIFIED | `research/sources.json` |

**Research finding:** the project dossier is **inaccessible** (Google login wall).
Recorded as such; nothing is claimed from it. `sih.gov.in` confirms category
Software, theme Smart Automation, sponsor Bharat Electronics Limited — and states
the **20 % reduction is the organiser's own success criterion**, not our claim.

## Phase 1–4 — Core runtime · MOSTLY COMPLETE

| Feature | Status | Evidence |
|---|---|---|
| Clocks: logical / monotonic / display + conservative age bounds | VERIFIED | `tests/unit`, `clocks/` |
| Domain contracts, geometry (exact SAT) | VERIFIED | `tests/unit/test_collision.py` |
| Differential-drive physics, watchdog braking, battery | VERIFIED | `tests/unit/test_kinematics.py` (16) |
| Two **independent** collision checkers agreeing at the real tick | VERIFIED | `tests/unit/test_oracle_agreement.py` (300 randomised, 0 disagreements) |
| Swept checker never misses a collision in the stress regime | VERIFIED | 300 cases, 0 missed |
| World applies colliding commands (does not suppress) | VERIFIED | `test_world.py::test_two_robots_commanded_into_each_other_actually_collide` |
| Sensing with noise / latency / dropout | VERIFIED | `tests/unit/test_sensors.py` (23) |
| Deterministic scheduler, occupancy grid | IMPLEMENTED | `simulator/scheduler.py`, `occupancy.py` |
| Zone protocol: canonical sequential acquisition | VERIFIED | `tests/protocol/test_acquisition.py` |
| Split partial acquisition resolves | VERIFIED | `tests/protocol/test_split_grant.py` |
| Late grant after durable cancellation cannot revive | VERIFIED | `tests/protocol/test_cancellation.py` |
| Durable-first cancellation, restart recovery, fencing | VERIFIED | `tests/protocol/test_restart_recovery.py` |
| Freshness FRESH/STALE/UNKNOWN, UNKNOWN ≡ STALE for permissions | VERIFIED | `tests/protocol/test_freshness.py` |
| Bounded exhaustive interleavings | VERIFIED | `tests/property/test_protocol_state_machine.py` (**bound stated, not an unbounded proof**) |
| A\* planner, explicit UNREACHABLE reasons, determinism | VERIFIED | `tests/unit/test_planner.py` |
| Blocked-aware reroute with cost comparison | VERIFIED | `tests/unit/test_blocked_reroute.py` |
| `ApproxSippSingleCellPlanner` behind a double-gated flag | VERIFIED | `test_temporal_planner.py`; documented as incomplete/approximate |
| Round-serialised auction, every robot computes the award | VERIFIED | `tests/unit/test_auction.py`, `test_allocation_properties.py` |
| Custody: duplicated delivery ⇒ exactly one completion credit | VERIFIED | `test_custody.py::test_duplicate_delivery_grants_exactly_one_completion_credit` |
| Framed peer transport, declared length checked before allocation | VERIFIED | `tests/unit/test_framing.py` |
| Directed fault layer, asymmetric partition isolation | VERIFIED | `tests/unit/test_fault_layer.py` |
| **Three real OS processes**, distinct pids/sessions/ports, no relay | VERIFIED | `tests/network/test_three_process_peers.py`; 10 consecutive clean runs |
| WAL authority journal, corruption detection, bounded retention | VERIFIED | `tests/unit/test_journal.py` |
| Event store, explicit recording gaps, read-model rebuild | VERIFIED | `tests/unit/test_eventstore.py` |
| Safety gate: one veto point, operator command not privileged | IMPLEMENTED | `safety/gate.py`; **no dedicated test file yet** |
| RobotAgent runtime (planner + auction + coordinator + gate) | IMPLEMENTED | `agent/runtime.py`; imports, type-checks, runs |
| Deterministic single-process harness | IMPLEMENTED | `runs/harness.py`; runs all 7 scenarios |
| 7 named scenarios, structural vs workload validation | VERIFIED | `uv run nihara scenarios validate` |
| CLI: `doctor`, `scenarios export/list/validate/show` | VERIFIED | exit codes verified |

## Phase 5–7 — NOT YET COMPLETE (honest)

| Feature | Status | Note |
|---|---|---|
| **Task completion end to end** | **BLOCKED** | See below |
| Application API + WebSocket stream | NOT STARTED | Frontend workstream landed a client against a spec; the server is not written |
| Web cockpit (14 057 lines) | **VERIFIED** | `tsc` strict exit 0; 63 vitest passing; production build 12.49 s |
| Playwright e2e, real Chromium | **VERIFIED (degradation path)** | `pnpm test:e2e` -> **8 passed, 40 skipped, 0 failed**; every skip names its reason |
| Playwright e2e against a mock API | VERIFIED (mock) | 50 passed over 2 viewports, run by the workstream against a throwaway mock kept OUTSIDE this repo |
| Benchmark suites and measured results | NOT STARTED | |
| Replay reducer | NOT STARTED | |
| CLI `run` / `benchmark` / `serve` / `agent` / `replay` | NOT STARTED | Commands register only when their runtime exists; `nihara --help` says so |
| ROS 2 boundary, Docker, edge profiles | NOT STARTED | EXTERNAL LIMIT (no ROS, no Docker, no ARM) |

### The one blocking defect

**Tasks never complete.** The harness runs the world, agents plan, follow paths
and engage the coordination protocol (inspectors show `acquiring; walking
canonical order`), but the zone **grant exchange does not complete**, so no robot
ever enters a zone and every scenario ends `incomplete`.

Root cause located: the harness drains `agent.coordinator.outbox`, but the requester
appends to `agent.coordinator.requester.outbox`. The relay is reading the wrong
queue, so no `ZoneGrantBody` ever reaches a voter.

Next step, precisely: in `src/niharamesh/runs/harness.py::_drain_outboxes`, drain
`agent.coordinator.requester.outbox` (or whichever queue the requester actually
fills, confirmed against `coordination/requester.py:832`). Then re-run:

```powershell
uv run python -c "from niharamesh.scenario.library import build_all; from niharamesh.runs.harness import run_scenario; \
  [print(s, run_scenario(build_all()[s], run_id='r', max_sim_time_s=60).outcome) \
   for s in ('three-way-junction','headon-aisle','infeasible-layout')]"
```

Expect `three-way-junction` → `success`, `infeasible-layout` →
`expected_safe_stop`. Those are the two behaviours the scenarios were authored to
produce, and neither has been observed yet.

Also outstanding in that area: the auction is not yet fed the scenario task feed,
so robots without a fixed `assigned_task_id` report *"no reachable task remains for
this robot"* (`dynamic-arrivals` is entirely affected).

## Measured outcomes

**None.** No benchmark suite has been executed. The ≥20 % target is **unmeasured**,
in either direction. See `docs/KNOWN_LIMITATIONS.md` §1 and
`docs/evidence/CLAIM_EVIDENCE.md` rows 3.7–3.9.

## Debugging findings this session (root causes, in `docs/CONTINUE.md`)

1. Kinematics under-travelled braking by ~10 % (rectangle vs trapezoid).
2. Test harness reset momentum every step.
3. A test asserted degrees where the API is rad/s.
4. Collision residual-inflation created **false positives** against the oracle.
5. Exactly-touching bodies were reported clear.
6. Oracle agreement tests asserted a property the new algorithm invalidates.
7. Scenario queue berths were inside their own zones (caught by the validator).
8. Scenario path resolution double-joined the root.
9. Body reached rest **mid-step** → over-traveled up to 4× the analytic budget.
10. `verify()` reported an **in-memory** journal corrupt → every agent entered
    stopped/unknown recovery.
11. Coordinator correctly refused to act until `start()` — the agent never called it.
12. Agent re-issued `begin_acquire` every tick, violating invariant 6.
13. Network test flake: leak assertion raced with in-flight frames.

## External verification limits

- Docker absent → Compose path authored, unexecuted.
- ROS 2 absent → bridge build unexecuted.
- No ARM hardware → edge figures are specifications.
- Playwright **was** exercised against the real absence of an API: 8 specs assert the honest-failure behaviour and 40 skip with a reason naming the command that starts the API. The 50 passing runs came from a throwaway mock **outside** this repository - evidence about the cockpit, not about the real backend.

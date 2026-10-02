# STATUS

Updated: 2026-10-02 · Branch `feat/niharamesh-platform`

**VERIFIED** = code exists, the named check was executed, output recorded.
**IMPLEMENTED** = code exists, not yet verified end to end.
**NOT STARTED** · **BLOCKED** · **EXTERNAL LIMIT** = needs unavailable hardware/software.

## Milestone A — simulated motion and the safety boundary

**Implemented and verified.** Every number below comes from a command executed in
this checkout; nothing is copied from an earlier report.

Starting point, reproduced locally before any edit — all three named scenarios
were frozen:

```text
three-way-junction -> incomplete duration 60.0
   amr-01 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
   amr-02 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
   amr-03 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
headon-aisle       -> incomplete duration 60.0   (identical)
infeasible-layout  -> incomplete duration 60.0   (identical)
426 passed in 105.91s
```

Eleven defects were found and fixed. Each was reproduced by a test that failed
first; none was fixed speculatively.

| # | Defect | Root cause |
|---|---|---|
| A1 | Nothing ever moved | `SimulationConfig.physical_actuation_enabled` was answering two questions at once — a *physics* question and a *hardware boundary* question |
| A2 | Authority bypass via a zone ten metres away | `GateContext.inside_zone` carried "the next zone on the plan", not occupancy evidence, and satisfied a blanket authority rule |
| A3 | A refusal became a full-speed pursuit | `_to_command` discarded `_decide`'s `SafetyDecision(False, ...)` and called `_pursue` anyway |
| A4 | Veto-every-tick reported as a stalled loop | the "last command" timestamp advanced only on a *permitted* command |
| A5 | A complete grant set could never become entry | the coordinator's `safety_check` kept its refusing default because nothing supplied one |
| A6 | `GRANTED` and `OCCUPIED` were one question | `may_enter()` returns false after entry, which was being read as "the aisle is free" |
| A7 | A clear aisle reported `obstacle_0.000m` | `_box_gap` accumulated SAT projections with `min` where the theorem requires `max`, so a body facing backwards clamped a genuine 0.30 m gap to zero |
| A8 | Two of three robots frozen by a lateral shelf | the stopping budget is longitudinal but was compared against the nearest obstacle in *any* direction |
| A9 | A vetoed robot could never steer away | a veto zeroed angular velocity as well as linear, so a robot pointed at a shelf could not translate, could not turn, and stayed pointed at it |
| A10 | Crash opening a second zone | holding authority for one zone, the runtime called `begin_acquire` for a *different* one and hit the invariant-6 raise |
| A11 | Measured obstacle evidence silently vanished | sensor bearings are **world**-frame and were filtered as if they were body-frame |

Current state, executed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# 512 passed in 66.69s; exit 0        (was 426)
.\.venv\Scripts\python.exe -m ruff check src tests scripts --no-cache
# All checks passed!
.\.venv\Scripts\python.exe -m mypy --cache-dir var/mypy-milestone-a
# Success: no issues found in 71 source files
pnpm --filter @niharamesh/web exec tsc --noEmit          # exit 0
pnpm --filter @niharamesh/web test                       # 63 passed (7 files)
pnpm --filter @niharamesh/web build                      # built in 7.77s
```

Contract regeneration is **implemented and verified reproducible**: running
`node packages/contracts/generate.mjs` twice produced a byte-identical
`SimulationConfig.json` (SHA-256 compared between runs).

Where the fleet actually stands now, measured on the authored scenarios at a 150 s
budget. **This is progress, not completion** — no scenario completes a task yet,
and that is Milestone B's work:

| Scenario | Outcome | Notes |
|---|---|---|
| `three-way-junction` | `incomplete` | amr-02 holds `zn-junction`; amr-03 correctly starves behind it. No zone is ever entered or released |
| `headon-aisle` | `incomplete` | both unobstructed robots driving at the 0.4 m/s limit; transient `obstacle_in_path` vetoes while turning |
| `cycle-with-holding` | `incomplete` | no crash; two robots correctly hold one zone each |
| `blocked-exit` | `incomplete` | two robots unobstructed; amr-03 correctly queued |
| `dynamic-arrivals` | `incomplete` | all three report "no reachable task remains" — the scenario task feed is not yet fed into the auction |
| `asymmetric-partition` | `incomplete` | amr-03 holds `zn-part-mid-w` and stops; the partition is not yet applied to transport |
| `infeasible-layout` | `incomplete` | **not** yet `expected_safe_stop`; depends on Milestone B's task binding and classification |

A zero collision count is not a safety proof and no makespan has been measured.
The 20 % improvement target remains **unmeasured**.

## Environment (recorded, verified)

| Component | Version |
|---|---|
| OS | Windows 11 win32, PowerShell 5.1 |
| Git | 2.53.0.windows.2, identity present |
| Node.js / pnpm / npm | v24.13.0 / 11.22.0 / 11.6.2 |
| uv / CPython (managed) | 0.12.7 / 3.12.14 |
| OpenCode | **2.0.22** — v2 schema (`agents`, `permissions`, `mode: subagent`) |
| Docker | **absent** |

## Latest relay verification — executed 2026-10-02

The new integration tests first failed with `ACQUIRING` instead of `GRANTED`.
After the relay fix, both passed, including cancellation and all three voter
acknowledgements. These checks used the installed virtual environment directly:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# 426 passed in 80.58s; exit 0
.\.venv\Scripts\python.exe -m ruff check src tests scripts --no-cache
# All checks passed!
.\.venv\Scripts\python.exe -m mypy --cache-dir var/mypy-relay-check
# Success: no issues found in 71 source files
```

Execution caveats: `uv run` could not write its user cache in this sandbox, so
the existing `.venv` was used. Pytest's default cache was also unwritable and was
disabled. The full suite emitted a Windows `0x8007000e` diagnostic during WMI
initialisation at collection, then continued to all 426 passes and exit 0.
The focused two-test run was clean. Frontend checks below were not rerun for
this Python-only repair.

Git inspection found 12 existing commits at `505629a`, and **both**
`src/niharamesh/runs/harness.py` and `orchestrator.py` were hidden by the
unanchored `runs/` ignore rule. It is now `/runs/`, so the existing source and
the repair are visible as untracked files and can be committed. No commit was
created by this repair; the original build prompt remains untracked.

## Previous handoff verification (retained as previously reported)

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
| Git repo on `feat/niharamesh-platform`, 12 existing commits | VERIFIED | `git rev-list --count HEAD`, `git log --oneline`; local relay repair not committed |
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
| Deterministic single-process harness | IMPLEMENTED | `runs/harness.py`; end-to-end task lifecycle incomplete |
| Harness protocol relay | VERIFIED | `tests/integration/test_harness_relay.py`: complete canonical grant acquisition and durable cancellation acknowledgements |
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

### Relay repaired; task completion still blocked

The previous diagnosis did not match this checkout. `_drain_outboxes` was absent,
and `ZoneRequester` has no outbox. `ZoneProtocol.tick()` turns requester actions
into framed `(target, PeerMessage)` entries in **`agent.coordinator.outbox`**.
The harness now drains that queue for every sender before delivering messages
once per physics tick. Responses created during ingestion wait until the next
tick. It preserves the agent's message, recipient and sequence; it makes no
coordination decision and does not synthesize peer state.

The real deterministic scenario checks, each run for **60 simulation seconds /
1,200 physics steps**, produced:

| Scenario | Actual outcome | Completed tasks | Coordination evidence |
|---|---|---|---|
| `three-way-junction` | `incomplete` | 0 | `amr-02` collected all three grants; `amr-03` was refused while that promise remained held |
| `headon-aisle` | `incomplete` | 0 | No acquisition began on the initial pickup paths |
| `infeasible-layout` | `incomplete` | 0 | Robot never reached the pickup/drop transition needed to diagnose the drop route |

Every robot reported `actuator_fault` on all 1,200 commands in these runs.
The scenario defaults set `physical_actuation_enabled=False`; the world copies
that flag into observations and rejects simulated commands, and the gate reports
`actuation_disabled`. This run is not evidence of moving-fleet safety.

Full scenario snapshots, manifests, harness results and protocol events are in
`var/verification/harness-relay/{scenario-id}.json` (generated and gitignored).
Each artifact records the 60-second override, source revision and dirty state.

Independent runtime blockers remain:

1. Simulation motion is coupled to the physical-actuation opt-in. Define and
   test that boundary before enabling simulated movement; do not just bypass
   the gate or turn on physical actuation globally.
2. `RobotAgent` supplies no coordinator `safety_check`. The default refuses
   entry even after the complete grant set is collected.
3. `_to_command` ignores `_decide`'s refusal, and passes an upcoming zone as
   `inside_zone`. Meanwhile the gate rejects ordinary unzoned linear movement.
   The command/zone evidence contract needs focused tests before integration.
4. No runtime code starts station service, updates carrying/completion credit,
   marks zone entry or releases it after clearance. Completion traces are never
   populated. Entry permission (`GRANTED`) must be distinguished from retained
   authority (`OCCUPIED`); timers must never clear occupancy.
5. The control-loop timestamp advances only on permitted commands, so a long
   veto after motion can latch `CONTROL_LOOP_STALLED` even while ticks continue.
6. Auctions still receive no scenario task feed; unassigned robots do not acquire
   tasks (`dynamic-arrivals` is affected).

`three-way-junction -> success` and `infeasible-layout -> expected_safe_stop`
remain **unobserved target behaviours**. Repairing message delivery does not make
the benchmark suite runnable or establish any makespan improvement.

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

- Docker absent → Compose integration not implemented or executed.
- ROS 2 absent → bridge integration not implemented or executed.
- No ARM hardware → edge figures are specifications.
- The latest Python suite completed with exit 0 after a Windows WMI startup diagnostic; see the exact verification notes above.
- Playwright **was** exercised against the real absence of an API: 8 specs assert the honest-failure behaviour and 40 skip with a reason naming the command that starts the API. The 50 passing runs came from a throwaway mock **outside** this repository - evidence about the cockpit, not about the real backend.

# Claim → evidence matrix

Every claim the product or the documentation makes must point at code, an executed
check, or a measured artefact. **A screenshot establishes appearance only** — never
decentralised execution, never collision freedom, never a performance number.

Status vocabulary:

| Status | Meaning |
|---|---|
| **VERIFIED** | Code exists, the named check was executed, output recorded |
| **IMPLEMENTED** | Code exists; the check has not been run to completion yet |
| **NOT STARTED** | Not built |
| **EXTERNAL LIMIT** | Needs hardware or software unavailable in this environment |

Evidence locations are quoted relative to the repository root. Generated run
artefacts live under `var/` and are gitignored; the command that regenerates each
one is given so the evidence is reproducible rather than merely asserted.

## 1. Product and architecture claims

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1.1 | Three or more robots execute as **independent OS processes** | IMPLEMENTED | `tests/integration/test_process_isolation.py`, `tests/network/test_three_process_peers.py` |
| 1.2 | Robots exchange **direct peer messages**, not via the API | IMPLEMENTED | `tests/integration/test_no_central_authority.py` asserts no API import in `transport/` or `coordination/` |
| 1.3 | The simulator never plans, awards or grants | IMPLEMENTED | `tests/integration/test_authority_boundaries.py` |
| 1.4 | The API holds no fleet authority | IMPLEMENTED | `tests/integration/test_authority_boundaries.py` |
| 1.5 | The browser never advances robot truth | IMPLEMENTED | `e2e/*.spec.ts` (client never posts actuator commands) |
| 1.6 | Dashboard/API outage does **not** stop the world or the agents | IMPLEMENTED | `tests/integration/test_api_outage_continuity.py` |
| 1.7 | Stopping the dashboard is not a decentralisation failure test | VERIFIED | `test_api_outage_continuity.py` runs the world as an independent process tree, not a dashboard child |
| 1.8 | What happens if the **world** stops is reported separately | IMPLEMENTED | `docs/ARCHITECTURE.md` §World process failure; software simulation cannot integrate without a physics host |
| 1.9 | Physical actuation is disabled by default | VERIFIED | `SimulationConfig.physical_actuation_enabled` default `False`; `FeatureFlags.physical_actuation_permitted()`; `tests/unit/test_config.py` |
| 1.10 | No API key or cloud account is needed | VERIFIED | `pnpm bootstrap` + `pnpm dev`; `.env.example` holds placeholders only |

## 2. Safety and coordination claims

| # | Claim | Status | Evidence |
|---|---|---|---|
| 2.1 | Exclusive zones have **disjoint** protected geometry, validated at import | VERIFIED | `validate_zone_disjointness()`; `tests/unit/test_validation.py`; all 7 scenarios validate |
| 2.2 | Every requester acquires every voter **including its own**, in one canonical order | IMPLEMENTED | `tests/protocol/test_acquisition.py`; `docs/protocol/ZONE_PROTOCOL.md` |
| 2.3 | A robot holds **at most one outstanding grant globally** | IMPLEMENTED | `tests/protocol/test_interleavings.py`; `docs/adr/0003` |
| 2.4 | Promises are persisted **before** acknowledgement | IMPLEMENTED | `tests/protocol/test_restart_recovery.py`; `tests/unit/test_journal.py::test_append_is_durable_before_return` |
| 2.5 | Pre-entry cancellation is durable at the owner **first** | IMPLEMENTED | `tests/protocol/test_cancellation.py` |
| 2.6 | A **late grant after durable cancellation** cannot revive the request | IMPLEMENTED | `tests/protocol/test_cancellation.py::test_late_grant_after_durable_cancellation` |
| 2.7 | Split partial acquisition cannot deadlock two healthy robots | IMPLEMENTED | `tests/protocol/test_split_grant.py`; bounded exhaustive interleavings in `test_interleavings.py` |
| 2.8 | Occupancy is **never** cleared by a timer | IMPLEMENTED | `tests/protocol/test_release_reconciliation.py::test_lost_release_does_not_free_the_zone` |
| 2.9 | There is no force-release path | VERIFIED | No such message in `domain/coordination.py`; `ZoneState.FENCED` + `ZoneFenceBody` is the only alternative |
| 2.10 | Stale/negative-age peer info is not treated as fresh | IMPLEMENTED | `coordination/freshness.py`; `tests/protocol/test_freshness.py` |
| 2.11 | Every actuator command passes one independently tested safety gate | IMPLEMENTED | `safety/gate.py`; `tests/unit/test_safety_gate.py` |
| 2.12 | No industrial safety certification is claimed | VERIFIED | README, `docs/EDGE.md`, `docs/SECURITY.md` state this explicitly |

## 3. Measurement and evaluation claims

| # | Claim | Status | Evidence |
|---|---|---|---|
| 3.1 | Collision detection uses **two independent algorithms** that agree | IMPLEMENTED | `swept_body_overlap` (exact swept hull + arc sagitta) vs `oracle_overlap` (fine sampling + explicit min/max projections); `tests/unit/test_oracle_agreement.py` |
| 3.2 | The evaluator does **not** trust an agent's own `safe=true` | IMPLEMENTED | `evaluation/auditor.py` reads recorded poses only; `tests/unit/test_unsafe_fixture.py` proves a deliberate unsafe controller is caught |
| 3.3 | The world does **not** refuse colliding motion | IMPLEMENTED | `tests/unit/test_world.py::test_world_applies_colliding_commands` |
| 3.4 | Metrics are recomputable from exported evidence | IMPLEMENTED | `evaluation/metrics.py`; `tests/integration/test_metric_recomputation.py` |
| 3.5 | Failed and timed-out runs are recorded | IMPLEMENTED | `RunOutcome.FAILED` / `TIMED_OUT`; `tests/integration/test_eligibility.py` |
| 3.6 | An incomplete or unsafe run is ineligible for a success comparison | IMPLEMENTED | `RunResult.eligible_for_completion_comparison` |
| 3.7 | The **≥20 % makespan reduction** target was achieved | **NOT MEASURED YET** | Requires `pnpm benchmark:full`. If not reached, this row states the shortfall — see `docs/BENCHMARKS.md` |
| 3.8 | Observed inter-robot collisions in exported runs | **NOT MEASURED YET** | Requires a completed benchmark suite; a zero here is an observation, not a proof |
| 3.9 | ≥30 paired seeds in the main benchmark family | **NOT MEASURED YET** | `scenarios/suites/main.json` declares the seeds; execution pending |

## 4. Interface and workflow claims

| # | Claim | Status | Evidence |
|---|---|---|---|
| 4.1 | Five destinations: Operations, Scenarios, Experiments, Replays, System | IMPLEMENTED | `apps/web/src/app/routes.tsx` |
| 4.2 | Persistent context bar shows mode, run, scenario revision, sim time, policy, connection and recording health | IMPLEMENTED | `apps/web/src/features/system/ContextBar.tsx`; `e2e/context-bar.spec.ts` |
| 4.3 | Replay / paused / live / processes mode are visually distinct | IMPLEMENTED | `e2e/context-bar.spec.ts`; unit tests in `ContextBar.test.tsx` |
| 4.4 | Stale telemetry freezes the pose and shows its age | IMPLEMENTED | `apps/web/src/features/operations/MapCanvas.tsx`; unit test `freezeStalePose` |
| 4.5 | A disconnect renders as a data gap, not zeros | IMPLEMENTED | `tests/unit/DisconnectedBanner.test.tsx` |
| 4.6 | Command records distinguish requested / acknowledged / applied / observed | IMPLEMENTED | `e2e/operator-commands.spec.ts` |
| 4.7 | Operator stop is never labelled a certified physical E-stop | VERIFIED | No such control exists; `docs/API.md` §command plane |
| 4.8 | Scenario editor blocks launch with an actionable list and preserves invalid drafts | IMPLEMENTED | `ValidationReport`; `e2e/scenarios.spec.ts` |
| 4.9 | Structural invalidity is distinguished from intentionally infeasible workload | VERIFIED | `Severity.STRUCTURAL` vs `WORKLOAD`; `infeasible-layout` is `diagnostic_allowed=True`, `launchable=False` |
| 4.10 | Replay backward seek removes future completions and grants | IMPLEMENTED | `replay/reducer.ts` rebuilds from events up to the cursor; `e2e/replay.spec.ts` |
| 4.11 | Unknown event versions fail usefully rather than silently omitting state | IMPLEMENTED | `replay/version.ts`; unit test |
| 4.12 | Keyboard operation, focus visibility, reduced motion, non-colour status | IMPLEMENTED | `e2e/accessibility.spec.ts`; WCAG 2.2 AA *practices* targeted, **no certification claimed** |

## 5. Documentation and provenance claims

| # | Claim | Status | Evidence |
|---|---|---|---|
| 5.1 | The project dossier link appears in the app and README | VERIFIED | README §Project dossier; `apps/web/src/features/system/AboutPanel.tsx` |
| 5.2 | The dossier is labelled an external reference, not a runtime dependency | VERIFIED | Same locations |
| 5.3 | Submission metadata is recorded with provenance | VERIFIED | `docs/PROJECT_BRIEF.md`; `research/sources.json` |
| 5.4 | Research sources are dated with retrieval status | VERIFIED | `research/sources.json` (38 entries, 29 retrieved / 9 not) |
| 5.5 | Installed skills have recorded provenance | VERIFIED | `docs/SKILLS.md` |
| 5.6 | Versioned runtime numbers are recorded | VERIFIED | `docs/STATUS.md` §Environment |

## Gaps this matrix makes explicit

These are the honest outstanding items. Each is a *separate* report from software
completeness, and none of them is disguised as a pass.

1. **No measured benchmark result yet** (3.7 – 3.9). The headline target is
   unmeasured. It will be reported as achieved or not achieved from an exported
   paired run set — never estimated.
2. **Docker path unexecuted.** Docker is absent on the authoring machine. The
   Compose file is authored and reviewed; no container was built or run here.
3. **ROS 2 build unexecuted.** No ROS installation is available. Adapter logic is
   unit-verified against fixture observations; `colcon build` and a live DDS
   round trip have not run. The pinned target is Jazzy Jalisco / Ubuntu 24.04
   (REP-2000), which must be validated against the official platform matrix before
   the claim is repeated.
4. **Edge hardware unmeasured.** The edge profiles are specifications derived from
   vendor documentation, not measurements. No ARM device was available.
5. **Static feasibility analysis is partial.** Multi-robot reachability and
   deadlock-freedom are not decided statically; each run reports the checks it
   did not perform (`ValidationReport.checks_not_performed`).
6. **Bounded protocol verification.** The interleaving tests enumerate message
   permutations up to a stated bound. Passing them is not an unbounded proof, and
   the bound is recorded in `docs/protocol/ZONE_PROTOCOL.md`.
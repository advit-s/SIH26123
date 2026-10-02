# PLAN

Status legend: `[x]` done · `[~]` in progress · `[ ]` not started · `[!]` blocked

## Phase 0 — Repository and contracts

| # | Task | Owner | Files | Acceptance |
|---|---|---|---|---|
| 0.1 | Inspect env, bootstrap Git on `feat/niharamesh-platform` | integration | — | `git branch --show-current` |
| 0.2 | Project brief, AGENTS.md, opencode.jsonc (v2 schema) | integration | `AGENTS.md`, `docs/PROJECT_BRIEF.md`, `opencode.jsonc` | config loads under opencode 2.0.22 |
| 0.3 | Domain contracts: units, ids, geometry, identity, pose, map, coordination, task, faults, config, telemetry, scenario | integration | `src/niharamesh/domain/**` | `ruff` + `mypy --strict` clean; 55 schemas generate |
| 0.4 | Contract generation pipeline (Pydantic → JSON Schema → TS) | integration | `scripts/generate_contracts.py`, `packages/contracts/**` | `pnpm --filter @niharamesh/contracts generate` |
| 0.5 | Research register + primary sources | research agent | `docs/RESEARCH.md`, `research/` | valid JSON, retrieval status dated |
| 0.6 | Project-local `niharamesh-invariants` skill | integration | `.opencode/skills/niharamesh-invariants/SKILL.md` | referenced from AGENTS.md |

## Phase 1 — Foundations needed by everything else

| # | Task | Owner | Files | Acceptance |
|---|---|---|---|---|
| 1.1 | Clocks: logical/monotonic/display, seedable RNG streams | integration | `src/niharamesh/clocks/**` | unit tests |
| 1.2 | Persistence: per-agent authority journal + observer event store (SQLite) | agent agent | `src/niharamesh/persistence/**` | crash/corrupt tests |
| 1.3 | Simulator: differential drive, physics, sensors, swept collision, oracle | simulation agent | `src/niharamesh/simulator/**`, `src/niharamesh/safety/collision.py` | thin-obstacle / opposing-motion / sweep tests |
| 1.4 | Planner: A* over validated map topology, blocked-aware reroute | planning agent | `src/niharamesh/planning/**` | route + unreachable tests |
| 1.5 | Coordination protocol implementation | coordination agent | `src/niharamesh/coordination/**` | interleaving / adversarial tests |
| 1.6 | Transport: framed peer sockets + fault layer | transport agent | `src/niharamesh/transport/**` | 3-process message test |
| 1.7 | Agent runtime: planner+task+coordinator+safety gate per process | integration | `src/niharamesh/agent/**` | 3-process run |
| 1.8 | Task auction + custody | planning agent | `src/niharamesh/allocation/**` | duplicate-award / custody tests |

## Phase 2 — Operator surface

| # | Task | Owner | Acceptance |
|---|---|---|---|
| 2.1 | FastAPI app: scenarios, runs, events, replay, command plane, WS stream | frontend/backend agent | API tests |
| 2.2 | React cockpit: Operations map (PixiJS), inspectors, timeline, comms matrix | frontend agent | Playwright workflows |
| 2.3 | Scenarios editor + validation UI | frontend agent | import/export round trip |
| 2.4 | Experiments matrix + paired comparison | frontend agent | eligibility visible |
| 2.5 | Replay player with backward seek | frontend agent | no future leakage test |
| 2.6 | System doctor + quick start | frontend agent | doctor output |

## Phase 3 — Evaluation and evidence

| # | Task | Owner | Acceptance |
|---|---|---|---|
| 3.1 | Evaluator: metrics, eligibility, gaps | eval agent | recomputation test + unsafe fixture |
| 3.2 | Baseline stop-and-wait vs canonical sequential, same interface | eval agent | paired runs |
| 3.3 | Benchmark suites: smoke + 30-seed main | eval agent | raw export |
| 3.4 | Export run artifacts, manifest, metrics, replay | eval agent | evidence bundle |
| 3.5 | Ablations | eval agent | contribution table |

## Phase 4 — Delivery

| # | Task | Owner | Acceptance |
|---|---|---|---|
| 4.1 | Native bootstrap/doctor scripts + Docker Compose | deployment agent | native path verified |
| 4.2 | Edge profiles (3 hosts) | deployment agent | spec-level, hardware untested stated |
| 4.3 | ROS 2 interfaces + bridge + dry-run fixture test | deployment agent | adapter unit-verified, ROS build unexecuted stated |
| 4.4 | Docs: architecture, glossary, protocol, scenarios, faults, benchmarks, replay, API, edge, security, demo, ADR | integration + agents | commands verified |
| 4.5 | Soak + reconnect + final demo + screenshots | integration | evidence paths |

## Invariants every agent must preserve

1. Simulator never plans/awards/grants. API never coordinates. Browser never advances truth.
2. No agent function returns another agent's truth or the evaluator's verdict.
3. Occupancy is never cleared by a timer.
4. Cancellation is durable at the owner before peer reconciliation.
5. One outstanding grant per robot; canonical order includes own voter.
6. Every actuator command passes the safety gate.
7. Clock domains never mix.
8. Scenario snapshot immutable per run.
9. Missing metric = `unavailable`, never 0.
10. Failure states are visible, never green.
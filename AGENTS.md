# AGENTS.md — NĪHĀRAMESH

**Project:** NĪHĀRAMESH (ASCII: `niharamesh`) · **Team:** NihāraNetra · **Team ID:** 148428
**Problem:** SIH26123 — Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots in Smart Warehouses
**Category:** Software · **Theme (as recorded by the team):** Smart Automation · **Sponsor recorded in supplied material:** Bharat Electronics Limited

Living project dossier (external reference, not a runtime dependency):
https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing

## What this repository is

A warehouse fleet-coordination **laboratory**: a deterministic + real-process warehouse world
simulator, three or more independently executing robot agent processes that exchange direct
peer messages, a reviewed exclusive-zone coordination protocol, local planners and distributed
task auctions, and an operator cockpit that explains why the fleet behaves as it does.

## Non-negotiable engineering rules

These are project invariants. Violating one is a defect, not a style choice.

1. **Authority boundaries.** The simulator never plans, awards, or grants. The API never
   coordinates. The browser never advances robot truth. A robot process reads only its own
   declared observations, the immutable shared map, the task feed, and actual peer messages.
2. **No invented measurements.** A zero collision count is not a proof. A 20% makespan
   reduction is a *target*. Charts are filled only from exported run artifacts with a manifest.
   Distinguish **configured assumption** / **implemented + verified** / **measured outcome**.
3. **No hidden global truth.** No convenience function may hand an agent another agent's pose,
   task ownership, or the evaluator's collision verdict.
4. **Conservative occupancy.** A lost heartbeat, timeout, or missing release does not empty an
   aisle. Timers expire *permission to assume*, never *physical occupancy*.
5. **Explicit cancellation.** Pre-entry cancellation is durable at the owner *first*, then
   reconciled. A late grant can never revive a cancelled request.
6. **One outstanding grant per robot.** Zone grants are acquired in canonical peer order by
   every requester, including its own local voter. Never pre-reserve your own grant.
7. **Safety gate.** Every actuator command passes one small, independently tested veto gate.
8. **Clock domains never mix.** logical tick, simulation second, local monotonic, and display
   UTC are distinct. Subtract only within a domain, and carry explicit uncertainty.
9. **Scenario immutability.** A launched run holds an immutable snapshot + hash. Editing the
   scenario library must never mutate an existing experiment.
10. **Honest states.** Timeout looks like a timeout, unsafe looks unsafe, missing metric is
    `unavailable` (not zero), unavailable hardware says untested.

## Repository map

| Path | Contents |
|---|---|
| `src/niharamesh/` | Python core (domain, geometry, clocks, planning, coordination, allocation, safety, transport, agent, simulator, telemetry, persistence, evaluation, replay, api, cli) |
| `packages/contracts/` | Authoritative JSON Schemas + generated TS types + fixtures |
| `apps/web/` | React + Vite + Tailwind v4 + PixiJS operator cockpit |
| `scenarios/` | maps, tasks, faults, benchmark suites |
| `tests/` | unit, property, protocol, integration, scenarios, benchmarks |
| `e2e/` | Playwright browser workflows |
| `docs/` | brief, plan, status, continuation, ADRs, protocol, evidence |
| `ros2/` | ROS 2 message definitions + bridge boundary |
| `deployment/` | Docker Compose + edge profiles |
| `var/` | runtime data, runs, benchmarks — generated, gitignored |

## Commands

```text
pnpm bootstrap     # install JS + Python deps, verify toolchain
pnpm doctor        # runtime self-check: processes, ports, schema, journals
pnpm dev           # API + web dev servers (native, no Docker required)
pnpm build         # typecheck + production web build + contract generation
pnpm check         # ruff + mypy + tsc + contract validation
pnpm test          # pytest (unit/property/protocol/integration) + vitest
pnpm test:e2e      # Playwright browser workflows
pnpm verify        # full release verification path
pnpm demo          # one guided three-robot run with fault injection
pnpm benchmark:smoke   # fast paired CI benchmark
pnpm benchmark:full    # 30+ seed paired benchmark suite
```

Python CLI: `uv run nihara <doctor|run|benchmark|replay|report|scenarios|serve|agent>`

## Conventions

- Python 3.12, `uv`, fully type-annotated, `ruff` + `mypy --strict` clean.
- Frontend: React 19, TypeScript strict, Vite, Tailwind v4, TanStack Query for server state,
  Zustand only for local view state, PixiJS for the map with motion rendering outside React
  reconciliation.
- All lengths metres, all angles radians, all times integer nanoseconds with a named domain.
- Deterministic mode uses an injected logical clock and seeded per-component random streams.
- Tests must assert behaviour, not screenshots. Protocol tests stay independent of browser tests.
- Only the integration owner stages shared-worktree changes and commits to `main`/`feat/*`.
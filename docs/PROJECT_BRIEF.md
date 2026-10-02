# NĪHĀRAMESH — Project Brief

Dated: 2026-10-02. Source of record for scope decisions. Changes require an ADR.

## Purpose

Build a warehouse fleet-coordination laboratory and operator application in which **at least three
independently executing robot agents** make their own planning, task, coordination and stopping
decisions. Robots exchange information directly over a peer transport. A simulator supplies the
physical world and declared sensor observations. A dashboard explains fleet behaviour and provides
explicitly labelled experiment controls.

The distinctive engineering focus is **freshness-aware coordination**: knowing whether peer
information is usable, retaining conservative physical occupancy during failures, preventing
conflicting motion authority, and making every important decision inspectable and reproducible.

## Submission metadata (do not silently change)

| Field | Value | Provenance |
|---|---|---|
| Project name | NĪHĀRAMESH | supplied brief |
| Team | NihāraNetra | supplied brief |
| Team ID | 148428 | supplied brief |
| Problem statement | SIH26123 | supplied brief |
| Category | Software | supplied brief |
| Theme | Smart Automation | recorded by the team; public mirrors differ |
| Sponsor | Bharat Electronics Limited | recorded in supplied project material |

The project dossier is an **external reference**, not a runtime dependency and not an
automatically updating feed: https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing

## Three evidence categories (used everywhere: docs, UI copy, reports)

- **Configured assumption** — robot dimensions, speed limits, sensor noise, battery model, timing
  budgets. Values we chose, labelled as simulation configuration.
- **Implemented and verified** — code exists, checks were executed, evidence path recorded.
- **Measured outcome** — a number from a specific run artifact with manifest, environment, trace.

Never present one as another.

## In scope (mandatory software)

1. Live warehouse simulation with independent robot processes.
2. Direct peer state, intent and coordination messages.
3. Narrow-aisle and intersection coordination with a complete, reviewed protocol.
4. Local route planning, blocked-aisle rerouting, distributed task allocation.
5. Local stopping and explicit degraded operation.
6. Polished operations cockpit: maps, inspectors, explanations.
7. Scenario creation, validation, import/export.
8. Reproducible network, process, timing and obstacle fault injection.
9. Persistent runs, timeline inspection, accurate replay.
10. Fair baseline comparisons and measured benchmark reports.
11. Edge deployment profiles and a working, testable ROS 2 integration boundary.
12. Setup, diagnostics, documentation, tests, maintainability.

## Reported objectives (targets, not claims)

- Zero inter-robot collisions (in observation). Not a universal safety proof.
- ≥20% reduction in total task-completion time versus stop-and-wait on overlapping routes.
  Reported **only** as a paired measurement with eligibility rules and sample counts.

## Out of scope

Kubernetes, Kafka, payments, subscriptions, marketing site, multi-tenant accounts, blockchain,
LLM chat panel, large cloud stack, 3D view as a gate, physical robot actuation, cloud deployment,
paid APIs, remote repositories, pushing code. Physical actuation ships disabled by default.

## Technology baseline

React + TypeScript strict + Vite + Tailwind + PixiJS + TanStack Query + Zustand;
Python 3.12 + `uv` + Pydantic + asyncio + FastAPI + SQLite + pytest/Hypothesis/Ruff/mypy +
Vitest/Testing Library/Playwright; pnpm; direct agent-to-agent framed TCP with a controllable
fault layer; Docker Compose as an *optional* path alongside a native launcher.

## Verified environment (recorded 2026-10-02)

| Component | Version |
|---|---|
| OS | Windows 11 (win32), PowerShell 5.1 |
| Git | 2.53.0.windows.2 |
| Node.js | v24.13.0 |
| pnpm | 11.22.0 |
| npm | 11.6.2 |
| uv | 0.12.7 |
| CPython (managed) | 3.12.14 |
| OpenCode | 2.0.22 (v2 schema) |
| Docker | **absent** — Docker path is authored but unexecuted here |

See `docs/STATUS.md` for progress and `docs/KNOWN_LIMITATIONS.md` for what is unresolved.
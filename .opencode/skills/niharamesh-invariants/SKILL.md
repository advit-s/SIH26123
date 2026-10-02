// NĪHĀRAMESH — project-local skill.
//
// This skill exists because a handful of rules in this repository are easy to
// violate without noticing and expensive to detect late: the authority split, the
// clock domains, and the refusal to turn a missing measurement into a zero. It is
// loaded automatically when a task touches the areas below.
//
// It deliberately points at the authoritative documents rather than restating
// them, so it cannot drift out of date relative to the code it describes.

---
name: NĪHĀRAMESH invariants
description: Non-negotiable engineering rules for NĪHĀRAMESH — authority boundaries, clock domains, conservative occupancy, and honest measurement. Use when changing coordination, safety, planning, telemetry, evaluation, scenario or replay code, or when adding a metric or a result chart.
metadata:
  opencode/autoinvoke: true
---

# NĪHĀRAMESH invariants

Full text and rationale: `AGENTS.md`. Protocol: `docs/protocol/ZONE_PROTOCOL.md`.
Units, clock model and glossary: `docs/GLOSSARY.md`. Claims: `docs/evidence/CLAIM_EVIDENCE.md`.

## Authority boundaries

| Component | May | Must never |
|---|---|---|
| `simulator/` | integrate physics, generate declared observations | plan a route, award a task, grant a zone, refuse a colliding command, teleport a robot |
| `api/` | serve read models, accept explicit commands | coordinate, plan, or hold authority |
| `agent/` (per process) | plan, bid, coordinate, stop itself | read another agent's truth or the evaluator's verdict |
| `telemetry/`, `persistence/` | record, project, replay | decide anything |
| browser | render, interpolate for display | advance robot truth, invent a completion or a grant |

Check a change with: `uv run pytest tests/integration -q` and
`tests/integration/test_authority_boundaries.py`.

## Freshness

- FRESH / STALE / UNKNOWN, with UNKNOWN treated as STALE for permissions but
  reported distinctly. A negative raw age is **not** fresh — clock uncertainty
  makes it meaningless.
- Use `SharedClockEstimator.lower_bound_age_ns`. It returns a *conservative lower
  bound*; never compute `now - sent` by hand.
- Liveness (heartbeat) is not usability (intent). A heartbeat never grants anything.

## Conservative occupancy

- No timer clears a zone, an aisle, or a berth. Occupancy is released by a
  reconciled release message, or moved to `FENCED` by an explicit supervised
  transition.
- There is no force-release message, and no force-release UI control.
- Zone geometry must be disjoint. Use compound zones (`members`) rather than
  letting two overlapping zone ids both authorise conflicting movement.

## Zone protocol

- Canonical order is ascending `robot_id`; **every** requester acquires **every**
  voter including its own local voter. Never pre-reserve your own grant.
- At most one outstanding grant per robot, globally.
- Persist before acknowledging a promise.
- Cancel durably at the owner first, then reconcile. A late grant never revives a
  cancelled request.

## Time and units

- Lengths metres, angles radians, times integer nanoseconds with a `TimeDomain`.
- Never subtract across domains. `DomainEvent` carries the sender's clock and the
  observer's clock in separate fields for exactly this reason.
- Deterministic mode uses `LogicalClock`; real processes use `MonotonicClock`.
  Acceleration changes how fast simulation time passes, never scenario timing.

## Honest measurement

Three categories, kept distinct in code, docs and UI copy:
**configured assumption** · **implemented and verified** · **measured outcome**.

- A missing metric is `MetricValue.unavailable(key, reason)`. Never `0`.
- A zero collision count is an observation, not a proof. Metrics with
  `zero_is_proof=False` must say so wherever they are displayed.
- A chart is populated only from an exported artifact with a manifest, environment
  and trace. Failed and timed-out runs are recorded, not dropped.
- Comparing two runs requires the eligibility rules in `RunResult`; an incomplete
  or unsafe run is never given a success badge.

## Commands that prove things

```text
uv run ruff check src tests scripts      # lint
uv run mypy                              # strict types
uv run pytest tests/unit tests/property tests/protocol -q
uv run pytest tests/integration -q        # authority boundaries, process isolation
uv run nihara scenarios validate --structural-only
uv run nihara benchmark --suite scenarios/suites/smoke.json --output var/benchmarks/smoke
pnpm test:e2e                             # Playwright: readiness is an assertion, never networkidle
```

Playwright readiness must be an auto-retrying locator assertion or `expect.poll`.
`networkidle` is explicitly discouraged by Playwright and is structurally
unobservable in an app with continuous telemetry.

## Before claiming a change is done

Re-read the diff, then run the command that exercises the change and read its
actual output. A passing checkpoint file is not evidence; executed output is.
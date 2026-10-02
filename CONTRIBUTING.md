# Contribution guide

## Ground rules

**1. Invariants are not negotiable.** The ten rules in `AGENTS.md` are defect
definitions, not style preferences. If a change requires breaking one, the change is
wrong — or the invariant needs an ADR and an independent review first.

**2. Never weaken an assertion to make a test pass.** Investigate and fix the cause. A
disabled test is worse than a missing one: it hides the defect and leaves the false
sense of coverage. This applies to tolerance as much as to `skip`.

**3. Missing measurement is `unavailable`, never `0`.**

**4. Evidence is executed output.** A checkpoint file says what was intended. A command
that ran, with its output, says what happened.

---

## Before you start

Load the project skill — it encodes the rules that are cheap to violate and expensive
to detect late:

```text
skill: niharamesh-invariants
```

Then read the relevant one of:

| Working on | Read |
|---|---|
| Coordination or safety | `docs/protocol/ZONE_PROTOCOL.md`, ADR 0002, 0003, 0005, 0006 |
| Planning or allocation | `docs/GLOSSARY.md` §5–7 |
| Simulator or physics | `docs/ARCHITECTURE.md` §2, `docs/GLOSSARY.md` §5 |
| Transport or persistence | `docs/SECURITY.md`, ADR 0009, 0011 |
| Telemetry, metrics, replay | `docs/BENCHMARKS.md`, ADR 0011 |
| Frontend | `docs/GLOSSARY.md`, the `frontend-design` and `vercel-react-best-practices` skills |
| Deployment or ROS 2 | `docs/EDGE.md` |

---

## Setup

```bash
pnpm bootstrap     # install deps, generate contracts, export scenarios
pnpm doctor        # verify the toolchain
```

---

## The engineering loop

```text
1. Inspect the repository and docs/CONTINUE.md
2. Choose one concrete, testable deliverable
3. Implement it
4. Run the checks and inspect actual behaviour
5. Diagnose failures at the root cause; rerun affected checks
6. Review the diff
7. Commit coherent work
8. Update docs/STATUS.md and continue
```

---

## Where things live

| Path | Owner |
|---|---|
| `src/niharamesh/domain/**` | Contracts. Changing a field is a schema change: bump `SCHEMA_VERSION`, regenerate, update consumers |
| `src/niharamesh/ports.py` | The authority seams. Changing these changes the architecture |
| `src/niharamesh/{simulator,safety}/**` | Physics, sensing, collision |
| `src/niharamesh/coordination/**` | Zone protocol. Safety-critical |
| `src/niharamesh/{planning,allocation}/**` | Local planning, auctions, custody |
| `src/niharamesh/{transport,persistence,telemetry}/**` | Peer messaging, durable stores, recording |
| `src/niharamesh/agent/**` | Per-robot runtime |
| `src/niharamesh/{api,evaluation,replay}/**` | Read models, metrics, reconstruction |
| `apps/web/**`, `e2e/**` | Cockpit and browser tests |
| `scenarios/**` | Authored library |
| `docs/**` | Documentation |

**Coordinate before touching a shared contract.** A change to `domain/**`, `ports.py`,
`pyproject.toml`, `package.json` or a lockfile requires a visible coordination message
and matching consumer updates in the same change. Never integrate two inconsistent
implementations of the same protocol because both reported success.

---

## Testing standards

### What a good test does

- Asserts **behaviour**, not implementation detail
- Fails when the behaviour breaks, for a reason a reader can follow
- Names the invariant it protects
- States its own limits: a bounded search says so

### Red flags

| Pattern | Why it is wrong |
|---|---|
| Asserting an agent's own `safe=True` | Tests the agent's belief, not the world |
| Screenshot-only verification | Establishes appearance, not behaviour |
| `pytest.skip` with no reason | Silent coverage loss |
| A test that re-implements the implementation | Passes when both are wrong in the same way |
| Tolerance widened to pass | The check stopped checking |
| Fixture data in a results chart | Looks like a measurement, is not one |
| Skipping a failing safety test | Defeats the purpose of the test |

### Required coverage for a protocol change

- **A regression test added before the fix.** Preserve the failing case.
- A bounded exhaustive interleaving check where transaction logic changed.
- An assertion on the *specific* rejection reason, not just "rejected".
- Re-run the consumer tests. A protocol change breaks callers.

### Test layers

| Suite | Scope | Marker |
|---|---|---|
| `tests/unit/` | Pure logic, domain boundaries | — |
| `tests/property/` | Hypothesis, invariants over generated inputs | — |
| `tests/protocol/` | Coordination state machines. **Independent of browser tests** | — |
| `tests/integration/` | Authority boundaries, process isolation, evaluation | — |
| `tests/network/` | Real localhost sockets, real processes | `network`, `timeout` |
| `tests/scenarios/` | Scenario library integrity | — |
| `tests/benchmarks/` | Metric computation and eligibility | `slow` |
| `e2e/` | Browser workflows | — |

Protocol tests stay independent of browser tests: a protocol bug must be findable
without a browser.

### Browser tests

Readiness is an **auto-retrying locator assertion** or `expect.poll`.

```ts
await expect(page.getByTestId("context-bar")).toBeVisible()
await expect(page.getByTestId("robot-inspector")).toContainText("amr-01")
```

**Never `waitForLoadState("networkidle")`** — Playwright's own documentation marks it
discouraged, and this app's continuous telemetry makes network idle structurally
unobservable, so waiting for it would hang until timeout rather than detect readiness.

When the API is unavailable, a test **skips with a stated reason** naming the command
that starts it. A skipped test always says why.

### Adversarial cases that must exist

| Case | Test |
|---|---|
| Deliberately unsafe controller | Must be caught by the evaluator — an evaluator that always reports zero must fail verification |
| Duplicate / reordered grant, cancel, release, task events | Final state identical to once, in order |
| Late grant after durable local cancellation | Must not revive the request |
| Split partial acquisition under simultaneous requests | Must resolve, never deadlock |
| Corrupt or missing journal | Stopped/unknown recovery; grants nothing |
| Thin obstacle crossed between integration samples | Detected |
| Opposing motion with clear endpoints | Detected |
| Timeout-based expiry on any occupancy | Must **not** free the aisle |

---

## Style

### Python

Python 3.12, `uv`, fully annotated, `mypy --strict` and `ruff` clean.

```bash
uv run ruff check src tests scripts
uv run mypy
```

- Lengths metres, angles radians, times integer nanoseconds with a `TimeDomain`
- No `print` in library code
- No bare `except`
- No wall-clock reads on the deterministic path
- Docstrings explain **why**, not what
- Files focused; split rather than exceed ~450 lines

### TypeScript

React 19, TypeScript **strict**, Vite, Tailwind v4, TanStack Query for server state,
Zustand only for local view state. PixiJS for the map, driven by its own ticker.

```bash
pnpm --filter @niharamesh/web exec tsc --noEmit
```

Keep high-frequency rendering **out of broad React reconciliation**. Clean up timers,
event listeners, socket subscriptions and renderer resources on unmount.

### Generated types

Never hand-edit `packages/contracts/generated/**` or
`src/niharamesh/contracts/schemas/**`. Regenerate:

```bash
uv run python scripts/generate_contracts.py
pnpm --filter @niharamesh/contracts generate
```

---

## Naming and copy

The three evidence categories must stay distinct in code, docs and UI:

| Category | Examples |
|---|---|
| **Configured assumption** | 0.4 m/s limit, 0.02 m localisation noise, 1.40 m aisle |
| **Implemented and verified** | A feature with an executed check |
| **Measured outcome** | A number from an exported artefact |

Phrase things the way `docs/GLOSSARY.md` §9 says to. In particular:

- "the robot's pose estimate is X, age A s" — not "the robot is at X"
- "a stop was **requested** at T; observed at T+Δ" — not "the robot stopped"
- "no collision was **observed**" — not "therefore safe"
- "no single-robot route exists at the declared clearance" — not "broken map"

---

## Committing

Only the integration owner stages shared-worktree changes. Explicit staging — never
blind `git add .`:

```bash
git add <specific reviewed paths>
git diff --cached --check
git diff --cached --stat
git commit -m "<specific coherent change>"
```

Never force-push, reset hard, clean unknown files, or bypass hooks. If Git identity
is missing, report it rather than inventing one.

Commit messages state **what changed and why**, and name the verification where it
exists.

---

## Safety-critical changes

A change to coordination, occupancy retention, the safety gate or freshness handling
requires:

1. A **regression test added before the fix**
2. An ADR entry, or a note in the relevant ADR's revisiting section
3. **Independent review** by someone who did not write it
4. Explicit statement of what liveness or throughput cost the change introduces

---

## Documentation obligations

| Change | Update |
|---|---|
| Any behaviour | `docs/STATUS.md` |
| Any new claim | `docs/evidence/CLAIM_EVIDENCE.md` |
| Anything newly unproven | `docs/KNOWN_LIMITATIONS.md` |
| Any protocol state or transition | `docs/protocol/ZONE_PROTOCOL.md` |
| Any new decision | `docs/adr/` |
| Any new metric | `docs/BENCHMARKS.md` |
| Any new command | `README.md`, `docs/API.md` |
| Anything blocking the next step | `docs/CONTINUE.md` |

If a claim cannot be evidenced, say it is unproven. That is a complete and acceptable
answer; a claim without evidence is not.
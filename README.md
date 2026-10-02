# NĪHĀRAMESH

**Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots in Smart Warehouses**

Team **NihāraNetra** · Team ID **148428** · Problem statement **SIH26123**

> NĪHĀRAMESH is a warehouse fleet-coordination **laboratory**: a deterministic and
> real-process warehouse world, three or more independently executing robot agent
> processes that exchange direct peer messages, a reviewed exclusive-zone
> coordination protocol, local planners and distributed task auctions, a local
> safety gate, and an operator cockpit that explains *why* the fleet behaves as it does.

The distinctive engineering focus is **freshness-aware coordination** — knowing whether
peer information is usable, retaining conservative physical occupancy during failures,
preventing conflicting motion authority, and making every important decision
inspectable and reproducible.

---

## Status

Read [`docs/STATUS.md`](docs/STATUS.md) for implemented / verified / blocked, and
[`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) for what is unresolved.

Three evidence categories are used consistently in this README, in the UI and in
every report:

| Category | Meaning |
|---|---|
| **Configured assumption** | A value we chose (robot size, speed limit, sensor noise, battery model, timing budget). Labelled as simulation configuration. |
| **Implemented and verified** | Code exists, checks were executed, evidence path recorded. |
| **Measured outcome** | A number from a specific run artifact with manifest, environment and trace. |

A zero observed collision count is **not** a universal collision-free proof.
The ≥20 % makespan-reduction figure is a **target**, reported only as a paired
measurement with eligibility rules and sample counts.

## Project dossier and updates

The living project dossier is an **external project reference**. It is not a runtime
dependency and not an automatically updating data feed:

**https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing**

Submission metadata as recorded by the team: category **Software**, theme
**Smart Automation**, sponsor **Bharat Electronics Limited**. Public mirrors differ
on the theme; see [`docs/RESEARCH.md`](docs/RESEARCH.md) for the recorded discrepancy.

## Prerequisites

| Tool | Tested version | Required? |
|---|---|---|
| Python (via `uv`) | 3.12.14 | yes |
| [uv](https://docs.astral.sh/uv/) | 0.12.7 | yes |
| Node.js | 24.13.0 (LTS line; ≥22.12 works) | yes |
| pnpm | 11.22.0 | yes |
| Git | 2.53 | yes |
| Docker | any recent | optional — a native path exists and is the tested one |
| ROS 2 | Jazzy / Ubuntu 24.04 (researched, see below) | optional |

No API key, cloud account or continuous internet connection is required after
dependency installation. No hosted fonts or CDN assets are used.

## Quick start

```bash
git clone <your local clone> niharamesh
cd niharamesh
pnpm bootstrap          # installs JS + Python deps and verifies the toolchain
pnpm doctor             # runtime self-check
pnpm dev                # API on http://127.0.0.1:8100 + cockpit on http://127.0.0.1:5173
```

Windows PowerShell works with the same commands. `scripts/*.mjs` are portable Node
scripts; there are no bash-only chains behind a cross-platform entry point.

## Three-minute demo path

```bash
pnpm demo
```

That single command: launches the world, starts three independent robot processes
over real localhost sockets, runs a three-way-intersection scenario to completion,
injects a coordination partition on one directed channel, shows the affected robot
enter degraded operation, then reports the measured metrics with the run evidence
path. Then open **http://127.0.0.1:5173** and:

1. **Operations** — watch the warehouse map; select a robot and read *why waiting*.
2. **Experiments** — open the paired baseline / candidate matrix.
3. **Replays** — open the exported run, jump to the first fault, step backwards.
4. **System** — `doctor` output: processes, endpoints, journals, schema, recording health.

## Command reference

| Command | Purpose |
|---|---|
| `pnpm bootstrap` | Install JS + Python dependencies, verify toolchain versions |
| `pnpm doctor` | Runtime self-check: processes, ports, journals, schema compatibility, recording health |
| `pnpm dev` | Native dev servers (API + web). No Docker required |
| `pnpm build` | Contract generation, typecheck, production web build |
| `pnpm check` | Ruff, mypy strict, tsc strict, contract validation |
| `pnpm test` | pytest (unit/property/protocol/integration) + vitest |
| `pnpm test:e2e` | Playwright browser workflows |
| `pnpm verify` | Full release verification path |
| `pnpm demo` | Guided three-robot run with fault injection |
| `pnpm benchmark:smoke` | Fast paired CI benchmark |
| `pnpm benchmark:full` | Full paired benchmark suite |

Python CLI (via `uv run`):

```text
nihara doctor                         runtime self-check
nihara run --scenario <file> --mode deterministic
nihara run --scenario <file> --mode processes
nihara benchmark --suite <file> --output <dir>
nihara replay --run <dir>
nihara report --run <dir>
nihara scenarios list|validate|show
nihara serve
nihara agent --robot <id> --scenario <file> --endpoint host:port
```

## Architecture in one picture

```text
                    ┌────────────────────────────────────────────┐
                    │  Application API  (FastAPI, :8100)         │
                    │  scenarios · runs · events · replay        │
                    │  read models · explicit command plane      │
                    │  NOT a planner. NOT a coordinator.        │
                    └───────────────▲────────────────────────────┘
                        telemetry   │   commands (labeled)
                    ┌───────────────┴────────────────────────────┐
                    │  Recorder / observer  (projections only)  │
                    └───────────────▲────────────────────────────┘
              events                │ events
   ┌────────────┬───────────┬───────┴───────┬──────────────┐
   │ robot AMR1 │ robot AMR2 │  robot AMR3   │  ...         │   separate OS
   │ planner    │ planner    │  planner      │              │   processes
   │ task agent │ task agent │  task agent   │              │
   │ coordinator│ coordinator│  coordinator  │              │
   │ SAFETY GATE│ SAFETY GATE│  SAFETY GATE  │              │
   └─────┬──────┴─────┬─────┴───────┬──────┴──────────────┘
         │  direct peer messages over framed TCP (fault layer in between)
         └──────────────┬─────────────┘
                        │ MotionCommand
                 ┌──────▼──────────────────────────────────────────┐
                 │ World / simulator process                      │
                 │ ground truth · integration · physics · sensors │
                 │ NO routing · NO auctions · NO grants ·         │
                 │ NO collision suppression                       │
                 └───────────────────────────────────────────────┘
```

Authority boundaries are enforced and independently tested. Stopping the dashboard
and the API does **not** stop the world or the robots — see
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the corresponding architecture test.

## Repository map

See [`AGENTS.md`](AGENTS.md) for the full table and the ten non-negotiable
engineering invariants that govern this codebase.

## Documentation

| Document | Contents |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Authority and failure boundaries |
| [`docs/GLOSSARY.md`](docs/GLOSSARY.md) | Domain terms, units, clock model |
| [`docs/protocol/ZONE_PROTOCOL.md`](docs/protocol/ZONE_PROTOCOL.md) | Protocol states, transitions, crash/recovery rules, progress argument |
| [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) | Methodology, eligibility, seeds, results, limitations |
| [`docs/SCENARIOS.md`](docs/SCENARIOS.md) | Scenario format, authoring and validation guide |
| [`docs/FAULTS.md`](docs/FAULTS.md) | Fault-injection guide with reproducible examples |
| [`docs/REPLAY.md`](docs/REPLAY.md) | Event format, replay semantics, evidence layout |
| [`docs/API.md`](docs/API.md) | API reference and command reference |
| [`docs/EDGE.md`](docs/EDGE.md) | Edge profiles, ROS 2 boundary, explicit verification status |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Threat model, local access, secret handling |
| [`docs/SKILLS.md`](docs/SKILLS.md) | Skill provenance and attribution |
| [`docs/DEMO.md`](docs/DEMO.md) | Demo script matching the actual final application |
| [`docs/RESEARCH.md`](docs/RESEARCH.md) | Primary sources, interpretation, attribution |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`docs/evidence/CLAIM_EVIDENCE.md`](docs/evidence/CLAIM_EVIDENCE.md) | Claim-to-evidence matrix |

## Safety and physical actuation

**Physical actuation is disabled by default** (`NIHARA_PHYSICAL_ACTUATION_ENABLED=false`).
Enabling it requires explicit configured devices, a controlled test area and operator
authorisation, and is refused outright while an unsafe research ablation flag is set.

No industrial safety certification is claimed. A general-purpose software collision
monitor is not a certified safety system.

## License

MIT for the project source. Third-party notices are in
[`docs/THIRD_PARTY.md`](docs/THIRD_PARTY.md); vendored skill packages retain their
upstream licenses.
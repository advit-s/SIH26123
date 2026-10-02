# Third-party notices

NĪHĀRAMESH is MIT licensed. This file records third-party components, what they are
used for, and their licenses. Nothing here is vendored into the source tree except
the skill packages listed in §4, which retain their upstream licenses.

---

## 1. Runtime dependencies

### Python (managed by `uv`, pinned in `uv.lock`)

| Package | Purpose | License |
|---|---|---|
| `pydantic` | Domain model validation, JSON Schema generation | MIT |
| `fastapi` | Application API, WebSocket stream | MIT |
| `uvicorn[standard]` | ASGI server | BSD-3-Clause |
| `starlette` | ASGI primitives (via FastAPI) | BSD-3-Clause |
| `numpy` | Vectorised geometry and numeric work | BSD-3-Clause |
| `jsonschema` | JSON Schema validation of fixtures and imports | MIT |
| `typing-extensions`, `typing-inspection` | Typing support (transitive) | Python-2.0 / PSF |

### Development only

| Package | Purpose | License |
|---|---|---|
| `pytest` | Test runner | MIT |
| `pytest-asyncio` | Async test support | Apache-2.0 |
| `pytest-timeout` | Test timeouts | MIT |
| `hypothesis` | Property-based and stateful tests | MPL-2.0 |
| `ruff` | Linter and formatter | MIT |
| `mypy` | Static type checking | MIT |
| `hatchling` | Build backend | MIT |

> **Note on `hypothesis`:** MPL-2.0 is a weak-copyleft licence. It applies to the
> library, not to code that merely *uses* it. No Hypothesis source is vendored or
> modified here.

### Node (managed by `pnpm`, pinned in `pnpm-lock.yaml`)

| Package | Purpose | License |
|---|---|---|
| `react`, `react-dom` | UI runtime | MIT |
| `typescript` | Type system | Apache-2.0 |
| `vite` | Dev server and bundler | MIT |
| `@tailwindcss/vite`, `tailwindcss` | Styling (Tailwind v4) | MIT |
| `@pixi/react`, `pixi.js` | WebGL map renderer | MIT |
| `@tanstack/react-query` | Server state | MIT |
| `zustand` | Local view state | MIT |
| `@radix-ui/*` | Accessible headless primitives | MIT |
| `lucide-react` | Icons | ISC |
| `json-schema-to-typescript` | TS type generation from JSON Schema | MIT |
| `@playwright/test` | Browser workflow testing | Apache-2.0 |
| Time-series charting library | Chart rendering | MIT (see `apps/web/package.json`) |

---

## 2. Standard library only for core logic

Deliberate constraints, recorded because they are unusual and therefore worth
justifying:

- **Framing and codec:** `asyncio`, `struct`-equivalent manual packing, `json`.
- **Persistence:** stdlib `sqlite3` — no ORM.
- **Geometry:** `math` plus `numpy` where vectorisation genuinely helps. **No
  Shapely, no GEOS, no OpenCV.** The geometry here is small, exact and
  safety-critical; a general-purpose geometry library would add a dependency whose
  numerical conventions would then need auditing.
- **Planning:** hand-written A* over a validated occupancy grid — transparent and
  inspectable, as the brief requires.

---

## 3. External documentation referenced (not redistributed)

Consulted for technical decisions; no text or code is vendored. Full register with
retrieval status in `research/sources.json` and `docs/RESEARCH.md`.

| Source | URL | Use |
|---|---|---|
| OpenCode v2 docs | https://opencode.ai/v2/docs/config/ | Configuration schema validation |
| Playwright assertions | https://playwright.dev/docs/test-assertions | Readiness conditions; `networkidle` discouraged |
| uv projects/workspaces | https://docs.astral.sh/uv/concepts/projects/workspaces/ | Dependency management |
| PixiJS ticker | https://pixijs.com/8.x/guides/components/ticker | Render loop separation from React |
| ROS 2 REP-2000 | https://github.com/ros-infrastructure/rep/blob/master/rep-2000.rst | Platform/target pinning |
| ROS 2 QoS settings | https://github.com/ros2/ros2_documentation | Profile selection |
| Nav2 Collision Monitor | https://docs.nav2.org/rolling/ | Monitor structure (concepts only) |
| SIH official portal | https://sih.gov.in/ | Submission metadata cross-check |
| SIH26123 dossier | https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/ | Project reference — **inaccessible** at time of research; recorded as such |
| Moving AI MAPF benchmarks | https://www.movingai.com/benchmarks/mapf.html | Reviewed with attribution; **not used as-is** (start/goal ≠ pickup-delivery) |
| SIPP (ICRA 2011) | https://sbpl.github.io/publications/sipp-icra11/ | Temporal planning assumptions |
| PIBT / PIBT2 | https://kei18.github.io/pibt2/ | Decentralised coordination context |
| Temporary priority research | https://arxiv.org/abs/2205.12504 | Priority-based MAPF limits |

---

## 4. Vendored skill packages

Installed project-locally under `.agents/skills/` by the official skills CLI. Used
**by reference only**; no instruction text is copied into NĪHĀRAMESH's source.
Provenance, content hashes, licenses and usage evidence: `docs/SKILLS.md`.

| Skill | Source | License |
|---|---|---|
| `frontend-design` | `anthropics/skills` | See `LICENSE.txt` in the skill directory |
| `webapp-testing` | `anthropics/skills` | See `LICENSE.txt` |
| `vercel-react-best-practices` | `vercel-labs/agent-skills` | Upstream repository |
| `writing-plans` | `obra/superpowers` | Upstream repository |
| `systematic-debugging` | `obra/superpowers` | Upstream repository |
| `verification-before-completion` | `obra/superpowers` | Upstream repository |

`niharamesh-invariants` (`.opencode/skills/`) is original work, MIT, authored for
this repository.

---

## 5. Not used

Recorded so their absence is a decision rather than an oversight. Each was
considered and rejected for a stated reason:

| Not used | Reason |
|---|---|
| Shapely / GEOS | Unnecessary dependency for small exact 2D geometry; its numerical conventions would need auditing in safety-critical paths |
| PyTorch / scikit-learn | No learned component is shipped. Shipping an untrained model described as working is worse than not shipping one |
| ROS 2 Python packages | Not required for the demonstration; the bridge boundary is unit-tested with fixtures instead |
| Kafka / Redis / Celery | A coordination *broker* would contradict the decentralisation claim |
| Kubernetes | Absent requirement; adds operational surface without adding function |
| Any paid LLM API | Must not be in the safety path, and none is needed |
| Docker at runtime | Optional path only; the native launcher is the tested one |
| Any chart/plotting fixture data in the UI | Example data must not appear as measured performance |

---

## 6. Licenses of authored assets

| Asset | License |
|---|---|
| `src/**`, `apps/**`, `tests/**`, `e2e/**`, `scenarios/**`, `scripts/**` | MIT |
| `docs/**` | MIT |
| `.agents/skills/**` | **Upstream licenses — see `docs/SKILLS.md`** |
| `.opencode/skills/**` | MIT (original work) |

No credentials, no vendored binaries, no generated artefacts under `var/` are
committed. Scenario JSON under `scenarios/` is authored content and is committed;
run artefacts are regenerable and are gitignored.
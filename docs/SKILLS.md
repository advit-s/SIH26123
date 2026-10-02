# Skill provenance and attribution

Dated: 2026-10-02. Skills are installed **project-locally** under
`.agents/skills/`, which is a documented OpenCode *project compatibility*
discovery path. They are not installed globally, and no user-level or provider
setting was modified.

## How they were installed

The vetted set was installed with the official skills CLI in copy mode so the
files live in the repository and can be reviewed:

```bash
npx skills add anthropics/skills   --skill frontend-design --skill webapp-testing --agent opencode --copy --yes
npx skills add vercel-labs/agent-skills --skill vercel-react-best-practices --agent opencode --copy --yes
npx skills add obra/superpowers --skill writing-plans --skill systematic-debugging \
                                --skill verification-before-completion --agent opencode --copy --yes
npx skills list --agent opencode
```

The resolved set is recorded with content hashes in `skills-lock.json` at the
repository root. **No recursive dependency tree was installed** and no skill pack
was added unreviewed. Before installing, the upstream instructions and the scripts
they reference were inspected; the only script in the set is
`webapp-testing/scripts/with_server.py`, which was read before use.

## Installed skills

| Skill | ID | Source repo | Upstream path | Hash (sha256, first 16) | License | Intended use in this project |
|---|---|---|---|---|---|---|
| frontend-design | `frontend-design` | `anthropics/skills` | `skills/frontend-design/SKILL.md` | `106acf230014cbb4` | see `LICENSE.txt` in the skill dir | Visual direction for the operator cockpit: a distinctive industrial application, not a generic dashboard |
| webapp-testing | `webapp-testing` | `anthropics/skills` | `skills/webapp-testing/SKILL.md` | `3f14af7f56906952` | see `LICENSE.txt` | Real browser workflow verification with Playwright |
| vercel-react-best-practices | `vercel-react-best-practices` | `vercel-labs/agent-skills` | `skills/react-best-practices/SKILL.md` | `6b526d013e280732` | upstream repo | React performance and state-management discipline |
| writing-plans | `writing-plans` | `obra/superpowers` | `skills/writing-plans/SKILL.md` | `c2647b5bf067be35` | upstream repo | Implementable tasks with acceptance criteria |
| systematic-debugging | `systematic-debugging` | `obra/superpowers` | `skills/systematic-debugging/SKILL.md` | `3589907ee34dc8b1` | upstream repo | Root-cause diagnosis instead of symptom patching |
| verification-before-completion | `verification-before-completion` | `obra/superpowers` | `skills/verification-before-completion/SKILL.md` | `b529822bdac4b197` | upstream repo | Fresh execution evidence before any completion claim |

`vercel-react-best-practices` ships an `AGENTS.md` and a `rules/` directory; both
are vendored unmodified. Its OpenCode skill ID is the path-derived
`vercel-react-best-practices`, not the frontmatter `name`.

## Project-local skill authored for this repository

| Skill | Path | Purpose |
|---|---|---|
| `niharamesh-invariants` | `.opencode/skills/niharamesh-invariants/SKILL.md` | Preserves the rules that are cheap to violate and expensive to detect late: authority boundaries, clock domains, conservative occupancy, the zone protocol's ordering rules, the three evidence categories, and the exact verification commands. |

It **points at** `AGENTS.md`, `docs/protocol/ZONE_PROTOCOL.md`,
`docs/GLOSSARY.md` and `docs/evidence/CLAIM_EVIDENCE.md` rather than restating them,
so it cannot drift out of date relative to the code it describes. It was written
after the protocol, time model and verification commands existed, as required.

Exactly one project-local skill was created. Deliberately no decorative skill set.

## Discovery paths, and why there are no duplicates

OpenCode 2.0.22 searches, in precedence order:

1. `~/.config/opencode/skills` (global)
2. `.claude/skills`, `~/.agents/skills` (global compatibility)
3. `.agents/skills` — project compatibility ← **the vetted set lives here**
4. `~/.config/opencode/skills` — project
5. `.opencode/skills` — project ← **only `niharamesh-invariants`**

The same skill is **not** duplicated across paths: each of the six vetted skills
exists in exactly one location, so no duplicate identity is created. The project
skill lives in `.opencode/skills/` because it is ours and higher precedence is
convenient, not because the vetted skills were copied there.

## Usage: installed is not the same as used

Installing a skill does not constitute using it. Record of actual use in this
build:

| Skill | Used for | Evidence |
|---|---|---|
| `systematic-debugging` | Diagnosing 8 distinct defects during integration rather than patching symptoms | Phase 1–4 entries in `docs/CONTINUE.md`; each has a root cause, not just a fix |
| `verification-before-completion` | Refusing completion claims on unexecuted output; fixed two tests whose assertions were weaker than the claim | `docs/CONTINUE.md` items 2, 3, 6 |
| `writing-plans` | `docs/PLAN.md` with owners, dependencies and acceptance checks | `docs/PLAN.md` |
| `frontend-design` | Operator cockpit visual direction | `apps/web/` (frontend workstream) |
| `vercel-react-best-practices` | Keeping high-frequency map rendering out of React reconciliation | `apps/web/` (frontend workstream) |
| `webapp-testing` | Playwright readiness by locator assertion | `e2e/`, `playwright.config.ts` |

## Where a skill conflicts with this brief

The brief overrides the skill in one specific case, and the override is recorded
here rather than silently applied.

`webapp-testing` documents generic readiness patterns. **This project's brief
requires that `networkidle` not be used**, because the cockpit has continuous
telemetry: with telemetry flowing, network idle is structurally unobservable, so
waiting for it would hang until timeout rather than detect readiness. Independent
research (`docs/RESEARCH.md`) confirms Playwright's own documentation marks
`networkidle` as **discouraged** and advises relying on web assertions instead.
Readiness in `e2e/` is therefore an auto-retrying locator assertion or
`expect.poll`, plus an explicit API probe that **skips with a stated reason**
naming the command to start the API when it is unreachable. A skipped test always
says why; it never silently passes.

## Attribution

All six upstream skills are used by **reference only**. No upstream instruction
text or vendor code has been copied into NĪHĀRAMESH's own source; the vendored
directories retain their upstream licenses (`LICENSE.txt` where present). Upstream
repositories remain the property of their authors, per their licenses.

Third-party runtime dependencies are enumerated in `docs/THIRD_PARTY.md`.
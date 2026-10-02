# `research/`

Evidence base for NĪHĀRAMESH technical claims.

## Contents

| File | Purpose |
|---|---|
| `sources.json` | Machine-readable register: one object per source with `id`, `title`, `url`, `source_type`, `publisher`, `accessed` (ISO date), `retrieved` (`true`/`false`), `note`. Sorted by `id`. |
| `../docs/RESEARCH.md` | The prose register: per-area Sources / Findings / Design consequence / Caveats, plus attribution, "what could not be retrieved", and open questions. |

## How to regenerate

`docs/RESEARCH.md` and `sources.json` are hand-curated, not generated. To refresh:

1. Re-fetch every URL in `sources.json` (all were accessed `2026-10-02`).
2. Re-verify the volatile facts in particular: ROS 2 distro support windows (REP 2000), Raspberry Pi
   hardware SKUs, and SIH portal problem-statement rows.
3. Update `accessed` per entry; set `retrieved: false` and write the exact HTTP outcome in `note` for anything
   that no longer resolves (403/404/login wall/PDF/ZIP).
4. Move any claim that lost its source into `docs/RESEARCH.md`'s "What could not be retrieved" section.
5. Keep the two files consistent. Never cite a `retrieved: false` entry for content.

Validate the register with:

```powershell
python -c "import json,pathlib; d=json.loads(pathlib.Path('research/sources.json').read_text(encoding='utf-8')); print('sources:', len(d)); assert all('url' in s and 'retrieved' in s for s in d); print('OK')"
```

## Caveat: retrieval status is dated

`retrieved: true|false` records what happened on the access date, not a permanent property. URLs rot,
distros reach end of support, PS rows get revised. Before any external review or publication, re-check that
the cited URL still says what `docs/RESEARCH.md` claims it says.

## Rules for this directory

- Paraphrase and cite. Never vendor full text, PDFs, archives, or third-party source code.
- Claims that came from background knowledge rather than a fetched page must carry an `unverified:` marker in
  `docs/RESEARCH.md`.
- Distinguish **configured assumption** / **implemented + verified** / **measured outcome**. A
  `retrieved: false` source is a gap, not a licence to paraphrase from memory.
- Owned by the RESEARCH workstream. The integration owner stages and commits.
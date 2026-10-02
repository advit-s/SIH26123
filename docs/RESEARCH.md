# Research register

**Project:** NĪHĀRAMESH — freshness-aware distributed fleet-coordination laboratory for warehouse AMRs
**Problem:** SIH26123 — Edge-AI Based Distributed Fleet Coordination for Autonomous Mobile Robots (AMRs) in Smart Warehouses
**Team:** NihāraNetra (Team ID 148428)
**Workstream:** RESEARCH (evidence base for implementation and docs)

## Access metadata

- **Access date for every URL in this document:** `2026-10-02`
- **Tool:** `webfetch` (HTTP GET, rendered to markdown/text). Crossref and arXiv metadata were queried through
  their public REST endpoints with the same tool.
- **Retrieval status per source:** `research/sources.json` (machine-readable) — each entry carries
  `retrieved: true|false` plus a `note`. This document and that file must always be read together.
- **Access-date caveat:** retrieval status is a fact about `2026-10-02`, not a permanent property. ROS distro
  support windows, Pi hardware SKUs, and doc pages all move. Re-verify before any external claim.

## What could not be retrieved

Nothing in this register is cited from memory alone unless it carries an explicit `unverified:` marker.
The following retrieval attempts **failed** and are recorded so that no downstream document can imply we
read them.

| Target | URL | Observed HTTP outcome | Consequence |
|---|---|---|---|
| Living project dossier (Google Doc) | `https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing` | `200` with body containing only: title `SIH26123 - Google Docs`, the string `This browser version is no longer supported. Please upgrade to a supported browser.`, and `Sign in`. **Zero dossier content.** | **inaccessible.** We did not read the dossier. No claim anywhere in our docs may be attributed to it. We did not attempt to change sharing or sign in. |
| Raspberry Pi 5 product page | `https://www.raspberrypi.com/products/raspberry-pi-5/` | **`403`** | Fallback used: the official Raspberry Pi *documentation* site (`raspberrypi.com/documentation`), which **is** reachable. CPU core count / instruction-set claims for Pi 5 are therefore `unverified:` (see Edge hardware). |
| Pi 5 product brief PDF | `https://datasheets.raspberrypi.com/raspberry-pi-5-product-brief.pdf` | **`404`** | Not used. |
| SIPP paper full text (PDF) | `https://www.cs.cmu.edu/~maxim/files/sipp_icra11.pdf` | content type `application/pdf` — our fetcher cannot render PDFs | SIPP assumptions are therefore cited from *other retrievable primary sources* about SIPP (arXiv:2302.00776, arXiv:1906.06911), not from the ICRA-11 paper itself. Marked `unverified:` where we state SIPP's own text. |
| "Surplus auction" primary source | arXiv API `all:"surplus auction" AND all:"multi-robot"`, `all:"surplus-based auction"`, `abs:"surplus" AND abs:"auction" AND abs:"robot"` | **0 results** in all three queries | **No primary source found.** All surplus-auction statements below are `unverified:` and must not be presented as cited claims. The capacity-reservation argument is instead grounded in CBAA/CBBA, which we did retrieve. |
| CBAA/CBBA full text | `https://doi.org/10.1109/tro.2009.2022423` | not fetched (paywall) | We retrieved the MIT DSpace record and abstract only. Any claim about CBBA's internal bid/reservation mechanism beyond that abstract is `unverified:`. |
| Moving AI benchmark archives | `*.map.zip`, `*.map-scen-even.zip` | content type `application/zip` — not renderable | Dataset *inventory* was read from the index page; file *contents* were not downloaded. `.map` / `.scen` grammar is cited from the official format page, which we did retrieve. |
| arXiv:1705.07105 (guessed ID) | — | retrieved, but **irrelevant** (an OBDA database-theory paper) | Discarded. Recorded here so nobody re-cites it as an auction source. |

`websearch` was unavailable for the whole session (`Web search cancelled` on every call); every finding below
therefore rests on directly-fetched URLs, and the one thing we could not source (surplus auction) is
explicitly marked rather than filled in.

---

## Project metadata cross-check (SIH26123)

### Sources

- `https://sih.gov.in/sih2026PS` — official portal, SIH 2026 problem statement table — **official site** — accessed `2026-10-02`
- `https://sih.gov.in/` — official portal home (theme list, participating organisations) — **official site** — accessed `2026-10-02`
- `https://sih2026-ps-viewer.vercel.app/ps/SIH26123` — secondary mirror — **secondary** — accessed `2026-10-02`
- `https://docs.google.com/document/d/1o9qfFzLK0UZBnQ1RRXQq-H4fyKzqRv5UmukPL9Q8nII/edit?usp=sharing` — project dossier — **dossier** — accessed `2026-10-02` — **inaccessible**

### Findings

The team recorded: **Problem** SIH26123 · **Category** Software · **Theme** Smart Automation · **Sponsor**
Bharat Electronics Limited. Cross-check result:

- **Official portal** (`sih.gov.in/sih2026PS`, row 123) states, verbatim from the retrieved page:
  `Organization Bharat Electronics Limited | Department Bharat Electronics Limited | Category Software |
  Theme Smart Automation`, PS ID `26123`, title *"Edge-AI Based Distributed Fleet Coordination for
  Autonomous Mobile Robots (AMRs) in Smart Warehouses"`, PS number `SIH26123`, idea-submission deadline
  `5 October 2026`. **All three recorded fields agree.** No disagreement found.
- **Secondary mirror** (`sih2026-ps-viewer.vercel.app`) renders the same row as
  `SIH26123 · Software · Edge-AI Based Distributed Fleet Coordination … · Bharat Electronics Limited ·
  Smart Automation`, and its facet counts place SIH26123 in a set of 5 BEL statements across a 260-statement
  corpus. **Also agrees.** The mirror does **not** expose a Category/Theme facet, so the mirror independently
  corroborates only *Software* + *organisation*; *Smart Automation* is corroborated by the official portal only.
- **Corroborating context from the portal home page:** `BHARAT ELECTRONICS LIMITED` appears in the list of
  participating Central ministries/departments/PSUs, and *Smart Automation* appears as a defined SIH theme.
- **The problem statement text itself names edge hardware**, which matters for our deployment claims:
  *"must run locally on edge hardware (e.g., Raspberry Pi or Jetson Nano onboard each robot)"*, and requires
  *"a peer-to-peer communication protocol where robots share localization data locally"*, *"Implementation of
  algorithms for edge hardware"*, and *"a lightweight monitoring UI that visualizes the entire fleet's
  real-time positions and battery status"*.
- **The 20% figure is a success criterion written by the organiser, not an outcome we produced.** The official
  page states: *"Success Criteria: Zero inter-robot collisions and a minimum 20% reduction in total task
  completion time compared to traditional stop-and-wait methods when handling overlapping paths."*
  This is the exact basis for our rule that 20% is a **target**, never a claimed measurement.

### Design consequence for NĪHĀRAMESH

- Keep the recorded metadata, and cite the official portal row as its source in `AGENTS.md`/docs.
- Label the 20% makespan reduction as **organiser-defined target** in every artifact that mentions it.
- Label the Raspberry Pi profile as **organiser-suggested hardware**, and — because we hold no Pi — as
  **specification only, untested** (see Edge hardware).
- Record the fleet size requirement *"at least 3 AMRs"* as a minimum, not a benchmark scale.

### Caveats

- The dossier is inaccessible, so anything the team wrote in it is **not** verifiable from here. If the
  dossier and the official portal ever disagree, the official portal wins and the disagreement is logged.
- The secondary mirror is a third-party Vercel deployment with no stated provenance or update policy
  (`data captured 2026-10-02` on its own page). Treat it as corroboration only, never as authority.
- The official PS list is rendered client-side; our fetch captured rows 1–13 *and* row 123 (SIH26123) in the
  same document, but we did **not** exhaustively verify every row. We verified the one row we care about.

---

## Multi-robot coordination / MAPF

### Sources

- `https://kei18.github.io/pibt2/` — PIBT/PIBT2 project page (AIJ journal version + repository) — **official site** — accessed `2026-10-02`
- `https://doi.org/10.1016/j.artint.2022.103752` — Okumura, Machida, Défago, Tamura, *Priority Inheritance with Backtracking for Iterative Multi-agent Path Finding*, Artificial Intelligence 298:103752 — **paper** — not retrieved
- `https://arxiv.org/abs/2205.12504` — Fujitani, Yamauchi, Miyashita, Sugawara, *Deadlock-Free Method for Multi-Agent Pickup and Delivery Problem Using Priority Inheritance with Temporary Priority*, KES 2022 — **paper** — accessed `2026-10-02`

### Findings

**PIBT / PIBT2 (from the project page, which we did retrieve).**

- MAPF is defined on a **graph**: agents must reach "their own respective destinations". For warehouse-scale
  fleets it must be solved "iteratively online on a lifelong basis", so offline compute-intensive optimal
  methods are ruled out; the target is scalable **sub-optimal, predictable-computation-time** behaviour.
- Decision procedure: "the agents, in descending order of priority, decide their next neighboring locations
  in the next timestep through communications only with the local agents."
- **The liveness guarantee is explicitly graph-conditional:** *"We prove that, regardless of their number, all
  agents are guaranteed to reach their destination within a finite time when the environment is a graph such
  that all pairs of adjacent nodes belong to a simple cycle (e.g., biconnected)."* That is, **PIBT's
  completion guarantee requires a biconnected map.** Dead-end aisles (shelf faces, loading docks) violate it.
- The algorithm is described as *"an adaptive prioritization scheme"* with *"backtracking"* — a robot that
  cannot progress yields to a higher-priority neighbour and retries later.
- Reported scale: hundreds of agents, *"acceptable solutions immediately"*; PIBT was *"used as a core of the
  winning strategy in the first MAPF competition (2023), among 825 submissions"*.
- Journal-version caveat recorded by the authors: PIBT2 *"substantially updated from the original repo of the
  conference paper (IJCAI-19)"* and is *"much faster"*; and an erratum: the introduction mislabels `Δ(G)` as
  a *diameter* when it is the **maximum degree**. (We cite AIJ/journal metadata from the project page; the
  PDF itself is paywalled, so detailed algorithmic statements are `unverified:` at line level.)

**Temporary priority / priority inheritance (from arXiv:2205.12504, retrieved).**

- Direct statement of PIBT's limitation: *"PIBT is only applicable to environments that are modeled as a
  bi-connected area, and if it contains dead-ends, such as tree-shaped paths, PIBT may cause deadlocks."*
- The fix is **temporary priority + restricted movement in trees**: agents are allowed temporary priorities,
  and their movements inside tree-shaped branches are constrained. The paper claims *"agents can always reach
  their delivery without deadlock"*, and benchmarks against the **token passing** baseline.
- The motivating domain statement is directly ours: *"in the real-world environment, there are many dead-end
  paths to locations such as the shelves where materials are stored as well as loading/unloading locations to
  transportation trucks."*

**"Priority inheritance" assessed as a mechanism.** A waiting robot at a constrained passage temporarily
raises the priority of the robot blocking it, so the blocker yields first. This is a *per-step, local,
in-timestep* reordering of decision authority — it is **not** a mutual-exclusion reservation. It buys
liveness cheaply and re-decides every tick; it buys **no** protection against two robots independently
believing they may enter the same restricted space between ticks. In PIBT the collision-freedom argument is
structural (each timestep is resolved in a single globally consistent priority order, and backtracking
retracts invalid choices), not a lock. `unverified:` at algorithm-line level because the papers' full text
is not retrievable here.

**Our planned protocol, stated precisely.** Canonical sequential acquisition: every requester acquires every
voter — **including its own local voter** — in one globally agreed order; a robot holds **at most one
outstanding grant globally**; no pre-reservation of your own grant.

*Safety (mutual exclusion) argument, given the protocol's preconditions.*

1. Let the grant order `<` be a single total order over voters, identical at every requester (identical
   order ⇒ no order inversion ⇒ no distributed deadlock by cycle).
2. A requester may declare a grant only after holding an explicit grant token from every voter `<` itself,
   so it cannot enter the critical section early.
3. When a voter grants to requester `x`, it records `(epoch, x)` and thereafter **refuses** all other
   requesters at the same or earlier voter position until it receives an explicit release from `x` (or a
   conservative expiry of *permission to assume*, never of occupancy — see AGENTS.md rule 4).
4. Because only one requester can hold the last voter at a time, and the earlier voters are monotonic, at
   most one requester is inside the critical section at any instant. Two robots cannot both be granted.
5. Including the requester's own voter in the order removes the "self-pre-reserved grant" case, which is the
   classic source of two-grants-per-robot splits.

*What this argument does **not** give us.* It is a mutual-exclusion argument only. It says nothing about
progress. Liveness additionally requires: every critical-section holder eventually releases; every robot
eventually acquires all voters; and **no robot holds one outstanding grant while blocking a robot that needs
a different grant** — which is precisely the situation canonical-order + single-outstanding-grant *can*
create. See Caveats.

### Design consequence for NĪHĀRAMESH

- **Keep** canonical sequential acquisition with an identical global voter order, self-vote included, and at
  most one outstanding grant. It is defensible, reviewable, and gives a short, checkable safety story.
- **Do not claim it is deadlock-free in availability terms.** It is *order-inversion-free by construction*
  (a strictly global order removes the circular-wait class) and *mutual-exclusive by construction*, but
  **blocking is still possible**: robot A holds zone Z's grant while physically sitting in the aisle that
  robot B needs in order to release a different zone. We will document this as a **bounded-but-unbounded-in-
  theory availability cost**, and measure it (grant wait-time distribution per zone) rather than assert it.
- **Do not claim PIBT-style deadlock-freedom on our maps.** Our warehouse maps contain dead ends by
  construction. If we claim liveness, we must either restrict the claim to biconnected regions or adopt a
  temporary-priority mechanism, which we have not validated.
- **Do not implement priority inheritance as a substitute for the grant protocol.** It is a *within-tick
  yielding* device. Using it to relax exclusive-zone safety would violate our own AGENTS.md rule 7 (safety
  gate) and rule 1 (authority boundaries). If we implement anything PIBT-derived, it belongs to the local
  planner / deadlock *recovery* path only, and only under the safety gate.
- **Name the mechanism honestly in docs and code**: `canonical sequential zone acquisition`, not "PIBT" and
  not "priority inheritance".

### Caveats

- The liveness theorem is **conditional on biconnectivity**; our maps violate it. Any reviewer asking "is it
  deadlock-free?" must be answered "no, and here is the condition under which it would be".
- Canonical-order acquisition costs **O(#voters) round-trips per grant**. With one global order and a
  robot-local voter, that is a linear message chain — acceptable at 3 robots, and this must be *measured*
  before scaling claims are made.
- Single-outstanding-grant is a real throughput cap: a robot that wants two overlapping zones must fully
  acquire-and-release one before starting the other.
- `unverified:` — detailed PIBT pseudocode, priority-update thresholds, and the exact biconnectivity
  condition wording; both papers' full texts were not retrievable through this tool.

---

## Distributed task allocation

### Sources

- `https://dspace.mit.edu/entities/publication/b0bf0a05-be3b-433b-9f4b-ce314ed5178b` — Choi, Brunet, How, *Consensus-Based Decentralized Auctions for Robust Task Allocation*, IEEE T-RO 25(4):912–926, June 2009 (MIT Open Access record + abstract) — **paper** — accessed `2026-10-02`
- `https://doi.org/10.1109/tro.2009.2022423` — DOI of the published version — **paper** — not retrieved

### Findings

From the retrieved MIT DSpace record and abstract:

- CBBA is the generalisation to the multi-assignment problem of **CBAA** (consensus-based auction algorithm).
  Both *"utilize a market-based decision strategy as the mechanism for decentralized task selection"* and
  *"use a consensus routine based on local communication as the conflict resolution mechanism to achieve
  agreement on the winning bid values."*
- **Conflict-freedom is claimed, not merely hoped for:** *"Under reasonable assumptions on the scoring
  scheme, both of the proposed algorithms are proven to guarantee convergence to a conflict-free assignment"*
  and *"exhibit provable worst-case performance."*
- **Robustness claim is about messages and topology, not about safety:** CBAA/CBBA produce
  *"conflict-free feasible solutions that are robust to both inconsistencies in the situational awareness
  across the fleet and variations in the communication network topology."*
- Persistent handle `http://hdl.handle.net/1721.1/52330`; the record is flagged *"made available in
  accordance with the publisher's policy"*, so redistribution terms differ from the paper's own licence.

**How the "reserve capacity while a bid is live" idea is avoided.** The mechanism the retrieved abstract
supports is: an agent's *bid* is the vehicle of intent; the **consensus routine decides the winner per
task**, and an agent's bid is replaced only when the agent loses. Two robots cannot both "win" a task
because winning is a *fleet-wide converged function of the bid values*, not a local decision — the local
decision only ever *proposes*. `unverified:` the exact invariant (the "bid-validity / epoch" update rule),
because the full text is paywalled.

**Is "reserve capacity while a bid is live" sound?** Partially. It is sound *as a capacity-accounting
discipline*: while an agent's bid on task `j` is live, the agent must not spend the capacity that bid
consumes on another task, or the bid becomes unbackable and the consensus outcome can be infeasible for the
winner. It is **not** sound as a *safety* mechanism: reserving capacity says nothing about physical
coexistence in a shared aisle. We must keep the two arguments separate in docs — capacity reservation
protects assignment feasibility; our zone grants protect physical exclusion.

**`unverified:` — surplus auction.** We could not retrieve any primary source (three arXiv API queries
returned 0 results; Crossref title search returned only unrelated economics papers). Any statement about a
"surplus auction" protocol, its surplus computation, or its conflict-avoidance argument is **not** cited
and must not appear in our docs as fact. If we want it, someone must obtain the paper by another route.

### Design consequence for NĪHĀRAMESH

- **Keep** a market/bid layer for task allocation (it matches the organiser's "task allocation & re-routing"
  requirement and the CBAA family), but implement it so that **winning is a converged, observed outcome,
  never a local decision** — mirroring CBAA's division of labour between propose and resolve.
- **Reserve capacity for a live bid**, and document it as protecting *assignment feasibility*, never as
  *collision safety*. Collision safety is exclusively the zone-grant protocol's job (AGENTS.md rule 7).
- **Do not silently resolve the surplus-auction gap.** Either obtain the paper or omit the family. We will
  omit it from all docs and record it as an open question.
- Cite CBAA/CBBA with the MIT handle, and note that our implementation is *inspired by*, not derived from,
  their algorithm — no code is vendored.

### Caveats

- CBAA/CBBA convergence is proved *"under reasonable assumptions on the scoring scheme"*. Our scoring function
  (distance + freshness + battery) must be checked against those assumptions or the proof does not apply to
  us. `unverified:` what "reasonable" requires.
- The MIT record notes the article is made available under the publisher's policy — check terms before
  quoting at length.
- No primary source for the surplus-auction family (see above).

---

## Spatial-temporal planning (SIPP)

### Sources

- `https://sbpl.github.io/publications/sipp-icra11/` — SIPP publication page, ICRA 2011, Phillips & Likhachev — **official site** — accessed `2026-10-02`
- `https://www.cs.cmu.edu/~maxim/files/sipp_icra11.pdf` — SIPP full text — **paper** — **not retrieved** (PDF)
- `https://arxiv.org/abs/2302.00776` — Ali & Yakovlev, *Safe Interval Path Planning With Kinodynamic Constraints* — **paper** — accessed `2026-10-02`
- `https://arxiv.org/abs/1906.06911` — Yakovlev, Andreychuk, Belinskaya, Makarov, *Combining Safe Interval Path Planning and Constrained Path Following Control* — **paper** — accessed `2026-10-02`
- `https://sbpl.github.io/software/` — SBPL software page (SIPP is part of SBPL) — **official site** — accessed `2026-10-02`

### Findings

- SIPP = **Safe Interval Path Planning**, ICRA 2011, Mike Phillips & Maxim Likhachev (CMU Robotics Institute /
  Search-Based Planning Lab). Retrieved publication page confirms venue, authors and the PDF link.
- SBPL *"Implements ARA*, AD*, Anytime D*, R*, weighted A*, SIPP, Experience Graphs, and lattice-based
  planners"* — SIPP is the temporal-robustness member of the SBPL family, grouped under
  *"Navigation in Dynamic Environments (SIPP)"*. No vendor code is vendored into our repo.
- **The load-bearing assumption, from a retrievable primary source (arXiv:2302.00776):** *"Original SIPP
  algorithm relies on the assumption that the agent is able to stop instantaneously. However, this assumption
  often does not hold in practice, e.g. a mobile robot moving with a cruising speed is not able to stop
  immediately but rather requires gradual deceleration to a full stop that takes time. In other words, the
  robot is subject to kinodynamic constraints. Unfortunately, as we show in this work, in such a case
  original SIPP is **incomplete**."* That paper introduces a variant *"provably complete and optimal for
  planning with acceleration/deceleration"*, and reports that the original SIPP property survives:
  *"it performs much less expansions compared to A* and, as a result, is notably faster."*
- **The temporal model** is a *reservation table*: vertices/edges of a roadmap are blocked during intervals
  by dynamic obstacles, and the planner searches over (vertex, safe-interval) states. `unverified:` the
  ICRA-11 paper's own wording of the state space and of the completeness/optimality theorem — full text not
  retrievable.
- **Motion model.** arXiv:1906.06911 (ICR'19) describes SIPP as *"capable of handling any-angle translations
  and rotations"* and treats path-following as a *separate* constrained-control problem, with a hierarchical
  split: SIPP plans a reference trajectory, a controller tracks it. Its experiments show that *"the number of
  successfully solved navigation instances significantly increases"* when the planned trajectory is made more
  trackable.

**Obstacles to applying SIPP to differential-drive AMRs in narrow aisles (each is sourced except where marked).**

1. **Instantaneous-stop violation → incompleteness.** A differential-drive AMR has non-zero deceleration and
   non-zero kinematic lag; on a stop-and-go plan the safe interval assumed by SIPP is shorter than the real
   stopping distance. Per arXiv:2302.00776, original SIPP is then *incomplete* for the true motion model —
   not merely suboptimal.
2. **Non-holonomic constraint.** A real AMR cannot translate sideways. Any-angle translations (arXiv:1906.06911)
   are only realisable through rotations, and rotations in a 1-cell-wide aisle sweep the footprint into
   neighbours. A grid abstraction that treats a cell as a point is therefore optimistic exactly where our
   safety problem lives.
3. **Rotation needs its own reservation.** In narrow aisles the swept volume during a turn is often the
   binding constraint, and it is a *continuous* obstacle, not a vertex. `unverified:` whether classic SIPP
   extensions model swept-volume rotation; the retrieved abstracts do not settle it.
4. **Control–plan decoupling is a real gap, not a detail.** arXiv:1906.06911 exists precisely because planning
   a geometrically safe path is insufficient — tracking it must also succeed. Our simulator must model
   tracking error, or SIPP-derived "safety" will be unearned.
5. **Temporal-parameter coupling.** SIPP interval arithmetic needs vehicle length/width/acceleration and a
   fixed time discretisation; our AGENTS.md clock rule (integer ns per clock domain) means the reservation
   table must be defined in an explicit domain and never mixed with display UTC.

### Design consequence for NĪHĀRAMESH

- **We will implement a simplified spatial-temporal variant behind a feature flag, and we will name it for
  what it is.** Proposed public name: `APPROX_SIPP_SINGLE_CELL` or similar. It is **not** SIPP and must never
  be presented as SIPP-compatible or SIPP-optimal.
- The feature flag must be **off by default** in any run whose metrics are exported or charted, and every
  artifact it produces must carry `planner: approximate-spatial-temporal` in its manifest.
- **The safety gate (AGENTS.md rule 7) does not consult the planner.** Even if our SIPP variant returns a
  "collision-free" plan, exclusivity still comes from the zone-grant protocol, and every actuator command
  still passes the veto gate. This is precisely the separation that makes our incompleteness tolerable: an
  incomplete *plan* costs throughput; an incomplete *safety* mechanism would be a defect.
- Do **not** claim optimality, completeness, or SOC-2-style formal guarantees for the planner. Claim: bounded
  search time, single-agent-per-interval reservations on an abstract grid, measured throughput.

### Caveats

- We did not read the SIPP paper. Every statement attributed to SIPP itself is `unverified:`; the
  assumptions we rely on come from later primary sources that restate them.
- Our variant inherits incompleteness w.r.t. acceleration by construction (arXiv:2302.00776). This is a
  documented, accepted limitation — but it must appear in the docs, not only in code comments.

---

## Evaluation

### Sources

- `https://www.movingai.com/benchmarks/mapf.html` — Moving AI MAPF benchmark page — **official site** — accessed `2026-10-02`
- `https://www.movingai.com/benchmarks/mapf/index.html` — MAPF benchmark set index (per-map inventory) — **official site** — accessed `2026-10-02`
- `https://www.movingai.com/benchmarks/formats.html` — Moving AI benchmark **file format** specification — **official docs** — accessed `2026-10-02`
- `https://www.movingai.com/benchmarks/grids.html` — 2D grid benchmarks page (format link + licence) — **official site** — accessed `2026-10-02`
- *Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks*, Stern, Sturtevant, Felner, Koenig, Ma, Walker, Li, Atzmon, Cohen, Satish Kumar, Boyarski, Bartak, SoCS 2019 — **paper** — **not retrieved** (required citation, published on the page)
- `https://www.itl.nist.gov/div898/handbook/eda/section3/eda334.htm` — NIST/SEMATECH e-Handbook, *Bootstrap Plot* — **official docs** — accessed `2026-10-02`
- `https://www.itl.nist.gov/div898/handbook/eda/section3/eda352.htm` — NIST/SEMATECH e-Handbook, *Confidence Limits for the Mean* — **official docs** — accessed `2026-10-02`
- `https://www.itl.nist.gov/div898/handbook/eda/section3/eda351.htm` — NIST/SEMATECH e-Handbook, *Measures of Location* — **official docs** — accessed `2026-10-02`

### Findings — datasets and formats

**Dataset inventory (from the MAPF index page, retrieved).** The MAPF benchmark set contains these maps,
each offered as a `.map` archive plus **two** scenario sets:

`Berlin_1_256` (256×256, 47 540 states), `Boston_0_256` (256×256, 47 768), `Paris_1_256` (256×256, 47 240),
`brc202d` (530×481, 43 151), `den312d` (65×81, 2 445), `den520d` (256×257, 28 178), `empty-8-8` (64),
`empty-16-16` (256), `empty-32-32` (1 024), `empty-48-48` (2 304), `ht_chantry` (162×141, 7 461),
`ht_mansion_n` (133×270, 8 959), `lak303d` (194×194, 14 784), `lt_gallowstemplar_n` (251×180, 10 021),
`maze-32-32-2` (666), `maze-32-32-4` (790), `maze-128-128-1` (8 191), `maze-128-128-2` (10 858),
`maze-128-128-10` (14 818), `orz900d` (1 491×656, 96 603), `ost003d` (194×194, 13 214),
`random-32-32-10` (922), `random-32-32-20` (819), `random-64-64-10` (3 687), `random-64-64-20` (3 270),
`room-32-32-4` (682), `room-64-64-8` (3 232), `room-64-64-16` (3 646), `w_woundedcoast` (642×578, 34 020),
`warehouse-10-20-10-2-1` (161×63, 5 699), `warehouse-10-20-10-2-2` (170×84, 9 776),
`warehouse-20-40-10-2-1` (321×123, 22 599), `warehouse-20-40-10-2-2` (340×164, 38 756).

The **four `warehouse-*` maps are the ones that resemble our domain**, and they are rectangular aisle grids
with dead ends — which is exactly the topology under which PIBT's biconnectivity theorem does not hold.

**Scenario-set structure.** *"There are 25 (x2) benchmark sets for each of the maps."* One set is generated
purely randomly, *"capped at 1000 problems per file"*; the other is *"evenly distributed in buckets of 10
problems with the same (length/4)"*. The intended use is *"add one agent at a time until an algorithm cannot
solve a problem in a given time/memory limit."* Required citation: Stern et al., SoCS 2019 (see Sources).

**`.map` format (from the official format page, retrieved).** Every map begins:

```
type octile
height y
width x
map
```

followed by an ASCII grid with upper-left corner at (0,0). Defined characters: `.` passable, `G` passable,
`@` out of bounds, `O` out of bounds, `T` trees (unpassable), `S` swamp (passable from regular terrain),
`W` water (traversable, but not passable from terrain).

**`.scen` format (from the official format page, retrieved).** Begins with `version x.x` (this document
describes 1.0; the trailing `0` is optional). Each line has **9 whitespace-separated fields**:

```
Bucket  map  width  height  start_x  start_y  goal_x  goal_y  optimal_length
0  maps/dao/arena.map  49  49  1  11  1  21
```

Notes stated by the format page: the optimal length assumes √2 diagonal costs; it assumes agents cannot cut
corners through walls; `(0,0)` is upper-left; if map height/width do not match the file it should be scaled;
and a single scenario file *can* contain problems from many maps, although currently each file holds problems
from one map.

**Licence.** *"All data is made available under the Open Data Commons Attribution License."*

### Findings — MAPF scenarios are **not** pickup-delivery workloads

This is not an opinion; it follows from the two pages above:

- A `.scen` line carries exactly **one start and one goal per agent, with no service time, no task release
  time, no task identity, no load state, and no assignment of which robot performs which leg.** There is
  no field in which a service time or a release time could be expressed.
- The stated usage model is *"add one agent at a time until an algorithm cannot solve a problem"*, i.e. the
  benchmark measures **solvability under increasing agent count**, not transport throughput.
- The `warehouse-*` maps happen to *look* like warehouses, but nothing in the format or the stated usage
  makes them pickup-and-delivery workloads. Treating them as such without a declared transformation would be
  an invented measurement — exactly what AGENTS.md rule 2 forbids.

### Concrete MAPF → pickup-delivery transport transformation

Deterministic, reproducible, and logged in the run manifest. Using a chosen `.map` and `.scen` file:

1. **Parse.** Read the `.map` header (`height`, `width`, `type octile`) and grid; read `.scen` lines. Keep
   `(start_x, start_y, goal_x, goal_y)` for each agent `i`. Treat `@`/`O`/`T` as blocked.
2. **Agent initial pose.** Robot `i` starts at `start_i` with heading from a declared deterministic rule
   (e.g. 0 rad) — the format has no heading.
3. **Split into pickup/drop.** `pickup_i = start_i`, `dropoff_i = goal_i`. One task per robot, **static
   pairing** — this is the weakest possible mapping and is stated as such.
4. **Service time.** Add a constant `service_time_s` at pickup and at drop. It must be a declared scenario
   parameter, not a hidden default, and must be expressed in the simulation-second clock domain (AGENTS.md
   rule 8).
5. **Task release times.** Release all tasks at `t = 0` for a *no-release* variant, or assign a declared
   release schedule `r_i` for a *staggered* variant (e.g. uniform over `[0, R]`). Report both; never mix.
6. **Load capacity.** Set capacity 1 (one task at a time). A single task per robot means capacity is
   non-binding — acknowledge this.
7. **Makespan definition.** `makespan = max_i (drop_completion_time_i) − min_i release_time_i`, in
   simulation seconds, stated in the manifest.
8. **Baseline.** "Traditional stop-and-wait" per the organiser's success criterion: a robot at a contested
   cell waits for the other to clear, no overtaking, no priority, no re-routing. This is the reference arm.
9. **Record provenance.** Store the exact `.map`/`.scen` filenames, their checksums, and the four added
   parameters (`service_time_s`, release policy, capacity, baseline definition) in the run manifest.

**Biases this introduces — stated, not hidden.**

- **Zero-payload bias.** One task per robot means the load state never changes, so we measure *traffic
  scheduling*, not *handling + transport*. Real MAPD makespan is dominated by the empty-return leg.
- **No release-time realism unless we add it.** With all releases at `t=0` the fleet starts saturated; that
  inflates early contention and can flatter or penalise our protocol depending on where it wins.
- **No service-time realism.** A constant service time ignores dock/queue blocking, which is a major source
  of real aisle deadlock.
- **Start/goal sampling bias.** Moving AI scenarios are built for MAPF, so start/goal distributions are
  conditioned on *solvability at high agent counts*, not on warehouse dock/station geometry. Our four
  warehouse maps are aisle grids, not realistic rack/pick-face layouts.
- **Paired-arm bias.** The same transformed workload must be used for both arms of every comparison. Any
  per-arm re-randomisation destroys pairing and must be avoided.

### Statistics for a paired makespan-reduction percentage at small n

**Recommendation: bootstrap percentile CI on per-pair ratios, paired by seed.** Concretely, for pair `i`
compute `r_i = (makespan_baseline,i − makespan_ours,i) / makespan_baseline,i` (the per-pair reduction),
then resample the `n` ratios with replacement (≥ 10 000 resamples), and report the 2.5th and 97.5th
percentiles. Point estimate = median of `r_i`; also report the per-pair count and the sign test.

Why this method, from retrievable sources:

- The resampling procedure itself is the NIST/SEMATECH bootstrap: *"a subsample of a size less than or equal
  to the size of the data set is generated from the data, and the statistic is calculated… generated with
  replacement… repeated for many subsamples, typically between 500 and 1000"*; the interval is obtained by
  ordering the resampled statistics and reading off percentiles (the page's worked example takes the 25th and
  475th of 500 ordered sample medians for a 90% interval). The same page states when to use it:
  *"There are many situations in which the uncertainty formulas are mathematically intractable. The bootstrap
  provides a method for calculating the uncertainty in these cases."* That is precisely our situation — the
  distribution of a *ratio* statistic on ~30 seeds has no usable closed form. The NIST page also records the
  scale warning: *"The uncertainty formulas for the median are frequently intractable"* and points to the
  bootstrap for confidence intervals on such location estimators.
- **Why the ratio, not the difference:** the distribution of makespan-reduction *percentages* is bounded and
  right-skewed; means are not robust there. NIST's robustness definitions are directly applicable — *"robustness
  of validity… the confidence intervals for the population location have a 95% chance of covering the
  population location regardless of what the underlying distribution is"* versus *"robustness of efficiency"* —
  and it states plainly that *"the mean… lacks robustness of validity"* for non-normal data while
  *"the median is an example of a estimator that tends to have robustness of validity but not robustness of
  efficiency."* Median-of-ratios + percentile interval buys validity at the cost of some width. That trade is
  correct when n is small and the reviewer needs to trust coverage.
- **Why percentile and not BCa:** the NIST page describes only the percentile method, and percentile is the
  one we can source. `unverified:` BCa acceleration (Efron & Tibshirani) — not retrieved. With n in the
  tens, BCa would be preferable if we can cite it; otherwise percentile + a sign test is defensible and
  honest.
- **Why not lead with Wilcoxon signed-rank:** `unverified:` — we did not retrieve a source for its null
  hypothesis (symmetry of the difference distribution) or its exact small-`n` critical values, and it tests a
  *location* of differences, not the mean of ratios that we actually want to report. We therefore present it
  as a **secondary confirmation only**, and if used, we must state the symmetry assumption explicitly.

**Assumptions and limitations we must state in every report.**

- **Pairing must be real.** Same map, same `.scen`, same seed, same fault schedule; only the coordination
  protocol differs. Otherwise the CI is meaningless.
- **n must be stated**, along with the seed list. A CI from n = 30 seeds is very wide; that is the honest
  answer, not a defect to hide.
- **Independence of pairs** is assumed. Seeds that share a map are not fully independent; report per-map and
  per-map-family breakdowns, or use a block bootstrap over maps. `unverified:` block bootstrap — not
  retrieved.
- **Percentile intervals are known to under-cover** in small samples. Do not describe the output as a 95%
  guarantee; describe it as a 95% *nominal* percentile interval.
- **Failures count.** A run that deadlocks or times out has **no makespan**. Report it as a separate
  failure count; never impute a makespan and never drop the pair silently. This is AGENTS.md rule 10.
- **The organiser's "zero collisions" is not a statistic we can bootstrap.** A zero count is not evidence of
  safety (AGENTS.md rule 2). Report the count, the exposure (robot-metres × run count), and the seed set.

### Design consequence for NĪHĀRAMESH

- Vendor the four `warehouse-*` Moving AI maps into `scenarios/` **as raw inputs only**, plus the
  transformation script and its manifest, so a reviewer can reproduce the transformation.
- Every benchmark artifact ships: source map/scenario filenames + checksums, the four added parameters, the
  seed list, `n`, the paired ratios, the CI, and the failure count.
- Never chart a number that is not traceable to an exported run artifact with a manifest.
- Report "20% makespan reduction" strictly as **organiser target vs. our measured CI**, never as an
  unqualified claim.

### Caveats

- The SoCS 2019 benchmark paper is the **required citation** for these datasets and we did not retrieve it.
  Our citation string is transcribed from the Moving AI MAPF page.
- We did not download the `.map`/`.scen` archives (zip not renderable by our fetcher). The format statements
  come from the official format page; actual file conformance is **not** verified by us.
- Open Data Commons Attribution License: attribution required, and redistribution terms should be checked
  before we mirror the archives into the repo. Prefer fetching at benchmark time over vendoring.

---

## ROS 2

### Sources

- `https://github.com/ros-infrastructure/rep/blob/master/rep-2000.rst` (fetched as raw RST) — REP 2000, *ROS 2 Releases and Target Platforms* — **official docs** — accessed `2026-10-02`
- `https://design.ros2.org/articles/ros_on_dds.html` — *ROS on DDS* (William Woodall; written 2014-06, last modified 2019-07) — **official docs** — accessed `2026-10-02`
- `https://github.com/ros2/ros2_documentation/blob/rolling/source/ROS-Framework/interfaces/topics/About-Quality-of-Service-Settings.rst` (fetched as raw RST) — *Quality of Service settings* — **official docs** — accessed `2026-10-02`
- `https://docs.nav2.org/rolling/.../configuring_collision_monitor_node/` — Nav2 *Collision Monitor Node* — **official docs** — accessed `2026-10-02`

### Findings — target platforms (REP 2000, retrieved)

- **Jazzy Jalisco: May 2024 – May 2029.** Targeted platforms: **Ubuntu Noble (24.04)** amd64 **Tier 1**
  (Debian packages + binary archive + source); arm64 **Tier 1**; arm32 **Tier 3**. Windows 10 (VS2019)
  Tier 1; RHEL 9 Tier 2; Ubuntu Jammy (22.04), macOS, Debian Bookworm, OpenEmbedded/Yocto Tier 3.
  Default RMW `rmw_fastrtps_cpp` (eProsima Fast-DDS) Tier 1; `rmw_cyclonedds_cpp` Tier 1;
  `rmw_connextdds` Tier 1 on Ubuntu/Windows/macOS. Minimum language requirements: **C++17, Python 3.8**.
- **Humble Hawksbill: May 2022 – May 2027.** Tier 1 on Ubuntu **Jammy (22.04)** amd64/arm64.
  ⇒ **Humble has NOT reached end of life.** As of `2026-10-02` it is still inside its 5-year window.
  Any claim that Humble is EOL is false as of this access date.
- **Kilted Kaiju: May 2025 – November 2026** — a non-LTS release whose support window **closes in roughly
  one month** from the access date. Do not pin to it.
- **Rolling Ridley** is the rolling development distribution (per REP-2002); as of May 2025 it targets the
  same platforms as Kilted.
- Policy that explains the numbers: *"Since regular Ubuntu releases are only supported for 9 months ROS 2
  will not target those. A single ROS 2 distribution will only have full Tier 1 support for a single Ubuntu
  LTS"*; and LTS releases are supported *"until the end of the standard support of the Ubuntu LTS release
  which is 4 years and 11 months from the ROS 2 release date."*
- **Correction to the task brief:** the brief asked "whether Humble/Ubuntu 22.04 has reached end of life".
  Per REP 2000 it has not (Humble runs to May 2027; Ubuntu 22.04 standard support also runs to 2027).
  Recorded as a correction, not silently dropped.

**Exact recommended pinned stack:** **ROS 2 Jazzy Jalisco on Ubuntu 24.04 Noble, amd64 or arm64**
(Tier 1, Debian packages available, support to May 2029), RMW `rmw_fastrtps_cpp` (default, Tier 1) or
`rmw_cyclonedds_cpp` (Tier 1), C++17 / Python 3.8 minimums. Do **not** pin Humble (shorter remaining
window) and do **not** pin Kilted (window closes Nov 2026). Record `ros2` / Ubuntu versions in the edge
profile as pinned values, not "latest".

### Findings — why DDS (design article, retrieved; read its own caveats)

- DDS is an **end-to-end, OMG-standardised** publish-subscribe transport with its own formal specification and
  reference API, so *"there is much less code to maintain and the behavior and exact specifications of the
  middleware have already been distilled into documentation."*
- **Distributed discovery replaces the ROS master**: *"The default discovery system provided by DDS… is
  distributed… This allows any two DDS programs to communicate without the need for a tool like the ROS
  master. This makes the system more fault tolerant and flexible."* This is the load-bearing reason for our
  no-central-server requirement (AGENTS.md rule 1).
- **QoS is the tuning surface**, spanning *"best-effort"* to *"reliable"*, which is why DDS suits lossy Wi-Fi
  warehouse links.
- **Honest caveats from the same page:** the article was written in 2014-06 and last modified 2019-07, and it
  explicitly notes it predates the final ROS 2 design; adopting DDS means *"adopting the philosophy and
  culture of that middleware"*; DDS is *"a static specification"* with a *"slow moving body"*; and the
  community risk is real: *"it isn't the feeling of a large community to fall back on with DDS."* Cite it as
  design rationale, **not** as current ROS 2 implementation documentation.

### Findings — QoS settings (official docs, retrieved)

- Policies: History (keep-last / keep-all), Depth, Reliability (best-effort / reliable), Durability
  (transient-local / volatile), Deadline, Lifespan, Liveliness (automatic / manual-by-topic), Lease Duration.
  For duration policies there is also a *"default"* meaning *"the duration is unspecified, which the
  underlying middleware will usually interpret as an infinitely long duration."*
- **Compatibility is a strict "request vs offered" model:** *"Connections are only made if every policy of
  the requested QoS profile is not more stringent than that of the offered QoS profile."* Best-effort
  publisher + reliable subscriber is **incompatible** — *"No."* Volatile publisher + transient-local
  subscriber is **incompatible** — *"No communication."*
- **Incompatibility is silent by default:** *"When connections are not made, no messages will be passed
  between the publisher and subscription."* Detection is opt-in via **QoS events** — publisher-side
  *"Offered incompatible QoS"*, *"Offered deadline missed"*, *"Liveliness lost"*; subscription-side
  *"Requested incompatible QoS"*, *"Requested deadline missed"*, *"Liveliness changed"* — plus **matched
  events** when a connection is established or dropped.
- Default pub/sub profile: keep-last, depth 10, reliable, volatile, system-default liveliness.
  A **sensor-data** profile exists (best-effort, smaller queue) for *"cases where it's more important to
  receive readings in a timely fashion, rather than ensuring that all of them arrive."*
- Note for our design: *"even the reliable policy in ROS 2 is implemented using UDP."*

### Findings — Nav2 Collision Monitor (official docs, retrieved)

- It is *"a node providing an additional level of robot safety"* that *"performs several collision avoidance
  related tasks using incoming data from the sensors, bypassing the costmap and trajectory planners"* to
  monitor at the **emergency-stop** level.
- **The documentation is explicit that it is not a certified safety system:** *"However, this node is done at
  the CPU level with any form of sensor. As such, this does not provide hard real-time safety certifications,
  but uses the same types of techniques with the same types of data for users that do not have safety-rated
  laser sensors, safety-rated controllers…"*
- Four behaviour models: **Stop** (≥ `min_points` obstacle points in a zone ⇒ stop), **Slowdown**
  (`slowdown_ratio` cap), **Limit** (cap `linear_limit` / `angular_limit`), **Approach** (estimate
  time-to-collision; if below `time_before_collision`, slow to maintain that margin). When multiple zones
  trigger, *"the most aggressive one is used (e.g. stop > slow 50% > slow 10%)."*
- Zone shapes: arbitrary polygon in the base frame, robot footprint, circle, and `VelocityPolygon` (polygon
  selected by commanded velocity — *"a larger safety zone when moving at 1.0 m/s than when moving at 0.5 m/s"*).
- Sources: `LaserScan`, `PointCloud2`, `Range`, `Costmap`. **Exclusion zones** mask a source's own returns
  (dock, conveyor, or the robot's own body) before the action polygons are evaluated, and the filter is
  **fail-safe**: *"if the zone transform is unavailable, no points are removed, so collision protection is
  never silently lost."*
- **Conservative timeout semantics already exist and we should mirror them:** `source_timeout` (default 2.0 s)
  — *"If no new data is received within this interval, the robot will be stopped. Setting `source_timeout: 0.0`
  disables this blocking mechanism."*; and `stop_pub_timeout` (default 1.0 s) bounds zero-velocity publication.
  Also `use_realtime_priority` (default false) raises thread priority to 90 and requires
  `<username> soft rtprio 99 / hard rtprio 99` in `/etc/security/limits.conf`.

### Design consequence for NĪHĀRAMESH

- **Pin ROS 2 Jazzy Jalisco / Ubuntu 24.04 Noble** in the edge profile and the bridge README, with arm64
  Tier 1 noted (Pi 5 is arm64 — see Edge hardware). Cite REP 2000. Do not claim Humble is EOL.
- **Do not use Kilted**: its support window closes November 2026.
- Our agent↔agent peer transport should be **DDS-native (no ROS master)**, which the DDS design article
  supports as the reason ROS 2 has no single discovery point. But the article is 2014-era; our own protocol
  must not depend on DDS discovery semantics we have not tested. Keep the simulation transport independent.
- **Pin explicit QoS profiles and treat QoS events as observable state, not logs.** Because an incompatible
  request/offer pair yields *silence*, our `pnpm doctor` must detect "peer connected but receiving nothing"
  and report it as an **honest state** (`unavailable`/timeout), never as "no traffic" (AGENTS.md rule 10).
  Concretely: grant/lease traffic = **reliable, keep-last, small depth** (we cannot drop a grant);
  high-rate pose/telemetry = **best-effort sensor-data profile** (we prefer freshness over completeness —
  this is the literal sense of "freshness-aware").
- **Model the safety gate after Collision Monitor's structure, not its authority**: zones with explicit
  thresholds, most-aggressive-wins, and — crucially — **fail-safe exclusion** and **stop-on-stale-source**.
  Our AGENTS.md rules 4 and 7 are the same idea: expiry revokes *permission to assume*, never occupancy;
  stale input produces a stop, not a guess.
- **In every doc, state in the same sentence as any safety claim that a software monitor is not a certified
  safety function.** Nav2's own docs say this; we must not be weaker than the upstream doc.

### Caveats

- `ros_on_dds` is 2014-vintage and self-declares that it predates final decisions. Use it for rationale only.
- REP 2000 documents *targets*, not our build. Our container/CI must actually build against Jazzy+Noble and
  record that, or the profile is a claim without evidence.
- Nav2 docs are `rolling`, which is **not** Jazzy. Pin Nav2 docs to the Jazzy branch before quoting parameter
  names as Jazzy-stable. `unverified:` — I fetched the rolling docs only.
- QoS defaults are per-RMW-implementation in places (`"system default"`), so behaviour can differ between
  Fast-DDS and Cyclone. Pin the RMW.

---

## Engineering references

### Sources

- `https://playwright.dev/docs/test-assertions` — Playwright *Assertions* — **official docs** — accessed `2026-10-02`
- `https://playwright.dev/docs/api/class-page` (`page.waitForLoadState`, `page.goto` `waitUntil`) — **official docs** — accessed `2026-10-02`
- `https://playwright.dev/docs/navigations` — **official docs** — accessed `2026-10-02`
- `https://playwright.dev/docs/network` — **official docs** — accessed `2026-10-02`
- `https://docs.astral.sh/uv/concepts/projects/workspaces/` — uv *Using workspaces* — **official docs** — accessed `2026-10-02`
- `https://pixijs.com/8.x/guides/components/ticker` — PixiJS 8 *Ticker* — **official docs** — accessed `2026-10-02`
- `https://fastapi.tiangolo.com/deployment/docker/` — FastAPI *in Containers — Docker* — **official docs** — accessed `2026-10-02`

### Findings and consequences — Playwright

**`networkidle` is explicitly discouraged by the vendor.** The `Page` API states, for `waitUntil` and for
`page.waitForLoadState`:

> `'networkidle'` — **DISCOURAGED** wait until there are no network connections for at least `500` ms.
> Don't use this method for testing, rely on web assertions to assess readiness instead.

**Why it is structurally wrong for our cockpit.** Our app holds **continuous telemetry** — an SSE/WebSocket
or long-poll telemetry stream plus periodic robot-state fetches. "No network connections for 500 ms" is then
either never true (test hangs until timeout) or true only in a lull that tells us nothing about fleet state.
It measures transport idleness, not application readiness. The same argument makes `waitForLoadState()`
unnecessary: the docs say *"you should not need it in most cases"*, and Playwright *"will automatically wait
for the target elements to become actionable."*

**The recommended readiness condition: an auto-retrying web assertion on observable application state.**
Playwright's auto-retrying locator assertions *"will retry until the assertion passes, or the assertion
timeout is reached"*, default timeout 5 s, configurable via `testConfig.expect`. Use:

- `await expect(page.getByTestId('fleet-status')).toHaveText('connected')` — app-level readiness.
- `await expect(page.getByTestId('robot-card-…')).toHaveCount(n)` — the fleet rendered.
- `await expect(page.getByTestId('makespan')).toHaveText(/\d/)` — metrics present, not "0".
- `await expect(page.getByTestId('zone-table')).toContainText('held')` — coordination state visible.
- `await expect(page.getByTestId('degraded')).toBeVisible()` — the *unhappy* path, so "unavailable" must be
  assertable (AGENTS.md rule 10).
- For non-UI state: `expect.poll(...)` to turn any synchronous `expect` into a polling one, or
  `expect(async () => {...}).toPass()` to retry a block; both accept custom `intervals`.
- Prefer **non-retrying assertions sparingly**: the docs warn *"Most of the time, web pages show information
  asynchronously, and using non-retrying assertions can lead to a flaky test."* That is a direct instruction
  against `expect(x).toEqual(y)` on telemetry.
- Use **soft assertions** (`expect.soft`, then `expect(test.info().errors).toHaveLength(0)`) when you want to
  collect all cockpit failures in one run instead of stopping at the first.
- For a specific response, prefer `page.waitForResponse('**/api/...')` over any global idle wait, and stub
  telemetry with `page.route(...)` so readiness does not depend on a live fleet.
- AGENTS.md rule: *"Tests must assert behaviour, not screenshots"* — consistent with the docs' guidance to
  rely on assertions, and reinforced by `toHaveURL`, `toHaveTitle`, `toHaveRole`, `toHaveAccessibleName`.

### Findings and consequences — uv workspaces

- A workspace is *"a collection of one or more packages, called workspace members, that are managed
  together"*, Cargo-inspired. Each member has its own `pyproject.toml`; the workspace shares **one lockfile**.
- `uv lock` operates on the **entire workspace at once**; `uv run` and `uv sync` operate on the workspace
  root **by default**, both accepting `--package` to target a member.
- Members are declared in `[tool.uv.workspace]` with required `members` and optional `exclude` (glob lists);
  every matched directory must contain a `pyproject.toml`. The workspace root is *also* a member.
- Cross-member deps use `[tool.uv.sources] dep = { workspace = true }`; `workspace` may also be a **path to
  another workspace root**. *"Dependencies between workspace members are editable."*
- Root `[tool.uv.sources]` apply to all members unless a member overrides; a member's own `tool.uv.sources`
  entry **wins even if its marker does not match the current platform** — a real footgun for platform-specific
  deps.
- **Limits that constrain our layout:** *"uv's workspaces enforce a single `requires-python` for the entire
  workspace, taking the intersection of all members' `requires-python` values"*; workspaces are *"not suited
  for cases in which members have conflicting requirements, or desire a separate virtual environment for each
  member"* (use path dependencies instead); and *"uv can't ensure that a package uses its declared
  dependencies and nothing else… uv can't ensure that packages don't import dependencies declared by another
  workspace member."* That last point is **direct, citable justification for our authority-boundary tests**:
  dependency isolation is *not* an enforcement mechanism here, so our tests must police import boundaries
  themselves.

### Findings and consequences — PixiJS 8 Ticker

- `Ticker` *"provides a powerful and flexible mechanism for executing callbacks on every animation frame"* —
  game loops, animations, and *"any time-based updates."*
- Standalone construction works without an `Application`: `const ticker = new Ticker(); ticker.add(cb);
  ticker.start();`. Listeners: `ticker.add(fn, ctx)`, `addOnce`, `remove`. Control: `start()`,
  `stop()` (*"Pause the ticker and cancel the animation frame"*), and `ticker.autoStart = true` to start on
  first listener.
- **Listener priority** — *"Listeners can be assigned a priority. Higher values run earlier"* with
  `UPDATE_PRIORITY.HIGH = 50`, `NORMAL = 0`, `LOW = -50`. This is the mechanism for ordering update phases.
- **Frame-rate clamping is where determinism leaks in**, and it is documented: `ticker.minFPS` *"Caps how
  slow frames are allowed to be. Used to clamp `deltaTime`"*; `ticker.maxFPS` *"Limits how fast the ticker
  runs"*; `maxFPS = 0` allows unlimited framerate.
- **Consequence:** drive the render loop from a **dedicated `Ticker` owned by the Pixi layer**, never from
  React state or effects. React supplies data (TanStack Query server state; Zustand view state); the ticker
  owns interpolation and drawing. That keeps motion rendering out of React reconciliation (AGENTS.md
  convention) and means a re-render does not restart the loop.
- **Consequence for clock discipline (AGENTS.md rule 8):** the ticker exposes a **frame delta**, which is
  wall-clock-ish, not simulation time. Robot interpolation must advance on *simulation* time from the
  telemetry stream, and `deltaTime` may only be used for *display smoothing*. In deterministic replay, set
  `maxFPS` deterministically and never let `deltaTime` influence simulated state — otherwise the same run
  would render differently on different machines while claiming determinism.

### Findings and consequences — FastAPI in containers

- Official recommendation: **build the image from scratch** on the official Python base image. The old
  `tiangolo/uvicorn-gunicorn-fastapi` base image is **deprecated**: *"You should probably not use this base
  Docker image (or any other similar one)."*
- With a `uv` project: *"its direct dependencies are declared in `pyproject.toml` and the exact resolved
  versions are stored in `uv.lock`"*, and the lock is exported into the image build via
  `uv export --format requirements-txt --no-dev --no-emit-project --output-file requirements.txt`. **The
  exported lock is the reproducibility artifact** — the container installs the resolved set, not a range.
- **Always use the exec form of `CMD`**: *"Make sure to always use the exec form of the `CMD` instruction"*,
  so FastAPI *"can shutdown gracefully and lifespan events are triggered."* Shell form breaks graceful
  shutdown and, per the linked Docker Compose FAQ, costs ~10 s on recreate/stop.
- Behind a TLS-terminating proxy, add `--proxy-headers`.
- **Docker cache discipline:** copy `requirements.txt` **first**, install, then copy application code —
  otherwise the dependency layer is invalidated on every code change. The docs are explicit that the install
  step is the expensive one.
- **One process per container** when a cluster handles replication; `--workers N` is for the simple
  single-server case (e.g. Docker Compose). Multiple worker processes inside one container mean you must
  reason about memory yourself.
- HTTPS is normally handled by an external component (Traefik, cloud LB). Restarts via the orchestrator.
- **Consequence for AGENTS.md rule 1 ("the API never coordinates"):** the docs' own replication guidance
  (multiple workers / multiple replicas) is a reminder that horizontal scaling multiplies API processes. Our
  authority boundary is unaffected **only** because the API holds no coordination state. Make that explicit
  in `deployment/`, or a future reader may "scale" the API into a coordinator by accident.
- Note: the current docs example uses `python:3.14` and `fastapi run`; our pinned versions must be explicit
  rather than copied from the example.

---

## Edge hardware

### Sources

- `https://www.raspberrypi.com/products/raspberry-pi-5/` — official product page — **official site** — **403, not retrieved**
- `https://www.raspberrypi.com/documentation/computers/raspberry-pi.html` — official documentation, hardware comparison table — **official docs** — accessed `2026-10-02`
- `https://datasheets.raspberrypi.com/raspberry-pi-5-product-brief.pdf` — **404, not retrieved**

### Findings

From the official documentation hardware table (retrieved):

- **Raspberry Pi 5**: SoC **BCM2712**; **RAM options: 1 GB, 2 GB, 4 GB, 8 GB, 16 GB**; 40-pin GPIO header;
  2× micro-HDMI; 2× USB 2.0; 2× USB 3.0; combined CSI/DSI fine-pitch ports; single-lane PCIe FFC
  connector; UART connector; RTC battery connector; four-pin JST-SH PWM fan connector;
  **Gigabit (1 Gb/s) Ethernet RJ45 with PoE+**; **2.4/5 GHz dual-band 802.11ac Wi-Fi 5 (300 Mb/s)**;
  Bluetooth 5 + BLE; microSD slot; **USB-C power 5 V at 5 A (25 W), or 5 V at 3 A (15 W) with a 600 mA
  peripheral limit**.
- **Compute Module 5** (the relevant part for a fleet robot): **BCM2712**; RAM **2/4/8/16 GB**;
  optional 802.11ac Wi-Fi 5 + BT 5; **no networking listed by default**.
- The documentation also states the fan thermal curve and that a fan is an official option, with the Active
  Cooler case *"recommended for overclockers"*.
- `unverified:` **CPU core count and instruction set for Pi 5 / BCM2712.** The product page is 403 and the
  processors sub-page also 403'd, so I could **not** retrieve the "quad-core 2.4 GHz Cortex-A76" figure from
  a first-party page in this session. **Do not state a core count, clock, or ISA from this document.**
- `unverified:` sustained/thermal performance. Nothing we retrieved benchmarks anything.

### Design consequence for NĪHĀRAMESH

- The edge profile may state, as **specification sourced to official documentation**: BCM2712 SoC,
  1/2/4/8/16 GB RAM (CM5: 2/4/8/16 GB), gigabit Ethernet with PoE+, Wi-Fi 5 (300 Mb/s), USB-C 25 W or
  15 W/600 mA peripheral-limited, active cooling available.
- The profile **must** say, in the same breath: **no Raspberry Pi hardware was available to the team; nothing
  here was measured; throughput/latency/thermal behaviour on a Pi is `unavailable` (AGENTS.md rule 10), not
  zero and not estimated.**
- Prefer **CM5 with PoE Ethernet** in any written deployment profile: wired is the defensible choice for a
  coordination protocol whose safety argument is about *availability of peer messages*, and Wi-Fi 5 with
  300 Mb/s and the warehouse "Wi-Fi dead-zone" problem the organiser names is a poor substrate for our
  conservative-occupancy assumption. This is a design *preference* supported by the organiser's own stated
  concern, not a measured result.
- 25 W (or 15 W with a 600 mA peripheral limit) is a real constraint on USB peripherals (LiDAR, radio) —
  record it, do not design against more.
- **Do not print a core count or clock speed** in the profile until someone retrieves the product page or
  datasheet successfully.

### Caveats

- We hold **no Pi**. This section is specification-only, by explicit project agreement.
- SKUs and RAM options change; re-verify against the official documentation table before publication.

---

## Attribution and licensing

- Everything in this register is **paraphrase plus citation**. We quote only short fragments needed to
  document a design decision or a vendor's own warning language (notably the Playwright `networkidle`
  deprecation and the Nav2 "not hard real-time safety certifications" sentence), each with its URL and access
  date.
- **No full text of any paper, book, standard, or documentation page is vendored, mirrored, or stored in this
  repository.** The `.map`/`.scen` Moving AI archives are **not** vendored (we could not download them, and
  prefer fetching at benchmark time); our scenarios reference them by name and checksum under the Open Data
  Commons Attribution License.
- **No vendor or third-party code is vendored.** SBPL, pibt2, HOG2, Nav2, ROS 2, PixiJS, Playwright, uv and
  FastAPI are referenced by URL only. Our implementation is written from scratch and is, at most,
  *inspired by* the cited algorithms — not derived from their source.
- The MIT DSpace CBAA/CBBA record states the article *"is made available in accordance with the publisher's
  policy"*; we cite and paraphrase the abstract only and do not redistribute it.
- The `design.ros2.org` DDS article is, per its own footer, licensed **CC BY 3.0**; we paraphrase and
  attribute it.
- Every source, its type, access date and retrieval status is machine-readable in `research/sources.json`.
  If a future revision cites a source marked `retrieved: false` for content, that is a defect.

---

## Open questions

1. **Surplus auction.** No primary source retrievable (three arXiv queries → 0 results; Crossref title search
   → only unrelated economics). Owner needed to obtain it by another route, or we permanently omit the family.
2. **Raspberry Pi 5 CPU count / clock / ISA.** Product page and processors page both 403; datasheet PDF 404.
   Until resolved, the edge profile must omit core count and clock.
3. **Project dossier.** Inaccessible (login/unsupported-browser wall). Any claim sourced to it is currently
   unverifiable from this workstream.
4. **SIPP full text.** Not renderable by our fetcher. If a reviewer disputes our reading of SIPP's
   assumptions, we need a human-read copy of the ICRA-11 PDF.
5. **Availability cost of canonical sequential acquisition.** We can argue safety; we cannot yet state a
   bound on blocking. Open: measure grant wait-time per zone and the incidence of hold-and-wait cycles.
   Candidate mitigations to evaluate, none chosen: bounded grant TTL + backoff, per-zone priority rotation,
   or a documented "yield" escalation. All require re-deriving the safety argument.
6. **Does our protocol deadlock under dead-end topologies?** PIBT's theorem does not apply to our maps
   (arXiv:2205.12504 says so explicitly). Open: whether our zone-decomposition + conservative occupancy
   yields deadlock-freedom empirically, and whether we adopt a temporary-priority recovery mechanism.
7. **BCa vs percentile for the paired ratio CI.** We can cite only the percentile method (NIST). Open: obtain
   a citable primary source for BCa and decide with `n` in mind.
8. **Block bootstrap over maps.** Seeds sharing a map are not independent. Open: decide whether the headline
   CI is over all pairs or map-blocked, and cite a source for the block bootstrap.
9. **MAPF→MAPD transformation parameters.** `service_time_s` and the release policy are currently *our* choice
   with no warehouse-grounded default. Open: find or justify a defensible value; until then it is a declared
   scenario parameter, never a default.
10. **Nav2 doc branch.** We fetched `rolling`, not Jazzy. Open: re-verify every quoted parameter name against
    the Jazzy docs before shipping a ROS bridge.
11. **CBAA scoring-function assumptions.** Convergence is proved *"under reasonable assumptions on the
    scoring scheme"*; we have not verified our (distance + freshness + battery) scoring against them.
    `unverified:` what "reasonable" requires.
12. **`pnpm benchmark:full` power.** With small `n`, the CI may simply not exclude 0%. That is an acceptable,
    honest outcome — but decide in advance what we will report if it happens, so no one is tempted to switch
    to an unpaired or post-hoc-selected statistic.
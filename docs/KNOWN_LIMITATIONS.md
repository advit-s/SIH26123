# Known limitations

Dated: 2026-10-02 · Branch `feat/niharamesh-platform`

This file exists so that nothing in the repository is read as more capable than it
is. Every entry says what is *not* true yet, why, and what would change it.

---

## 1. The 20 % makespan-reduction target is unmeasured

**Not true:** that NĪHĀRAMESH achieves a ≥20 % reduction in total task-completion
time against stop-and-wait on overlapping routes.

The requirement states this as a **target**. No paired benchmark result exists in
this repository yet, so the claim cannot be made in either direction. The
organiser's own success criterion (per `docs/RESEARCH.md`, from `sih.gov.in`) is a
minimum 20 % reduction against traditional stop-and-wait, which makes the figure
an evaluation objective rather than a result.

**What would change this:** executing `scenarios/suites/main.json` with at least 30
paired seeds through `pnpm benchmark:full`, then reporting the measured paired
reduction with its eligibility rules, sample counts, exclusions and uncertainty.
If the target is not reached, that is reported as the finding, with the bottleneck
and the next experiment — not worked around by changing the baseline.

---

## 2. Zero observed collisions is not collision freedom

**Not true:** that the system is collision-free.

The evaluator independently detects inter-robot and robot-obstacle overlap using
two different algorithms (`swept_body_overlap` and `oracle_overlap`), and the world
genuinely applies colliding commands rather than suppressing them. A run reporting
zero collisions is therefore evidence that no collision was *observed* under that
run's geometry, sensing and timing — not a universal guarantee.

`RunResult` carries `collisions` alongside `min_clearance_m`, and the metric
registry marks collision counts `zero_is_proof = False`.

---

## 3. Docker Compose path is authored but unexecuted

**Not true:** that the containerised deployment has been run.

Docker is not installed on the authoring machine (`docker --version` →
command not found, recorded in `docs/STATUS.md`). `deployment/docker/` contains a
reviewed Compose topology with health checks, but no image was built, no container
started, and no service-health assertion was executed.

**What would change this:** installing Docker and running the Compose path, then
recording the actual startup output and health transitions.

---

## 4. ROS 2 integration boundary is unexecuted

**Not true:** that the ROS 2 adapters build or communicate.

No ROS 2 installation is available here. `ros2/niharamesh_interfaces` contains
message definitions and `ros2/niharamesh_bridge` contains adapter logic plus a
fixture-driven dry-run test that exercises the **same agent core** a live node
would drive. That dry run is unit-verified; `colcon build`, `ros2 interface show`
and a live DDS round trip have not run.

Two further caveats, both from `docs/RESEARCH.md`:

* **The pinned target is a researched recommendation, not a tested build.** Jazzy
  Jalisco on Ubuntu 24.04 (arm64) is the current Tier-1 LTS per REP-2000. Humble
  Hawksbill runs to May 2027 and has *not* reached end of life, so the brief's
  premise that it is EOL is wrong; Kilted Kaiju's window closes in November 2026
  and must not be pinned. All of this must be validated against the official
  platform matrix before the claim is repeated.
* **QoS incompatibility between peers is silent.** A best-effort publisher with a
  reliable subscriber matches no profile and simply delivers nothing. Any
  integration check must distinguish "connected but silent" from "healthy and
  idle" and report the former as `unavailable`, not as "no traffic".

Nav2's Collision Monitor informs the adapter's structure (zones,
most-aggressive-wins, fail-safe exclusion, stop-on-stale-source) but its authority
is **not** replicated. Nav2's own documentation states it "does not provide hard
real-time safety certifications", and neither does anything here.

---

## 5. Edge hardware is specified, not measured

**Not true:** that NĪHĀRAMESH was measured on ARM edge hardware.

`deployment/edge/` contains profiles for three hosts with process identity, storage,
networking, power/cooling considerations and deployment commands. Every performance
figure in those profiles is either a vendor specification or an explicitly
unverified placeholder. No CPU, memory or timing measurement was taken on a
physical edge device, because none was available.

**Not true either:** the Raspberry Pi 5's CPU core count or clock rate. The product
page and datasheet returned HTTP 403 / 404 during research, so those specific
figures are marked `unverified:` in `docs/RESEARCH.md` and are deliberately **not**
printed in the profiles.

---

## 6. Static feasibility analysis is partial, and says so

Multi-robot reachability and deadlock-freedom are **not** decided statically.
`ValidationReport.checks_not_performed` states this on every validation, and the
reachability check that *is* performed is described as a 0.25 m configuration-space
flood fill — an estimate, not a completeness proof.

Static validation does catch structural invalidity decisively: overlapping
protected zone geometry, berths inside a zone, undersized passages, duplicate ids,
invalid references, overlapping initial bodies, incompatible schema versions.

---

## 7. Protocol verification is bounded

The interleaving tests enumerate message permutations up to a **stated bound**
(`tests/protocol/test_interleavings.py`). Passing bounded tests is not an unbounded
formal proof, and the bound is recorded rather than implied away.

Deadlock-freedom is argued from the *global* single-outstanding-grant invariant
rather than detected by search. That argument is sound for healthy robots under a
reliable non-partitioned network, but it says nothing about liveness once a robot
fails while holding a grant — its zone stays fenced until a supervised transition.
This is a deliberate availability cost, documented in `docs/adr/0003`.

---

## 8. No learned component is shipped

The brief permits an optional learned travel-time estimator. None is present.
Rather than ship an untrained model described as if it worked, the system uses an
analytical queue-delay estimate inside the bid cost model.

The AI in this system is precisely: onboard A* search, constrained velocity
profiles, intent prediction from a spatial plan, and multi-agent negotiation.
Calling that "AI powered" would be an overstatement, so the documentation does not.

It is also **not** yet established whether the sponsor expects machine learning
specifically. That is an open question, recorded rather than assumed either way.

---

## 9. Temporal planning is approximate and off by default

`temporal_planning` is implemented as `ApproxSippSingleCellPlanner`. The original
SIPP assumes an agent can stop instantaneously and is incomplete under
kinodynamic constraints — neither holds for a differential-drive AMR in a 1.40 m
aisle. The variant discretises space×time on the inflated grid and only avoids
reservations it has been told about. It makes **no completeness or optimality
claim**, it is off by default for exported runs, and it never participates in the
safety path.

---

## 10. Scope boundaries held deliberately

Not built, because nothing in the specification required them: Kubernetes, Kafka,
payments, subscriptions, a marketing site, multi-tenant accounts, blockchain, an LLM
chat panel, a large cloud stack, or a 3D view as a gate. Physical actuation ships
disabled by default and is refused outright while any safety-weakening ablation
flag is set.

---

## 11. Known environment limits on this machine

| Limit | Consequence |
|---|---|
| Docker absent | Compose path unexecuted (item 3) |
| No ROS 2 | Bridge build unexecuted (item 4) |
| No ARM/edge hardware | Edge figures are specifications (item 5) |
| Windows + PowerShell | Linux-specific paths are authored but unexecuted; the native launcher is the tested path |
| No paid APIs or cloud accounts | Also a design constraint, not just an environment one |

---

---

## 12. The three-process network test is intermittently red, and its root cause is not known

**Not true:** that `tests/network/test_three_process_peers.py` passes reliably.

Measured in this checkout, 2026-10-02:

- `test_three_process_peers_talk_directly` in isolation: **22 consecutive passes, 0
  failures** (10 whole-file runs plus 14 single-test runs).
- Within the **full** Python suite: **1 failure in 3 runs**, on the assertion that a
  cut robot's link to the *survivor* reports `status == "healthy"`.

The observed value at failure:

```text
{'availability': 'unavailable', 'connect_attempts': 1, 'connected': False,
 'dialed_from_port': 0, 'status': 'disconnected'}
```

`connect_attempts: 1` with `connected: False` means the outbound link had completed
its **first and only** dial attempt. `PeerLink.run` retries with capped backoff, so a
single attempt implies the reconnect loop had not re-entered when the sample was
taken — either the socket was still attached while the health model judged the link
unavailable, or the loop was inside `_read_loop` and therefore not reconnecting.

**An attempted fix was reverted, and the reason is recorded because getting it wrong
is the interesting part.** The test's own comment claims it waits on an observable
"cut is live" condition before sampling; the code does not, it sleeps `_PHASE_S`.
Adding that wait made the failure *consistent* (8 of 10 runs) instead of intermittent
and moved it to a different robot. The original was a load-dependent race; the wait
changed the sampling instant to a point where the link is genuinely still settling,
and this checkout contains no evidence about which of those states is correct.
Guessing would have produced a test that passes for the wrong reason, so the change
was reverted and the flake is recorded here instead.

**What would change this:** reading how `health.peers[*].status` and `availability`
are derived in `transport/peer.py` and `transport/faults.py`, and establishing
whether link availability is meant to survive a partition that silences only *other*
peers. Until then this test's result is reported as observed, not smoothed over.

---

## 13. No scenario completes a task

**Not true:** that any authored scenario currently delivers a payload.

Measured 2026-10-02 at a 150 s budget across all seven library scenarios: every one
returns `incomplete`. `three-way-junction` showed amr-02 holding `zn-junction` and
amr-03 correctly starving behind it, because no robot declared zone entry or release
and no task was bound through the auction. Station service, custody and completion
credit were unwired at the time of that measurement.

This is Milestone B work in progress, recorded so no earlier status line is read as a
claim of end-to-end capability. A stationary fleet is not a demonstration of
collision avoidance, and a run that reports `incomplete` is the correct report for it.

## 14. Honest reporting rules this project holds itself to

These are the mechanisms that keep the items above from quietly becoming false:

- Metrics that were not collected are `MetricValue.unavailable(...)`, never `0`.
- An ineligible run (incomplete, unsafe, timed out, incomplete evidence) never
  receives a success badge, and excluded pairs are displayed beside any aggregate.
- Battery values state `measured` / `simulated` / `estimated` / `unavailable`.
- `nihara doctor` prints measured values only when collected.
- Safety-weakening ablations mark their run `unsafe_research_variant`, and the UI
  labels such results as research observations, never as safety evidence.
- Recording gaps are explicit `RecordingGap` records; a run with an unrecovered
  gap in a durable category is marked incomplete and excluded from claims that
  require complete evidence.

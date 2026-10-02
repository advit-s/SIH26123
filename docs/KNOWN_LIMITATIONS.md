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

## 2. Collision counts: a real collision was found, and a zero is still not a proof

**Not true:** that the system is collision-free.

The evaluator independently detects inter-robot and robot-obstacle overlap using
two different algorithms (`swept_body_overlap` and `oracle_overlap`), and the world
genuinely applies colliding commands rather than suppressing them. A run reporting
zero collisions is therefore evidence that no collision was *observed* under that
run's geometry, sensing and timing — not a universal guarantee.

**A non-zero count is a real finding, and one was found.** On 2026-10-03,
`dynamic-arrivals` produced **556 overlapping physics samples** between `amr-01` and
`amr-02` from 62.2 s, on the authored map with no fault injected and nothing edited.
Root cause: the safety gate had no inter-robot check — a peer reached it only as one
forward-cone distance compared against a *longitudinal* braking budget, which is the
wrong quantity for a robot beside the nose. The gate now refuses closing motion
within a declared separation of a sensed peer, and the overlap no longer occurs in
that run. The regression is `tests/integration/test_inter_robot_separation.py`, which
skips when the collision no longer reproduces.

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

## 12. The three-process network test WAS intermittently red — root cause found 2026-10-03

**Resolved, and the cause was never in the transport.**

Measured in this checkout on 2026-10-02, the flake was: within the full Python
suite, 1 failure in 3 runs, on the assertion that a cut robot's link to the
*survivor* reports `status == "healthy"`. An attempted fix had already been reverted
and recorded.

**Root cause, found 2026-10-03.** Each of the three child processes samples
`transport.health()` itself and then immediately calls `transport.stop()`, which
closes every peer socket. The children are not phase-synchronised — each starts its
own clock after its own import and polls for the phase command every 20 ms — so when
the natural skew exceeds a child's shutdown time, a still-running child *truthfully*
reports a departed peer as `disconnected` / `availability: "unavailable"`. The test
asserted `healthy` at an instant at which the peer had legitimately gone.

Reproduced at **5 failures in 45 runs** under CPU load (14 busy-loop processes on 12
cores), and **in isolation on the very first uninstrumented run**. The departed
peer's own stack is `PeerTransportServer.stop -> PeerClient.stop -> _detach ->
StreamWriter.close`, and `connect_attempts` of 1 versus 2 is the reconnect backoff
clock (≤ 57.5 ms after a successful attach), not a stuck loop.

**Fix:** a shutdown barrier — no robot calls `transport.stop()` until the parent
holds all three phase-2 snapshots — plus
`test_a_robot_that_finishes_early_is_still_healthy_in_its_peers`, which injects the
phase skew deterministically and failed 6 of 6 times without the barrier. Post-fix:
40/40 under 14 burners, 20/20 under 10 burners with the artifact ordering invariant
checked on every run, and 0 `tests/network` failures across 5 full-suite runs.
A finite clean sample is evidence, not a guarantee of zero future flakes.

**Two genuine transport defects were found on the way and are fixed.**
`PeerTransportServer._spawn` registered `self._tasks.discard` as its done callback,
so a worker killed by an unhandled exception left no counter, no health field and no
log. And `last_rx_ns` / `last_tx_ns` used `0` as the "no evidence" sentinel, which
is a legal measurement because `time.monotonic()` resolves to a millisecond on
Windows; they now report `None`.

**Still open in that test:** its no-leak counters are incremented at the consumer
(`drain()` popping the inbox) rather than at admission, so `drain()` lag is
indistinguishable from a partition leak. The partition itself is sound — the
lag-free evidence is the transport's own inbound drop counter. Not fixed here.

---

## 13. No authored scenario has yet reached `success`

**Superseded as written on 2026-10-03; the honest replacement is worse, not
better.**

The original claim was "no scenario delivers a payload". That is no longer true:
`three-way-junction` completes `t-junction-0` with exactly one completion credit,
and `dynamic-arrivals` completes `t-dyn-2`. Those are real deliveries, derived from
real custody events.

What is still true, and is the current limitation:

**Not one of the seven authored scenarios classifies as `success` at its own
declared budget.** Every one returns `incomplete`, or — for the partition and
infeasible layouts — returns something that is not yet the diagnostic outcome the
scenario intends. `infeasible-layout` is still not `expected_safe_stop`.

Three causes are known and none is diagnosed to root cause yet:

1. **Throughput.** Two of `three-way-junction`'s three tasks, and most of
   `dynamic-arrivals`' four, do not finish inside their budgets. Measured causes:
   a mutual standoff in a 1.4 m aisle with no passing place, and `amr-01` spending
   long stretches stopped under `obstacle_in_path`. Whether the clearance governor
   is too timid or the geometry is genuinely too tight is **still a hypothesis**.
2. **`infeasible-layout` never reaches its diagnostic state.** The run now
   terminates correctly, but the classification and the evidence behind it are not
   yet in place.
3. **Partition behaviour is injected but not yet measured.** `asymmetric-partition`'s
   declared cut is now applied to harness routing; what the fleet *does* under it is
   not yet established.

Nothing here is worked around. No deadline was enlarged, no map edited, no task
discarded, and no collision check weakened to produce these numbers.

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

# Architecture decision records

Each ADR states the decision, the alternatives rejected **with reasons**, the
consequences, and — importantly — **what would make us revisit it**. An ADR without a
revisiting condition is a decision nobody may question, which is not what this file
is for.

Full text with rejected alternatives and verification pointers:
[`docs/adr/0002-canonical-sequential-acquisition.md`](adr/0002-canonical-sequential-acquisition.md)
… etc.

| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-canonical-json-schema-single-source.md) | Pydantic models are the single source of truth for contracts | Accepted |
| [0002](adr/0002-canonical-sequential-acquisition.md) | Canonical sequential acquisition for exclusive zones | Accepted |
| [0003](adr/0003-single-outstanding-grant.md) | At most one outstanding grant per robot, globally | Accepted |
| [0004](adr/0004-disjoint-zone-geometry.md) | Exclusive zones require disjoint protected geometry | Accepted |
| [0005](adr/0005-conservative-occupancy-retention.md) | Occupancy retained until a reconciled release | Accepted |
| [0006](adr/0006-safety-gate.md) | One veto gate in front of every actuator command | Accepted |
| [0007](adr/0007-canonical-clock-domains.md) | Five named clock domains; never subtract across them | Accepted |
| [0008](adr/0008-deterministic-and-process-modes.md) | Two honest execution modes, not one aspiration | Accepted |
| [0009](adr/0009-direct-peer-transport.md) | Direct framed TCP between agents; no broker | Accepted |
| [0010](adr/0010-role-based-access-control.md) | Trust model and threat boundaries | Accepted |
| [0011](adr/0011-event-sourcing-for-observability.md) | Append-only events as the observability substrate | Accepted |
| [0012](adr/0012-fair-baseline-evaluation.md) | Fairness of the stop-and-wait baseline is non-negotiable | Accepted |

---

## Summary of rejected alternatives

Recurring across the ADRs. Each was considered and rejected for a stated reason:

| Alternative | Rejected because |
|---|---|
| **Broadcast grant + total priority order** | Concurrent requests split durable grants across peers, so no robot can enter. Priority order does not fix it |
| **A central coordinator or MAPF solver in the backend** | Centralised planning presented as decentralised animation |
| **PIBT-style priority inheritance for exclusive zones** | Yields *within* a tick; confers no inter-tick exclusion. Would violate invariants 1 and 7 |
| **Deadlock detection with preemption** | Preempting a robot that is *physically inside* a zone is not safe |
| **Per-zone grant limit** | Does not remove cycles: two robots can each hold Z1 while seeking Z2, in opposite orders |
| **Timer-based occupancy expiry** | A crashed robot is still physically present; a timer moves a robot into an occupied aisle |
| **Majority-vote clearance** | A vote is not physical geometry |
| **Force-release on operator button** | No safe instantaneous state change exists |
| **Heartbeat as usable intent** | Liveness is not information |
| **Negative raw age treated as fresh** | A future timestamp means the clock relationship is unknown |
| **Safety checks inside the planner** | The planner optimises task completion; it has an incentive to be optimistic |
| **Safety checks in the world process** | The world would refuse colliding motion, concealing unsafe control |
| **Auto-migrating scenario schema versions** | A silent migration changes an experiment's meaning |
| **Silently repairing an invalid scenario** | The layout *is* the experiment |
| **Endpoint sampling for collision** | Opposing robots meet mid-tick with clear endpoints |
| **Inflating bodies to cover unsampled motion** | Conservative in the safety direction, but manufactures penetration out of real clearance |
| **Weakened baseline for a better headline** | Measures the handicap, not the policy |
| **Dropping failed seeds** | A timeout is what stop-and-wait does badly; dropping it hides the effect under study |
| **Imputing makespan for a deadlocked run** | A failure becomes a fast run |
| **Dogfooding a learned estimator in the safety path** | Learned predictions cannot override occupancy, authority, freshness or stopping checks |
| **GPU-accelerated 3D view before the core passes** | Decorative breadth before required depth |
| **Kubernetes / Kafka / a broker** | A coordination broker would contradict the decentralisation claim |

---

## Decision themes

Three patterns run through these ADRs, and they are the reason the system is
trustworthy rather than merely impressive:

**1. Structural removal over dynamic management.** Where a hazard could be detected
and handled (deadlock, overlap), it is instead made structurally impossible — a global
order, a single-outstanding-grant invariant, disjoint zone geometry. There is less
code and no recovery path to get wrong.

**2. Asymmetric failure is acceptable; symmetric confidence is not.** It is fine for the
safety gate to refuse a safe command (visible throughput cost). It is not acceptable
for the system to *confidently* believe an aisle is empty when it is not. Every choice
in this set follows from that asymmetry.

**3. Honest unavailability over plausible fiction.** A missing measurement is
`unavailable`, not `0`. An unexecuted Docker or ROS build is labelled unexecuted. An
unmeasured target is reported unmeasured. The project's credibility depends on its
claims being exactly as strong as its evidence.
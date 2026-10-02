# Architecture decision records

Each ADR states the decision, the alternatives that were rejected **with reasons**,
the consequences, and — importantly — **what would make us revisit it**. An ADR
without a revisiting condition is a decision no one is allowed to question, which
is not what this file is for.

| ADR | Decision | Status |
|---|---|---|
| [0001](adr/0001-canonical-json-schema-single-source.md) | Pydantic models are the single source of truth for contracts | Accepted |
| [0002](adr/0002-canonical-sequential-acquisition.md) | Canonical sequential acquisition for exclusive zones | Accepted |
| [0003](adr/0003-single-outstanding-grant.md) | At most one outstanding grant per robot, globally | Accepted |
| [0004](adr/0004-disjoint-zone-geometry.md) | Exclusive zones require disjoint protected geometry | Accepted |
| [0005](adr/0005-conservative-occupancy-retention.md) | Occupancy is retained until a reconciled release | Accepted |
| [0006](adr/0006-safety-gate.md) | One small veto gate in front of every actuator command | Accepted |
| [0007](adr/0007-canonical-clock-domains.md) | Five named clock domains; never subtract across them | Accepted |
| [0008](adr/0008-deterministic-and-process-modes.md) | Two honest execution modes, not one aspiration | Accepted |
| [0009](adr/0009-direct-peer-transport.md) | Direct framed TCP between agents; no broker | Accepted |
| [0010](adr/0010-role-based-access-control.md) | Trust model and threat boundaries | Accepted |
| [0011](adr/0011-event-sourcing-for-observability.md) | Append-only events as the observability substrate | Accepted |
| [0012](adr/0012-fair-baseline-evaluation.md) | Fairness of the stop-and-wait baseline is non-negotiable | Accepted |

---

## Summary of rejected alternatives

Recurring across the ADRs, these were considered and rejected:

| Alternative | Rejected because |
|---|---|
| **Broadcast grant + total priority order** | Concurrent requests split durable grants across peers, so no robot can enter. Priority order does not fix this. |
| **A central coordinator / MAPF solver in the backend** | Would be centralised planning presented as decentralised animation |
| **PIBT-style priority inheritance for exclusive zones** | Yields within a tick; confers no inter-tick exclusion. Would violate invariants 1 and 7 |
| **Timer-based occupancy expiry** | A crashed robot is still physically present. A timer would move a robot into an aisle someone is in |
| **Majority-vote clearance** | A vote is not physical geometry |
| **Force-release on operator button** | No safe instantaneous state change exists |
| **Heartbeat as usable intent** | Liveness is not information |
| **Negative raw age treated as fresh** | A future timestamp means the clock relationship is unknown |
| **Auto-migrating scenario schema versions** | A silent migration changes an experiment's meaning |
| **Silently repairing an invalid scenario** | The layout is the experiment |
| **Imputing makespan for a deadlocked run** | A failure becomes a fast run |
| **Endpoint sampling for collision** | Opposing robots meet mid-tick with clear endpoints |
| **Inflating bodies to cover unsampled motion** | Conservative in the safety direction, but manufactures penetration out of real clearance |
| **GPU-accelerated 3D view before the core passes** | Decorative breadth before required depth |
| **Dogfooding a learned estimator in the safety path** | Learned predictions cannot override occupancy, authority, freshness or stopping checks |
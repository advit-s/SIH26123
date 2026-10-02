# ADR 0002 — Canonical sequential acquisition for exclusive zones

**Status:** Accepted · **Date:** 2026-10-02
**Supersedes:** nothing · **Superseded by:** nothing

## Context

Warehouse aisles admit one robot. A robot therefore needs an explicit, durable right
to traverse a passage before it moves, and every peer must be able to see that right
so nobody enters against someone else.

The specification is explicit about the trap:

> *"Do not implement an incomplete broadcast-grant protocol and assume total priority
> order fixes it. Concurrent requests can split durable grants across peers so no
> robot can enter."*

A naive broadcast design has every robot simultaneously solicit every other robot.
With two concurrent requests R1 and R2 over zone Z, R1 may obtain a grant from peer A
while R2 obtains one from peer B. Neither has the complete set, so **neither may
enter**, and if A and B each hold a promise the deadlock is permanent without a
recovery mechanism. A total priority order does not help: priority governs *who goes
first*, not *who has collected a complete, non-conflicting set*.

## Decision

**Canonical sequential acquisition**, plus the single-outstanding-grant rule
([ADR 0003](0003-single-outstanding-grant.md)).

1. The admitted peer set is frozen per run epoch, with a **canonical order**:
   ascending `robot_id`. Every requester uses *the same* order.
2. A requester solicits voters **one at a time in that order**, waiting for each
   grant before asking the next.
3. The requester acquires **every** voter, **including its own local voter**, in its
   canonical position. It never pre-reserves its own grant.
4. A grant identifies `(run, epoch, zone, requester, requester_session,
   request_version)`. Any mismatch means the grant is for a different transaction
   and is refused, never coalesced.
5. The promise is **persisted before it is acknowledged**.
6. Entry requires the exact complete grant set, the requester's own still-live local
   state, durable commitment, current local safety checks, and no conflicting
   obligation it already holds.
7. `required_set_digest` must equal the owner-computed digest. A mismatch means
   entry is withheld.
8. Pre-entry cancellation is **durable at the owner first**, then reconciled with
   peers. A late grant can never revive a cancelled request.

## Why canonical order is what removes the deadlock

Two properties, and both are needed:

**A global total order admits no circular wait.** Because every requester walks
voters in the same order, two concurrent requests can never be "each waiting for a
voter the other already holds" in a cycle. At least one is always strictly ahead.
Contrast broadcast grant, where each holds a *different* subset and the cycle
closes.

**Including the requester's own voter closes the split.** Pre-reserving your own
grant is the specific mistake that recreates the cycle: R1 holds its own voter,
R2 holds its own, and each waits for the other's — an irreducible deadlock. Treating
the local voter as one more position in the order removes that case by construction.

## Consequences

**Accepted costs, stated rather than hidden:**

- **Serialisation.** Every acquisition is a round trip per voter. With N peers this
  is N sequential exchanges, so acquisition latency grows linearly with N. Measured,
  not asserted — see `docs/BENCHMARKS.md`.
- **Throughput bound.** [ADR 0003](0003-single-outstanding-grant.md) means a robot
  can hold only one grant globally. A traversal needing two adjacent resources with
  no berth between must be authored as **one compound zone**.
- **Availability, not safety, is the exposed dimension.** Safety holds under
  partitions, crashes, loss and reordering. What degrades is how many robots are
  moving at once.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Broadcast grant + total priority** | Split grants with no entry path. Explicitly called out by the brief. |
| **Pre-reserve own grant, then broadcast** | Recreates the two-holder cycle through the local voters. |
| **PIBT / priority inheritance** | Yields *within* a tick; confers no inter-tick exclusion. Cannot express durable authority. Research also records that PIBT's deadlock-freedom does not extend to dead-end topologies, which warehouse aisles are. |
| **Consensus-based (CBFA-style) consensus** | Heavier than needed for N ≈ 3–8; adds phases without removing the grant-splitting problem, which the global order already removes. |
| **Surplus / redistribution auction over zones** | No retrievable primary source was found during research, so it cannot be implemented honestly. Recorded in `docs/RESEARCH.md` rather than half-built. |
| **Central coordinator in the API** | Would be centralised coordination presented as decentralised. |
| **Optimistic entry, retract on conflict** | Undetectable mid-zone conflicts produce exactly the unsafe motion this project exists to prevent. |
| **Token passing / ring ordering** | Physically correct but brittle to crashes: a dead token-holder freezes the ring. |

## Revisiting condition

Revisit if **either**:

1. Measured acquisition latency (voters × round trip) dominates makespan at the
   target fleet size. Then consider a two-phase prepare/commit variant, which keeps
   the global order but overlaps the round trips. It must preserve the
   no-split-grant property and would need its own interleaving tests.
2. Maps are authored requiring genuinely overlapping zones. Then the disjointness
   requirement must be replaced by a complete, enforced conflict set — validated at
   import **and** at admission, since two different zone ids must never authorise
   physically conflicting movements.

In both cases the disjointness and single-outstanding-grant invariants are
non-negotiable. Any variant that weakens them is a different protocol and needs its
own ADR plus a fresh independent review.

## Verification

- `tests/protocol/test_acquisition.py` — happy path, correct rejection reasons
- `tests/protocol/test_split_grant.py` — split partial acquisition resolves
- `tests/protocol/test_cancellation.py` — **late grant after durable cancellation**
- `tests/protocol/test_interleavings.py` — bounded exhaustive message permutations
- `tests/protocol/test_restart_recovery.py` — durable promise survives reboot
- `docs/protocol/ZONE_PROTOCOL.md` — full state and transition tables
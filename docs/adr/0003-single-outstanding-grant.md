# ADR 0003 — At most one outstanding grant per robot, globally

**Status:** Accepted · **Date:** 2026-10-02

## Context

[ADR 0002](0002-canonical-sequential-acquisition.md) removes the *split grant* form of
deadlock by giving every requester one global acquisition order. But that alone does
not remove every wait-for cycle: a robot that already holds zone Z1 and then seeks
zone Z2 holds a grant while waiting, and another robot holding Z2 while seeking Z1
closes a cycle.

The tempting fix is deadlock detection plus recovery — wait-for-graph analysis,
timeouts, preemption. That is a large, subtle, hard-to-test surface, and preemption
of a robot that is *physically inside* a zone is not safe at all.

## Decision

**A robot owes at most one grant globally, across all zones, at any time.**

Enforced in the voter: a coordinator that already owes a grant anywhere rejects a new
solicitation with `RejectionReason.GRANT_HELD`. The robot must complete or durably
cancel its outstanding grant before soliciting another.

This is a single invariant, not a protocol phase.

## Why it is sufficient

Model the fleet as a wait-for graph: an edge `A → B` means A is waiting for B to
respond, because A holds an outstanding grant or B owes A one.

**Claim.** In any wait-for cycle, every robot on the cycle simultaneously owes a
second grant, contradicting the invariant.

*Proof sketch.* Consider a cycle `A₁ → A₂ → … → Aₙ → A₁`. Each edge means the
predecessor is blocked on the successor. By the canonical order of
[ADR 0002](0002-canonical-sequential-acquisition.md), solicitation proceeds strictly
in one global sequence. If Aᵢ is blocked waiting for Aᵢ₊₁, then Aᵢ already owes a
grant for the zone it is currently acquiring. For the cycle to close, Aᵢ₊₁ must also
be blocked on a grant, so it too owes one. Every node on the cycle therefore owes a
grant *and* is waiting to acquire another. That is two outstanding grants for a robot
whose invariant permits one. ∎

Consequently: **no cycle exists**, so no deadlock exists among healthy robots. There
is nothing to detect and nothing to recover from, because the possibility has been
removed structurally rather than managed dynamically.

The result is: *order-inversion-free*, i.e. no circular wait — **not** "deadlock-free
in all circumstances". See the liveness section below.

## Consequences

### Safety

Holds under partitions, message loss, duplication, reordering and clock skew. These
change *whether messages arrive*, never *the order in which authority is granted*.

### Liveness — what is explicitly NOT guaranteed

1. **A robot that fails while holding a grant blocks its zone indefinitely.** The
   zone moves to `FENCED` and stays unavailable until a supervised transition.
   **This is deliberate.** The failed robot may be physically inside that aisle.
   There is no safe instantaneous recovery, so none is offered.
2. **A slow voter blocks the queue behind it.** Acquisition is serial, so one
   unresponsive peer stalls every subsequent requester. This is an availability cost
   and is measured.
3. **Bounded progress requires bounded per-request work.** Under a reliable
   non-partitioned network with no failures and bounded response times, a queued
   requester eventually acquires and traverses. Testable, and tested.

The asymmetry is the point: **a protocol that guarantees progress by relaxing safety
is not an acceptable trade**, and this one does not make it.

## Practical requirement

Because a robot holds at most one grant, a traversal needing two adjacent resources
with **no safe berth between them** must be authored as **one compound zone**
(`Zone.members`). Otherwise the robot would hold Z1 while waiting for Z2, which is
precisely what the invariant forbids.

This is why the authored map lattice places every zone beside a single shelf row, so
consecutive zones along an aisle are always separated by a full cross aisle — a safe
place to stop. `validate_berth_separation` and `validate_zone_disjointness` enforce
this at authoring time.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Wait-for-graph detection + recovery** | Large, subtle, and recovery of a robot physically inside a zone is not safe. Structural removal is strictly better where it applies. |
| **Preemption / pre-emptive priority** | Cannot safely preempt a body inside a zone. |
| **Per-zone grant limit** (one grant *per zone*, several across zones) | Does not remove cycles: two robots can each hold Z1 while seeking Z2, in opposite orders. |
| **Timeout-based forced release** | Moves a robot into an aisle someone still occupies. |
| **Multiple outstanding grants with a reservation table (SIPP-style)** | Sensible for a single centralised planner. Here it reintroduces the cycle this invariant eliminates. |

## Revisiting condition

Revisit only if **all three** hold:

1. Measured wait time under the single-outstanding-grant rule is dominated by
   *grant bookkeeping* rather than by genuinely contended passages, **and**
2. the fleet target exceeds roughly 16 robots, where serialised acquisition becomes
   the bottleneck rather than the contention, **and**
3. a concrete alternative exists that preserves the safety argument — most likely a
   *partial-order* scheme with a proven cycle-free property, not a priority queue.

Any replacement must pass the bounded exhaustive interleaving suite and receive an
independent review before it replaces this rule. Relaxing it silently is forbidden.

## Verification

- `tests/protocol/test_interleavings.py` — for every enumerated message permutation,
  assert (a) no two robots hold executable authority over one zone, and (b) no robot
  holds two outstanding grants. **The bound is stated in the test and in
  `docs/protocol/ZONE_PROTOCOL.md`; bounded tests are not an unbounded proof.**
- `tests/protocol/test_split_grant.py` — split acquisition resolves without a cycle
- `tests/protocol/test_restart_recovery.py` — a rebooted voter still owes its promise
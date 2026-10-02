# ADR 0003 — One outstanding grant per robot, globally

- Status: **accepted**
- Date: 2026-10-02
- Decides: the invariant that makes the zone protocol deadlock-free, and the
  fairness queue that keeps it usable
- Spec: [`docs/protocol/ZONE_PROTOCOL.md`](../protocol/ZONE_PROTOCOL.md)
- Related: [`0002-canonical-sequential-acquisition.md`](0002-canonical-sequential-acquisition.md)
- Team: NihāraNetra · Problem SIH26123

## Context

`AGENTS.md` invariant 6 states it in one line:

> **One outstanding grant per robot.** Zone grants are acquired in canonical peer
> order by every requester, including its own local voter. Never pre-reserve
> your own grant.

`domain/coordination.py` states the enforcement direction:

> `RejectionReason.GRANT_HELD` - *"This voter already owes an outstanding grant
> somewhere. The single-outstanding-grant rule is what makes wait-for graphs
> acyclic."*

This ADR fixes the precise meaning of both, the proof, the fairness mechanism that
the proof alone would starve, and what is **not** guaranteed.

## Decision

### 1. The rule

> A robot holds at most one outstanding grant, globally, across all zones.

Enforced at two independent points:

- **Owner side** (`ZoneRequester.begin`). A robot with a non-terminal transaction
  cannot start another walk, whatever the zone. The call raises
  `RuntimeError("… invariant 6 permits one outstanding grant globally")`. There is
  no queue of pending requests inside one robot: the planner and the task auction
  decide what to ask for next.
- **Voter side** (`ZoneVoter.solicit` → `GRANT_HELD`). A voter that already owes
  *this requester* an outstanding promise refuses a new solicitation from that
  requester. This is the cross-check, and it is also what the domain module's
  docstring describes.

Both sides matter. The owner side is the discipline; the voter side is what makes
the discipline *checkable by someone who does not trust the owner*.

### 2. Why it is needed

Without it, a robot could hold grants for two zones at once. In a future where
zones may overlap (the brief allows overlapping zones behind a complete conflict
set), two robots holding two zones each in opposite order would form a classic
2-cycle:

```
r1 holds {A, B?}   r2 holds {B, ?}
```

Even today the rule removes a whole class of future hazards for the cost of one
round of parallelism, which the A/B measurement has not yet shown to be worth
giving up.

### 3. The proof of deadlock-freedom

`ZoneProtocol.wait_for_graph()` publishes at most one edge per robot:
`robot → the voter it is waiting on`, and **only while it holds at least one
grant**. A robot that is merely queued behind somebody blocks nobody, so it
publishes no edge. `detect_wait_for_cycle` walks the published graph.

**Claim.** The published wait-for graph is acyclic.

**Proof.** Suppose a cycle exists and let `W` be the robot in the cycle whose
blocking index `k` - the canonical index of the voter it is waiting on - is
smallest.

1. `k > 0`. A robot waiting on `c_0` holds nothing, so it publishes no edge and
   cannot be in the cycle.
2. `W` waits on `c_k`, so `W` holds promises from `c_0 … c_{k-1}`, and therefore
   holds `c_0`'s promise for its own zone `Z_W`. By P1, `c_0` promised `Z_W` to
   `W` and to nobody else.
3. Follow `W`'s blocker: `c_k` owes a promise to some requester `Y` (for `Z_W` or
   for another zone). `Y` obtained `c_0 … c_k` in order, because a walk is
   sequential. So if `Y` is itself blocked, its blocking index is `> k`.
4. Iterating along the cycle produces a strictly increasing sequence of blocking
   indices inside a finite totally ordered set. Impossible. ∎

The detector exists to **disprove** this claim from observed edges, not to recover
from a deadlock: the operator/API layer calls it with the edge each robot
publishes, and a non-`None` result is a protocol defect to be investigated.

### 4. What the proof does *not* say

- It says nothing about a robot that stops answering. That is a partition or a
  failure, reported as `partition_stop` / `starvation_suspected`, not a deadlock.
- It says nothing about *liveness*. Acyclicity plus fairness gives progress; the
  fairness mechanism is section 6, and the assumptions are ZONE_PROTOCOL.md §11.
- It is a statement about the **published** graph. A robot publishes an edge only
  while holding a grant, by design: publishing an edge for a merely queued robot
  would create false cycles (`r1` waiting on `r2`, `r2` queued behind `r1`) for
  a situation that resolves as soon as `r1` releases. That mistake was made
  during implementation and is why the rule is written down here.

### 5. Interaction with per-zone exclusivity

P1 (a zone is promised to at most one transaction) is a different rule and does
not follow from this one. They are independent:

| Rule | Scope | Refusal |
|---|---|---|
| P1 | (voter, zone) | `ZONE_PROMISED` |
| P2 | (voter, requester) - this ADR | `GRANT_HELD` |
| P3 | (robot) - this ADR | `RuntimeError` from `begin` |

ADR 0002 §3 shows that P1 alone, combined with the canonical order, already makes
split grants unreachable. P2/P3 add the discipline that keeps one robot from
accumulating obligations.

### 6. The fairness queue (and why it is not optional)

The proof above gives deadlock-freedom and nothing else. Measured behaviour
without a fairness queue was **starvation of the lowest-index robot's peers**:

> Every walk begins at `c_0`. The robot whose `robot_id` *is* `c_0` reaches its
> own voter in-process, with zero round trips, while every other robot needs at
> least one. It therefore won every race.
> `tests/protocol/test_acquisition.py::test_progress_a_queued_requester_eventually_acquires_and_traverses`
> failed with `only ['r1'] traversed within 600 steps`.

The fix is a bounded, in-memory, per-voter, per-zone FIFO queue:

- a refused requester joins the queue and is told its position;
- when the zone is free, the voter serves the **queue head**, not whoever arrived
  first;
- a retry keeps the position it already had - otherwise a robot loses its place by
  being slow, which is the unfairness the queue exists to remove;
- an entry expires after `4 × solicit_timeout_s`.

**The queue is not authority.** An entry does not reserve the zone, never
overrides a promise already issued, and never reorders issued authority. It only
decides who is served *next* among requesters who all lack the full set.

**The TTL expires permission to assume, not occupancy.** A queue head whose robot
died stops blocking the head of the line after `4 × solicit_timeout_s`. This is
the one timer in the protocol that expires something, and what it expires is the
*assumption* that the head will return. It can never clear a zone, release a
promise, or un-grant anything: those require a reconciled message or an authorised
fence.

**Backoff.** A refused requester retries after
`solicit_timeout × 2^min(refusals, 3) × (1 + stable_offset(txn) mod 3)`. The
per-transaction offset is deterministic, so two robots refused in the same instant
do not re-race in lockstep, and a replayed run reproduces the same schedule.

### 7. Starvation-freedom: what is and is not claimed

**Claimed.** Within one voter's view, service is FIFO by arrival, and a requester
that keeps its queue entry is served when the zone next becomes free.

**Not claimed.** Starvation-freedom against an adversary that re-requests faster
than any robot can complete a traversal. Such a robot keeps the zone permanently
busy and every other requester waits. The protocol does not hide this: after three
refusals the blocking report becomes `starvation_suspected` (a named holder is
making progress without this robot) or `livelock_suspected` (refusals with no
holder at all). The operator sees which.

### 8. Honest cost

- A robot traversing a zone cannot also hold another, even a disjoint one. Two
  robots can still traverse two *different* zones concurrently.
- The rule is a hard refusal, not a queue. A robot with an outstanding grant that
  wants a second zone must cancel first. That is intentional: a queue inside one
  robot would be a second allocation problem, and the task auction already
  decides what a robot should be doing.
- `GRANT_HELD` is only reachable for the *same* voter, because a voter cannot see
  what another voter owes. That is why the owner-side rule exists and why both are
  tested.

## Verification

| Claim | Where |
|---|---|
| the owner refuses a second walk | `test_acquisition.py::test_second_concurrent_acquisition_is_refused_locally`, `tests/property/test_protocol_state_machine.py::test_an_owner_never_starts_two_walks` |
| the voter refuses with `GRANT_HELD` | `test_restart_recovery.py::test_clean_restart_with_an_outstanding_promise_does_not_forget_it` |
| the published graph is acyclic, checked after **every** delivery | `test_interleavings.py`, `tests/property/test_protocol_state_machine.py` |
| a cycle *is* detected when one is planted | `test_split_grant.py::test_wait_for_graph_is_acyclic_under_contention` |
| all three robots traverse within a bounded step count | `test_acquisition.py::test_progress_a_queued_requester_eventually_acquires_and_traverses` |

## Alternatives considered

- **Relax P2 to (voter, zone) pairs**, i.e. a voter may owe several robots promises
  for several zones at once. This is the provably safe relaxation and it does allow
  more parallelism. It was **not** enabled because the domain module's own
  docstring - the authoritative contract - specifies "somewhere", and because a
  per-robot limit is the invariant the project brief asks for. The relaxation's
  precondition is that P3 (the owner-side rule) is enforced everywhere, since P2
  is then no longer a complete check. Recorded here so the option is visible.
- **Drop the rule and rely on disjoint zone geometry.** Rejected: the brief
  explicitly allows overlapping zones behind a complete conflict set in future
  work, and the rule is what keeps that extension safe.
- **Make the rule per-robot-per-zone** (one grant per zone, several zones at once).
  Rejected: that is not invariant 6, and it re-opens the 2-cycle in section 2.

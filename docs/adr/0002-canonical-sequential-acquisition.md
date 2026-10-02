# ADR 0002 — Canonical sequential acquisition of exclusive zones

- Status: **accepted**
- Date: 2026-10-02
- Decides: the algorithm for obtaining exclusive authority over a warehouse zone
- Spec: [`docs/protocol/ZONE_PROTOCOL.md`](../protocol/ZONE_PROTOCOL.md)
- Team: NihāraNetra · Problem SIH26123

## Context

Warehouse AMRs must not enter a narrow aisle or a junction while another robot is
inside it. Every robot therefore needs exclusive authority over a *zone* before
it crosses the zone's stop line, and the decision must be made without a central
coordinator: the project brief forbids "a centralized MAPF solver run in the
backend and described as decentralized robot planning", and `AGENTS.md` invariant 1
forbids the API from coordinating at all.

The brief also carries an explicit warning that shaped this decision:

> *"Do not implement an incomplete broadcast-grant protocol and assume total
> priority order fixes it. Concurrent requests can split durable grants across
> peers so no robot can enter."*

So the requirements are:

1. no central arbiter;
2. no state in which two robots believe they may enter the same zone;
3. no state in which two robots each hold part of a grant set and neither can
   enter - the "split grant" failure;
4. a promise must survive the death of the process that made it;
5. a lost heartbeat must not empty an aisle;
6. every important decision must be inspectable and explainable.

## Decision

**Canonical sequential acquisition.** The admitted peer set comes from
`Membership`; canonical order is ascending `robot_id`. Every requester acquires
**every** voter, including its own local voter, in that one global order, one
outstanding solicitation at a time.

Three properties follow immediately, and together they are the whole safety
argument:

- **Single serialisation point.** Every walk starts at canonical index zero. That
  voter owes at most one promise per zone, so at most one requester can ever hold
  a partial set for that zone. Two robots cannot both hold a complete set,
  because a complete set contains index zero.
- **No split grant.** Since only one requester can hold index zero, no second
  requester can obtain *any* later index for the same zone. A requester that is
  refused holds nothing at all.
- **Durable, restorable promises.** Every voter journals the promise before
  acknowledging it, so a reboot restores the record instead of forgetting it and
  resuming to vote.

The requester's own voter is **not** privileged. For the robot at canonical index
zero it happens to be `slot[0]`, handled in-process by the same `ZoneVoter.solicit`
code with the same checks, the same journal append and the same refusal reasons.
There is no `pre-reserve your own grant first` branch anywhere in the
implementation, and
`tests/protocol/test_split_grant.py::test_every_walk_starts_at_canonical_index_zero_including_the_self_voter`
asserts that the walk order is literally `membership.order()` for every requester.

## Alternatives considered

### A1 — Broadcast grant (all voters answer every request)

*Rejected.* This is the failure the brief names. With a broadcast, two robots can
each receive a partial set, and with a total priority order the loser refuses to
release, so **no robot can enter**. Adding a total order on top does not fix it:
the loser's promise is already durable, and revoking it would break the durability
guarantee that makes the protocol safe at all. Rejected on the brief's own
grounds.

### A2 — Ricart–Agrawala with timestamps

*Rejected, and deliberately not renamed.* Its deadlock-freedom argument depends on
a shared total order over requests and on deferring only to *earlier* requests; a
requester holding the token must not be starved out by later arrivals. That is a
genuine algorithm, but it grants CS permission to **all** members rather than
demanding every member's promise, so a robot whose voter is partitioned can be
blocked by an absent peer with no explicit "who is holding what" record. It also
requires a queue per process whose ordering is only as good as the timestamp
comparison, and it does not by itself give the per-zone durable occupancy record
this project needs for conservative retention. Naming a custom mixture of it was
explicitly ruled out.

### A3 — Token / lock service per zone (a designated holder)

*Rejected.* Safe and simple, but it puts the authority decision in one process,
which contradicts invariant 1 and turns a single robot failure into a single-zone
outage. It also has to be replicated to be useful, which is a different
distributed-systems problem with its own failure modes.

### A4 — Total-priority-order bakery algorithm (Lamport)

*Rejected.* Lamport's bakery gives mutual exclusion with a *shared* ordering
computed from every process's latest choosing number. It requires every process to
maintain state for every other process, and choosing a number requires reading
everyone's state - i.e. a broadcast per acquisition. It is also a mutual-exclusion
primitive, not a durable, restartable, zone-scoped authority: after a crash the
bakery state is gone and must be reconstructed, and the "holder" has no durable
record that a peer could have relied on.

### A5 — Two-phase locking, zones ordered globally

*Rejected.* Requires a global order over *all* resources, not just zones, and
holds locks across the whole traversal. Two robots each holding disjoint zones
would still block each other. It also has no natural place for the durable
occupancy record.

### A6 — Quorum / majority grant

*Rejected on safety grounds.* A majority vote is not physical clearance. A quorum
of 2 of 3 can grant a zone while the third robot is physically inside it.

## Consequences

**Good**

- Split grants are unreachable among conforming requesters, and the argument is
  three sentences long enough to audit.
- Every refusal is explicit and carries a `RejectionReason`; a requester never has
  to guess whether silence meant refusal or partition.
- Every promise is durable before it is acknowledged, so a reboot never forgets
  one.
- Occupancy retention and fencing compose naturally: the record that makes a zone
  `OCCUPIED` is the same record that a fence terminates.
- Deadlock-freedom follows from the canonical order plus one outstanding grant per
  robot (ADR 0003), so there is no deadlock detector in the motion path.

**Bad, and stated rather than hidden**

- **`n` round trips per acquisition.** For the robot at canonical index zero,
  `n-1`, because its own voter answers in-process.
- **The fleet serialises per robot.** A robot traversing a zone cannot also hold
  another, even a disjoint one (invariant 6).
- **Canonical index zero is a hot spot** for every zone.
- **A forged request can split a zone**, because a voter cannot see another voter's
  record. The consequence is fail-stop (nobody can enter), not unsafe motion; see
  ZONE_PROTOCOL.md §6.3 and the test that asserts it.
- **Throughput is bounded by the slowest zone.** A zone whose holder fails blocks
  until an operator fences it.

## Verification

| Claim | Where |
|---|---|
| split grants impossible | `tests/protocol/test_split_grant.py` |
| the self voter is step zero of the shared order | `tests/protocol/test_split_grant.py::test_every_walk_starts_at_canonical_index_zero_including_the_self_voter` |
| 720 orderings preserve both invariants | `tests/protocol/test_interleavings.py` |
| arbitrary message sequences preserve the safety invariants | `tests/property/test_protocol_state_machine.py` |
| bounded progress under healthy conditions | `tests/protocol/test_acquisition.py::test_progress_a_queued_requester_eventually_acquires_and_traverses` |

## Notes

- An **ordering cost** was found empirically, not on paper. Every walk starts at
  index zero, so the robot at index zero reaches the first voter with zero round
  trips while everybody else needs one. Without a fairness queue it therefore won
  every race and monopolised the zone; the progress test failed with only one of
  three robots ever traversing. The fix, and why it is bounded, is ADR 0003 §6.

# ADR 0005 — Conservative occupancy retention

**Status:** Accepted · **Date:** 2026-10-02

## Context

A robot inside an aisle holds the zone. What happens if its release message is lost,
its heartbeat stops, or the network partitions mid-traversal?

The tempting default is a timeout: after *T* seconds without contact, assume the zone
is free and unblock the queue. This is the mechanism behind most real-world warehouse
near-miss incidents, and it is wrong.

## Decision

**A zone moves out of `OCCUPIED` only on a reconciled release message.**

Specifically:

1. `RELEASED` is not effective on send. It becomes effective only when **every**
   voter has reconciled the matching `ZoneReleaseBody`.
2. A **lost heartbeat, a timeout, a missing release, or a majority vote does not free
   an aisle.** A vote is not physical geometry.
3. When a holder fails, the zone transitions to `FENCED` — explicitly unavailable,
   visibly reported, and requiring a supervised operator transition.
4. **There is no force-release message and no force-release UI control.** There is no
   safe instantaneous state change, so none is offered.
5. The owner's assertion that it has achieved full inflated-body clearance is recorded
   as **evidence**, not accepted as clearance. Peers reconcile; they do not trust.

The asymmetry this preserves:

> **Freshness expiry removes *permission to assume*, never *physical occupancy*.**

A robot may become so uncertain that it must refuse to *start* a traversal. It may
never conclude that another robot has *left* one.

## Consequences

### Accepted costs

- **A crashed robot blocks its zone until fenced.** Availability loss, deliberately
  chosen.
- **Recovery is an operator action**, not automatic. This is a feature: automatic
  recovery from an unknown physical state is the thing we are avoiding.
- **Fenced zones accumulate** in long runs with crashes. The doctor and zone inspector
  surface them so they are visible rather than quietly stranding throughput.

### What makes this acceptable

The failure this prevents is the severe one. A timeout-based release does not merely
risk a collision — it produces a **confident wrong belief** that another robot is
gone, and the system's own safety gate will then permit motion on the strength of
that belief. Converting an unknown into a known-looking value is how a distributed
system loses its safety argument while still reporting green.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Timeout-based occupancy expiry** | A crashed robot is still physically there. Turns an unknown into a false certainty. |
| **Majority-vote clearance** | Three robots agreeing that an aisle is empty does not make it empty. |
| **Heartbeat-derived clearance** | Heartbeat is *liveness*, explicitly not usable information. |
| **Automatic recovery on holder restart** | The restarted robot cannot prove it is not still occupying the zone, nor that it did not move while "down". |
| **Operator force-release button** | There is no safe instantaneous transition. A button would invite a routine, unguarded unsafe action. |
| **Fenced zone re-opened automatically after a grace period** | Same failure as a timeout, with extra steps. |
| **Let the owner self-declare clearance** | The owner is the least reliable witness to its own physical state; peers reconcile independently. |

## Implementation notes

- `ZoneState`: `FREE` · `PROMISED` · `OCCUPIED` · `FENCED`
- Release reconciliation is tracked per voter; the zone frees only at the last one.
- `ZoneFenceBody` carries `operator_authorised`, so a fence is visibly an operator act
  and not an automatic system behaviour.
- Fencing is a first-class state in the UI, not an error toast.

## Revisiting condition

Revisit if a **formal** recovery procedure exists that provably restores safety
without relying on a timeout — for example a physical confirmation mechanism
(dock-locked presence, a floor sensor in the aisle) that is not a network timeout.
That would change the information available, not the safety requirement.

Revisit if the measurement shows fenced zones dominate lost throughput across many
faulted runs **and** a bounded, operator-supervised recovery procedure is available
that is strictly safer than the current state. Merely wanting the throughput back is
not a reason.

Any change here is a safety-critical change and requires independent review before
merge, plus a regression test added **before** the fix.

## Verification

- `tests/protocol/test_release_reconciliation.py::test_lost_release_does_not_free_the_zone`
- `tests/protocol/test_restart_recovery.py` — corrupt journal → grants nothing
- `tests/protocol/test_cancellation.py` — occupancy retained across a cancelled request
- `src/niharamesh/domain/coordination.py` — no force-release message type exists
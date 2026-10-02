# ADR 0010 — Trust model and threat boundaries

**Status:** Accepted · **Date:** 2026-10-02

## Context

This is a **local laboratory application**. Over-engineering it into an identity
platform would waste the time available for the coordination protocol, which is the
thing under review. But under-engineering it is worse: a spoofed grant message that
is accepted as ordinary state would void the entire safety argument.

The threat model therefore has to be explicit about what is *not* defended.

## Decision

### What is trusted

| Subject | Trusted with |
|---|---|
| The local operator | Launching runs, injecting faults, requesting controlled stops |
| The immutable shared map | Read-only geometry, available to every agent |
| Each agent's own journal | Its own promises and custody |

### What is not trusted

| Subject | Explicitly not trusted with |
|---|---|
| Peer agents | Each other's **claims** — every state and intent message is validated on receipt |
| Imported scenario files | Any authority; they are validated, then merely data |
| API payloads | Filesystem paths outside the scenario root |
| The browser | Any actuator command |
| Timers | Any claim about physical occupancy |

### Validation performed on every peer message

`run_id`, `epoch`, `sender`, `sender_session`, `schema_version`, `protocol_version`,
`seq` (within a bounded replay window), `time_domain`, `map_digest`, validity horizon.

A message failing any check is **refused with a specific `RejectionReason`**, never
coalesced with a valid one. Spoofed and replayed messages must not be accepted as
ordinary state; that is the concrete requirement.

### Network posture

- Every service binds **`127.0.0.1`** by default. There is no `0.0.0.0` anywhere.
- CORS origins are explicit; empty means same-origin only. No wildcard.
- WebSocket origins are validated on upgrade.
- Non-loopback binding requires an **explicit** configuration *and* an operator
  token. Without a token the application refuses to serve off-loopback rather than
  serving unauthenticated.

### Parsing posture

No `pickle`, no `yaml.load`, no `eval`, no `marshal`, no untrusted object
deserialisation anywhere. JSON only. Unknown fields are rejected, not ignored.
Framed reads validate the declared length against a maximum **before** allocating.

## What is explicitly NOT defended

1. **Byzantine peers.** A compromised agent can lie consistently about its own
   behaviour. The system refuses replayed and mismatched messages; it does not detect
   a peer fabricating plausible state throughout.
2. **Rate limiting.** Absent, and appropriate only for loopback. A non-loopback
   deployment needs a reverse proxy with limits.
3. **Malicious scenario authoring.** Anyone who can write a scenario file can author a
   scenario. Validation prevents *invalid* layouts; it cannot prove a layout safe.
4. **`Idempotency-Key` as authentication.** It prevents accidental duplication. It does
   not prove the caller is authorised.
5. **Physical actuation.** Out of scope for the API entirely — there is no endpoint
   that reaches hardware.

## Consequences

The security effort went into **boundedness and honest rejection** rather than into
cryptography. In practice this means: a peer that floods cannot exhaust a robot's
memory, a peer that stalls is reported as `connected_silent` rather than healthy, and
a message from a rebooted robot is refused rather than merged.

The boundedness work has a second benefit. The primary adversary in a fleet
demonstration is a **buggy or misconfigured peer**, not an attacker, and bounded
queues plus explicit rejection are exactly what makes a misbehaving peer diagnosable.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Full identity provider** | Enormous scope for a loopback tool; would consume time better spent on the protocol |
| **mTLS between agents** | Realistic for a deployed fleet, disproportionate here. The identity check that matters is *session and epoch validation*, not transport encryption |
| **Signed manifest / vote signatures** | Byzantine defence without a stated adversary model is complexity with no threat it addresses |
| **Trust-and-allow on the peer channel** | Directly contradicts the invariant that a spoofed release message must not be accepted as ordinary state |
| **Rejecting all `localhost` traffic** | Would break the demonstration entirely |

## Revisiting condition

Revisit if any of these becomes true:

1. The application is exposed beyond a controlled network. Then mTLS or at minimum
   authenticated transport, plus rate limiting, become mandatory — not optional.
2. Fleet size grows past the point where a peer's compromise is materially dangerous.
3. A Byzantine-defence requirement appears with a real adversary model. Until then,
   Byzantine claims are not made.
4. Physical actuation is enabled. Then the actuation boundary needs its own threat
   model, separate from this one, reviewed independently.

Full detail: `docs/SECURITY.md`.
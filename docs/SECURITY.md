# Security model

Scope: a **local laboratory application** running on a developer machine or a
controlled demo network. This document states the boundary honestly rather than
implying a security posture the project does not have.

**NĪHĀRAMESH is not an industrial safety system and claims no certification.** No
software collision monitor in this project — including the ones it borrows concepts
from — substitutes for a certified safety function.

---

## 1. Trust model

| Component | Trusted with | Explicitly not trusted with |
|---|---|---|
| The operator at the keyboard | Launching runs, injecting faults, controlled stops | Physical actuation, which requires separate authorisation |
| Peer agents on the same loopback | Their own identity, boot session and admission | Each other's *claims* — every intent and state message is validated before use |
| Imported scenario files | Nothing until validated | Any authority whatsoever |
| Imported API payloads | Nothing until validated | Filesystem paths outside the scenario root |
| The browser | Display and read access | Any actuator command |

A local prototype need not solve Byzantine consensus. What it **must** do is refuse
spoofed or replayed protocol messages as ordinary state — and it does, because
every message carries `run_id`, `epoch`, `sender`, `sender_session` and a monotonic
`seq`, all checked on receipt.

---

## 2. Network exposure

### Loopback by default

All services bind `127.0.0.1` by default:

| Service | Default bind |
|---|---|
| Application API | `127.0.0.1:8100` |
| Web dev server | `127.0.0.1:5173` |
| Every agent peer socket | `127.0.0.1`, one distinct port per robot |

There is no `0.0.0.0` anywhere in the source. Binding to a non-loopback interface
requires an **intentional** configuration change and is documented as changing the
threat model.

### CORS and WebSocket origins

CORS origins are explicit (`NIHARA_CORS_ORIGINS`); the default is empty, meaning
same-origin only. WebSocket origins are validated on upgrade. There is no wildcard.

### Non-loopback mode

Enabling it requires:

1. an explicit `NIHARA_BIND_HOST` change,
2. `NIHARA_OPERATOR_TOKEN` set to a real secret,
3. operator acknowledgement that the host is now on an untrusted network.

Without a token, the application refuses to serve on a non-loopback interface
rather than serving unauthenticated.

---

## 3. Authentication

Deliberately minimal, because a local laboratory application should not become an
identity-management product.

| Situation | Control |
|---|---|
| Loopback, default | None. Bound to loopback, which is the boundary. |
| Non-loopback | Optional bearer token (`NIHARA_OPERATOR_TOKEN`) |
| Mutating API calls | `Idempotency-Key` required, so retries cannot duplicate runs, tasks or faults |
| Physical actuation | Separate explicit gate — not reachable from the API at all |

`.env.example` contains **placeholders only**. Real credentials belong in `.env`,
which is gitignored. `.env.example` is never edited to carry a secret.

---

## 4. Input validation and parsing

| Control | Implementation |
|---|---|
| Every domain model | Pydantic v2, `extra="forbid"`, frozen, bounds on every numeric field |
| NaN / infinity | Rejected at the boundary (`allow_inf_nan=False`, plus explicit validators) |
| Oversized payloads | Framed reads check the declared length against `max_bytes` **before** allocating |
| Message size | Capped (256 KiB default); larger messages refused with a stable error code |
| Unknown fields | Rejected, never ignored — a silent drop is how critical protocol fields get lost |
| Schema versions | Incompatible versions **refused**, never auto-migrated |

### Unsafe deserialisation: none

There is **no** `pickle`, no `yaml.load`, no `eval`, no `marshal`, and no
untrusted object deserialisation anywhere in the project. Scenarios and events are
JSON only. This is a hard rule, not a style preference.

---

## 5. Filesystem safety

| Risk | Control |
|---|---|
| Path traversal | `resolve_scenario_path` resolves symlinks, then requires the result to be inside the scenario root. `PathEscape` otherwise |
| Arbitrary write | Output filenames are generated from validated identifiers, then resolved through the same guard |
| Partial writes | Write to `.tmp`, then atomic rename |
| Unbounded files | 4 MiB scenario limit, checked before parsing |
| Run artefact bloat | Bounded retention; `prune_before` refuses to delete authority/custody records |
| Deletion | There is no "clean unknown files" path. Nothing deletes outside its own run directory |

---

## 6. Secrets

- `.env` is gitignored. `.env.example` holds placeholders.
- Certificates and keys (`*.pem`, `*.key`, `*.crt`, `*.keystore`, `certs/`) are
  gitignored.
- Secrets are not logged. Error responses carry a stable code, a message and a
  correlation id — never an internal stack trace or environment dump.
- `nihara doctor` prints tool versions, paths and build identity. It does **not**
  print environment variables or token values.
- Stack traces are opt-in via `NIHARA_TRACEBACK=1`, so a user-facing failure is
  actionable without dumping internals into logs.

---

## 7. Command injection

Every subprocess is spawned with an **argument array**, never a shell string, with a
short timeout and a captured result. Tool discovery uses `shutil.which`. No user
input reaches a shell.

---

## 8. Denial of service within the trust boundary

The interesting adversary is not an external attacker but a **misbehaving or buggy
peer**, so the focus is on boundedness:

| Resource | Bound |
|---|---|
| Frame length | Declared length checked against `max_bytes` before allocation |
| Inbox | Bounded; sheds replaceable messages before authority messages |
| Replay window | Bounded sequence window per sender |
| Clock sync | 16 samples per peer |
| Journal | Bounded retention; safety records never pruned |
| Event spool | Bounded; exhaustion becomes an explicit `RecordingGap` |
| Log files | Rotated; never grow unbounded during a multi-hour run |

A peer that stops reading cannot make a robot's memory grow without bound, and a
peer that floods is bounded by the same inbox.

---

## 9. Denial of service against the dashboard

| Control | Behaviour |
|---|---|
| Telemetry | Replaceable and decimation-able; authority events never dropped |
| Browser memory | Bounded client buffers and chart history |
| Slow client | Backpressure on the stream; a slow browser never blocks agent control |
| Stream gaps | Detected and surfaced; cursor expiry recovers via a fresh snapshot |
| Cursor semantics | Snapshot + cursor, so a reconnect never silently loses the start state |

---

## 10. Known limitations of this model

Stated plainly, because a security document that only lists strengths is not useful.

1. **No Byzantine fault tolerance.** A compromised peer can lie about its own
   identity and behaviour. The system refuses *replayed* and *mismatched* messages;
   it does not detect a peer that consistently fabricates plausible state.
2. **No rate limiting on the API.** Appropriate for loopback; a non-loopback
   deployment needs a reverse proxy with limits.
3. **Local trust in the scenario root.** Anyone who can write a scenario file can
   author a scenario. Validation prevents *invalid* layouts, not malicious ones, and
   validation cannot prove a layout safe.
4. **`Idempotency-Key` is not authentication.** It prevents accidental duplication.
   It does not prove the caller is authorised.
5. **Physical actuation is out of scope for the API entirely.** There is no
   endpoint that reaches hardware. Enabling actuation requires configured devices,
   a controlled test area, operator authorisation, and is refused while any
   safety-weakening ablation flag is set.
6. **No formal verification of the protocol.** The interleaving tests are bounded,
   and the deadlock-freedom argument is a proof sketch, not a machine-checked proof.

---

## 11. Reporting a security issue

This is a competition project, not a hosted service. A serious finding — especially
one that would let an agent fabricate authority — should be raised with the team
directly. Findings are fixed as ordinary defects, with a regression test added
before the fix, per the project's debugging discipline.
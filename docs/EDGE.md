# Edge deployment and ROS 2 integration

Two things this document is careful about:

1. **Physical actuation is disabled by default.** There is no API endpoint that
   reaches hardware. Enabling actuation requires explicitly configured devices, a
   controlled test area, and operator authorisation.
2. **No industrial safety certification is claimed.** Nav2's Collision Monitor
   informs this adapter's *structure*; its own documentation states it "does not
   provide hard real-time safety certifications". Neither does anything here.

---

## 1. What has and has not been executed

| Item | Status | Evidence |
|---|---|---|
| Native launcher on a development machine | **VERIFIED** | `pnpm bootstrap`, `pnpm dev`, `pnpm demo` on Windows 11 / Python 3.12.14 / Node 24.13.0 |
| Docker Compose path | **EXTERNAL LIMIT** | Docker is absent on the authoring machine. `deployment/docker/` is authored and reviewed; **no image was built and no container was run** |
| ROS 2 message definitions | **IMPLEMENTED** | `ros2/niharamesh_interfaces/msg/*.msg` with explicit frames, units and timestamps |
| ROS 2 bridge adapter logic | **VERIFIED** | `tests/ros2/test_bridge_fixture.py` drives the **same agent core** from fixture observations and asserts the emitted commands |
| `colcon build` | **EXTERNAL LIMIT** | No ROS 2 installation available. Never executed |
| Live DDS round trip | **EXTERNAL LIMIT** | Never executed |
| Raspberry Pi 5 / Jetson execution | **EXTERNAL LIMIT** | No ARM hardware available. Edge profiles are **specifications**, not measurements |

> A specification is not a measurement. No CPU, memory, power or timing figure in
> this document was measured on physical edge hardware.

---

## 2. Pinned ROS 2 target

**Researched recommendation: ROS 2 Jazzy Jalisco on Ubuntu 24.04 (Noble), arm64.**

From `docs/RESEARCH.md` (REP-2000, arm64 Tier 1):

| Distribution | Target | Status |
|---|---|---|
| **Jazzy Jalisco** | Ubuntu 24.04 | **Current Tier-1 LTS, arm64 supported to May 2029** ← pin this |
| Kilted Kaiju | Ubuntu 24.04 | Non-LTS; window closes November 2026 — **do not pin** |
| Humble Hawksbill | Ubuntu 22.04 | Runs to May 2027; **has *not* reached EOL** |

The build brief's premise that Humble is end-of-life is **incorrect**, and that is
recorded rather than repeated. Before any ROS claim is made, this matrix must be
re-validated against the official platform page, because a distribution's support
window is exactly the kind of fact that goes stale.

---

## 3. QoS: incompatibility is silent

The single most important ROS integration fact, from the official QoS
documentation:

| Publisher | Subscriber | Compatible? |
|---|---|---|
| best-effort | reliable | **No** |
| volatile | transient-local | **No** |

> "When connections are not made, no messages will be passed."

So a mismatched pair looks exactly like silence. NĪHĀRAMESH therefore reports a
**connected but silent** peer as `connected_silent`, never as "no traffic" — the
same distinction the peer transport makes, and for the same reason.

Chosen profiles:

| Topic | QoS | Reasoning |
|---|---|---|
| Pose, telemetry, state | `BEST_EFFORT`, depth 5 | Replaceable. Loss is acceptable; freshness is explicit |
| Intent, zone requests/grants/cancels/releases | `RELIABLE`, depth 10, `TRANSIENT_LOCAL` | Authority must not be dropped or arrive stale after restart |
| Heartbeat | `BEST_EFFORT`, depth 1 | Liveness only. **Not** usable intent |
| Clock | `RELIABLE`, depth 1 | Required for any timestamp comparison |

---

## 4. Message definitions

`ros2/niharamesh_interfaces/msg/` — every message carries an explicit frame, unit
and timestamp. Units are stated in the field comment, matching the internal
convention (metres, radians, integer nanoseconds, named time domain).

| Message | Purpose |
|---|---|
| `NhmPose.msg` | `frame_id`, `position_m [3]`, `orientation_wxyz [4]`, `header.stamp`, uncertainty |
| `NhmVelocity.msg` | Linear/angular with explicit `_mps` / `_radps` suffixes |
| `NhmSensorScan.msg` | Bearing/distance rays with `observed_at_ns` **and** `delivered_at_ns` |
| `NhmIntent.msg` | Projected path, expected zones, validity horizon, map digest, plan version |
| `NhmZoneRequest/Grant/Cancel/Release.msg` | Direct 1:1 with the peer wire types |
| `NhmTaskBid/Award.msg` | Bid components, ownership version, bid-set digest |
| `NhmHeartbeat.msg` | Liveness only, explicitly documented as such |

Design rules enforced in the `.msg` files:

- **Every timestamp carries its frame** and its unit. A bare `time` is never used.
- **`sent_at_ns` is separate from `received_at_ns`.** Conflating them is how a
  "fresh" message ends up being two seconds old.
- **Intent is never authorization.** The comment says so.
- **Heartbeat is never usable intent.** The comment says so.

---

## 5. The bridge boundary

```text
ROS 2 topic                Bridge node              NĪHĀRAMESH core
────────────              ───────────              ───────────────
NhmPose        ─────────▶ Observation builder ───▶ WorldPort.observe()
NhmSensorScan  ─────────▶ Sensor adapter       ───▶ Observation.sensor
NhmVelocity    ◀───────── MotionCommand       ◀─── Safety gate
NhmIntent      ─────────▶ PeerEnvelope        ───▶ Coordinator
NhmZone*       ⇄         Peer transport      ⇄     Coordinator
```

The bridge is a **translator**, and the test enforces that:

- It converts frames, units and timestamp semantics.
- It does **not** decide anything. No route, no bid, no grant, no veto.
- Actuator output passes through the **same safety gate** as the simulated path.
  A ROS input cannot bypass the gate, which is why the bridge test asserts on gate
  decisions rather than on raw velocities.

### Fixture-based integration test (executed)

```bash
uv run pytest tests/ros2 -q
```

`tests/ros2/test_bridge_fixture.py` feeds recorded `NhmPose` / `NhmSensorScan`
messages into the adapter, runs the real agent core, and asserts:

- the emitted `NhmVelocity` matches the safety-gated command,
- a stale observation produces a **stop**, not motion,
- an expired command triggers watchdog braking,
- a message with a bad frame or an implausible timestamp is **rejected**, not
  coerced.

This proves the *adapter logic* and the core integration. It does **not** prove the
ROS build works — no `colcon build` has been run.

---

## 6. Edge profiles

Three distinct host profiles. `deployment/edge/<host>/` holds each one.

| | `edge-planner` | `edge-supervisor` | `edge-observer` |
|---|---|---|---|
| Role | World + sensor fusion | Authority journals, coordination | Recording, read models, replay |
| Robot count | all | all | all (passive) |
| Identity | `nhm-world` | `nhm-sup-01..N` | `nhm-obs-01` |
| Storage | WAL journal + run state | **authority journal, `synchronous=FULL`** | event log, bounded retention |
| Authority | **none** | none | **none** |
| Loss impact | Simulation stops | Promises may be lost → fenced zones | **Data gap only** |

Each profile states: process identity, listening ports, local network
configuration, durable storage paths, log destinations, and power/cooling notes.

### Raspberry Pi 5 — specification only

From vendor documentation, as recorded in `docs/RESEARCH.md`:

| Attribute | Value |
|---|---|
| SoC | Broadcom BCM2712 |
| RAM options | 1 / 2 / 4 / 8 / 16 GB (CM5: 2 / 4 / 8 / 16 GB) |
| Networking | Gigabit Ethernet with PoE+; Wi-Fi 5 |
| Power | 25 W typical; ~15 W at 600 mA |

**Deliberately not stated:** CPU core count and clock rate. The product page and
datasheet returned HTTP 403 / 404 during research, so those figures are marked
`unverified:` in `docs/RESEARCH.md` and are not printed here. Printing a
remembered spec number would be exactly the invented measurement this project
refuses.

Recommendation: **CM5 with wired PoE**. The organiser's own problem statement names
"Wi-Fi dead-zone" risk, and this system's core assumption is that a stale peer must
be treated conservatively. Wireless is a poor substrate for that assumption: it
turns a partition into a routine event.

---

## 7. Docker Compose path

`deployment/docker/` provides a Compose topology with explicit health checks and
readiness gates.

**Nothing here has been executed.** Docker was unavailable on the authoring
machine, so no claim about container behaviour is made. When it is run, record:

```bash
docker compose up -d
docker compose ps                      # capture the health transitions
docker compose logs --tail 200 api
```

Services do not report ready after a fixed sleep: each waits on its own health
check, and dependents use `condition: service_healthy`. A container that is up but
unhealthy is reported as unhealthy, not as ready.

The native launcher remains the tested path and requires no container runtime.

---

## 8. Physical actuation

Disabled by default, and enforced in three places:

```text
NIHARA_PHYSICAL_ACTUATION_ENABLED=false      # environment default
SimulationConfig.physical_actuation_enabled  # False, model-level default
FeatureFlags.physical_actuation_permitted() # refuses when any unsafe ablation is on
```

Enabling requires **all** of:

1. explicit `NIHARA_PHYSICAL_ACTUATION_ENABLED=true`,
2. configured device identifiers (not defaults),
3. a declared controlled test area,
4. documented operator authorisation,
5. no safety-weakening ablation flag set.

There is **no API endpoint that reaches hardware**. A browser fault-injection
control intended for simulation cannot affect a physical device, because no such
path exists. Even with actuation enabled, the actuator model still applies its
declared acceleration and deceleration, and a stale command still triggers
watchdog braking — physical execution is not a shortcut past the safety gate.

---

## 9. Verification status summary

| Capability | Verified here? |
|---|---|
| Native launcher, no ROS, no hardware | **Yes** |
| Safety gate on simulated motion | **Yes** |
| Bridge adapter logic via fixtures | **Yes** |
| Container build and health | **No** — Docker unavailable |
| `colcon build`, message generation | **No** — ROS unavailable |
| Live DDS round trip, QoS in practice | **No** — ROS unavailable |
| ARM edge CPU/memory/timing | **No** — no hardware |
| Physical robot operation | **Not attempted, not claimed** |
| Industrial safety certification | **Not claimed** |

The software demonstration runs on an ordinary development machine without ROS or
hardware. That path is the tested one.
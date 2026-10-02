# ADR 0006 — One safety gate in front of every actuator command

**Status:** Accepted · **Date:** 2026-10-02

## Context

Motion can be requested by four sources: the planner, the coordinator, the operator,
and the actuator watchdog itself. If each source had its own notion of what is safe,
the safety argument would need to hold four times over, and the weakest link would
govern.

There is also a subtler problem. A planner that is *trying* to be safe will fail to
find a route and stop. A planner that is *trying* to complete a task will find a
route. Neither should decide.

## Decision

**Exactly one veto point. Every actuator command passes it.**

1. A single `SafetyGate.evaluate(command, now_ns) -> SafetyDecision` sits between
   whatever produced a command and the world.
2. It can veto **planner, coordinator and operator-requested motion alike.** An
   operator command has no privileged path.
3. It is **small, observable and directly tested.** Every veto carries a named
   `StopReason` and the limiting constraint that produced it.
4. Vetoes are **recorded as `SAFETY`-category events**, so the UI can show what was
   refused and why.
5. The gate is in the **agent process**, not the world. The world applies physics; it
   never decides safety, and it never refuses a command for being unsafe — it applies
   it and lets the evaluator detect the collision independently.

## Constraints it checks

| Check | Derived from |
|---|---|
| Command expiry (watchdog) | `actuator.command_ttl_s` |
| Localisation freshness | Declared staleness bound |
| Sensor observation age | `sensor.observation_latency_s` + dropout |
| Zone authority present for the zone being entered | Coordinator state |
| Peer intent freshness for the contended zone | `protocol.freshness_horizon_s` |
| Stopping clearance to an observed obstacle | `StoppingBudget`, inclusive of payload overhang |
| Obstacle in the immediate path | Local observations |
| Blocked exit / no safe berth | Berth occupancy |
| Control-loop stall | `protocol.control_period_s` |
| Battery below the configured reserve | Declared threshold |
| Operator stop requested | Command plane |
| Physical actuation switch | `physical_actuation_enabled` |

`UNKNOWN`-class freshness is treated **exactly like `STALE`** here. Uncertainty grants
no permission.

## Consequences

**The gate can be wrong in one direction only.** It can refuse a safe command
(availability loss, visible in the metrics). It cannot permit an unsafe one, *provided*
every constraint above is correct. That asymmetry is the point: an availability cost
is recoverable, a safety cost is not.

The gate is also the natural place for future constraints, which is why it is a single
named component rather than checks scattered through the planner.

## What this is not

- **Not a certified safety function.** No software monitor in this project is one.
- **Not a collision-avoidance system.** It vetoes motion on *evidence*; it does not
  plan around obstacles.
- **Not complete.** Every check has a threshold, and thresholds are configured
  assumptions. The evaluator independently checks for violations, so a missed veto
  becomes a recorded unsafe run rather than a silent failure.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| **Safety checks inside the planner** | The planner is optimising task completion; it has an incentive to be optimistic. |
| **Safety checks in the world process** | The world would then refuse colliding motion, concealing unsafe control — precisely what the brief forbids. |
| **Checks at the transport layer** | Sees packets, not physical state. |
| **Operator override** | Any override weakens the single point of responsibility. |
| **Trust the coordinator's own view** | The coordinator reasons about *authority*; it does not observe the physical path. |
| **Learned safety model** | Learned predictions cannot override occupancy, authority, freshness or stopping checks. |

## Revisiting condition

Revisit only if the measurement shows a *specific* gate constraint is the dominant
throughput bottleneck across benchmark families — and then by adding a constraint, not
by relaxing one. Never relax `command_expired`, localisation freshness or zone
authority.

A **learned** estimator may later be *advisory* input to a stopping-distance budget,
behind a feature flag, with a deterministic analytical fallback. It may never gate
actuation, and any such change needs its own ADR plus an ablation.

## Verification

- `tests/unit/test_safety_gate.py` — each constraint vetoes for its own reason
- `tests/unit/test_safety_gate.py::test_operator_command_is_vetoed_like_any_other`
- `tests/unit/test_kinematics.py::test_command_expiry_decays_momentum_over_several_steps`
- `tests/integration/test_world.py::test_world_applies_colliding_commands` — the world
  does not refuse unsafe motion, so the gate is the only thing preventing it
- `tests/integration/test_unsafe_fixture.py` — a deliberately unsafe controller is
  detected by the evaluator, so a gate that silently failed would still be caught
# Milestone A — approved observation / actuation / zone-evidence contract

Status: **approved by the integration owner** (author of this file). Any implementer
may propose a change here, but nobody may implement against a different interface.

This file exists because the three defects reproduced on 2026-10-02 all came from
*ambiguous meanings* rather than from missing code. Writing the meanings down first is
cheaper than debugging them afterwards.

## A0. The reproduced defect

Baseline before Milestone A (reproduced locally, not copied from a previous report):

```text
three-way-junction -> incomplete duration 60.0
   amr-01 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
   amr-02 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
   amr-03 cmds 1200 vetoes 1200 stops {'actuator_fault': 1200}
   inspect amr-02 queued_for_zone actuator_fault zn-junction
headon-aisle       -> incomplete duration 60.0   (identical veto pattern)
infeasible-layout  -> incomplete duration 60.0   (identical veto pattern)
```

`426 passed in 105.91s` for the whole Python suite at that point.

Every tick is vetoed with `StopReason.ACTUATOR_FAULT` / constraint
`actuation_disabled`. Nothing moves, so nothing can complete. That is the visible
symptom; the five root causes below are the actual defects.

## A1. Two different switches, currently conflated

`SimulationConfig.physical_actuation_enabled` is used for two unrelated questions:

1. *May this command integrate against the declared actuator model?* (a physics question)
2. *May this command energise a real drive train?* (a hardware boundary question)

Question 2 must stay `False` in this repository, forever, unless a human opts in.
Question 1 must be `True` in the laboratory, or the simulation cannot demonstrate
anything.

**Contract.** The two become separate fields.

```python
# SimulationConfig
simulated_actuation_enabled: bool = True    # the declared actuator model integrates commands
physical_actuation_enabled: bool = False    # hardware opt-in; unchanged meaning
```

plus one derived helper, and it is the only thing the simulator is allowed to ask:

```python
@property
def actuator_chain_live(self) -> bool:
    """True when the declared actuator model integrates accepted commands."""
    return self.simulated_actuation_enabled or self.physical_actuation_enabled
```

The existing validator (`physical_actuation_enabled` requires
`features.physical_actuation_permitted()`) is **unchanged and must stay**.

`MotionState.actuation_enabled` keeps its schema and its meaning, restated: *this
robot's own drive-train chain is live and will accept commands*. It becomes true when
the chain is live at boot, not only after the first accepted command — otherwise the
gate's first check vetoes every command at tick 0 and no robot can ever start.

`World.apply_command` refuses when `not self._config.actuator_chain_live`. It still
refuses on: unknown robot, wrong clock domain, and a non-increasing `command_seq`. It
still **never** refuses a colliding command.

## A2. The gate's zone evidence contract

Today the gate asks:

```python
if ctx.inside_zone is None and ctx.zone_authority is None and abs(command.linear_mps) > 1e-6:
    return SafetyDecision(False, StopReason.ZONE_AUTHORITY_MISSING, "no_zone_authority")
```

and the runtime fills `inside_zone` with `_zone_in_progress` — *the next zone anywhere
on the remaining plan*, which may be ten metres away. Together with A3 below that is an
authority bypass: a robot with no grant satisfies the zone check by naming a zone it is
approaching.

**Contract.** The gate decides about *geometry*, not about plans. Three separate facts,
with separate names:

| field | meaning |
|---|---|
| `occupied_zone: str \| None` | the zone whose **protected geometry contains this robot's body right now**, derived from this robot's own pose estimate and footprint. Conservative: inflated, never the centre point. |
| `entry_permission: str \| None` | the zone for which this robot holds **complete, durable GRANTED entry permission** (its own local voter plus every peer voter, digests reconciled, journal healthy, local admission passed). |
| `zone_authority: str \| None` | the zone whose authority this robot **retains** — granted-and-entering, or physically occupied. Survives `may_enter()` going false after entry. |
| `swept_body: OrientedBox \| None` | the conservative body this command could occupy between now and the end of its TTL, including braking distance and the localisation uncertainty bound. Built by the agent from its own footprint and its own command. |

The decision, replacing the blanket rule:

```python
for zone in self._map.zones:
    if not _body_touches_bounds(swept, zone.protected_bounds):
        continue
    if zone.id == ctx.occupied_zone:
        if ctx.zone_authority != zone.id:
            veto(ZONE_AUTHORITY_MISSING, f"unauthorised_occupancy:{zone.id}")
        continue
    if ctx.entry_permission != zone.id:
        veto(ZONE_AUTHORITY_MISSING, f"unauthorised_entry:{zone.id}")
```

Three consequences, all intended:

* **Legitimate open-space motion is permitted.** A robot crossing an aisle with no zone
  anywhere in its swept body is never asked for zone authority.
* **Protected entry needs complete valid authority**, not a plan that mentions the zone.
* **Occupancy is retained.** Being inside a zone you hold authority over is permitted
  even after `entry_permission` has gone, because authority and entry permission are no
  longer the same question.

`_body_touches_bounds` is an AABB test of the body's corners against
`Zone.protected_bounds`. The protected geometry is *already* inflated by the map author;
the gate must not inflate it a second time.

## A3. The agent's own refusal is a decision, not advice

`RobotAgent._decide` returns `SafetyDecision(False, ...)` for `WAITING`,
`QUEUED_FOR_ZONE`, `SERVICING` and `UNREACHABLE`. `_to_command` then discarded it and
called `_pursue` anyway, producing a full-speed pursuit command for a robot that had
just decided not to move.

**Contract.** `_to_command` requests `0.0, 0.0` whenever `decision.permitted` is false.
A refusal is still offered to the gate — a stop is a command and must be attributable —
but it can never carry a velocity the agent refused to ask for.

`stop_reason` reports the agent's refusal when the agent refused, and the gate's reason
when the gate vetoed. Both are recorded; neither is overwritten by the other.

## A4. Control-loop age is measured, not inferred from permission

`_last_command_at_ns` is only updated when the gate *permits*. A robot vetoed every tick
therefore looks permanently stalled, and the gate latches `CONTROL_LOOP_STALLED` — a
false stop that hides the real one.

**Contract.** Measure the gap since the previous **tick**, before updating:

```python
age = 0 if self._last_tick_ns is None else now_ns - self._last_tick_ns
self._last_tick_ns = now_ns
```

A live loop reports ~0 and is never falsely latched. A loop that really has not ticked
for longer than `DEFAULT_STALL_NS` reports that gap on its first tick back and **fails
closed once** — which is what "fail closed" has to mean for a stall detector that
re-arms itself.

## A5. The coordinator's local safety callback must be a real one

`ZoneProtocol`'s default `safety_check` is `_safety_unavailable`, which refuses
everything. That refusal is intentional and stays as the default. What is missing is the
runtime's own callback.

**Contract.** `RobotAgent` supplies `safety_check=self._admission_safety`. It answers
from *current local evidence only*:

* localiser age against the declared staleness bound,
* this tick's own sensor scan not dropped,
* battery above the reserve,
* the swept body from the current pose to the zone entry pose is clear of **static map**
  obstacles by the declared stopping budget.

It must **not** consult `may_enter`, the grant set, peer state, or anything else that
the entry decision is itself producing — that would be circular. Grants are established
by the protocol; the callback only says whether this robot can physically and safely
enter given what it can see.

## A6. Ownership

| Path | Owner |
|---|---|
| `src/niharamesh/domain/config.py`, `src/niharamesh/simulator/**`, `src/niharamesh/safety/gate.py`, `src/niharamesh/contracts/**` | safety/simulation implementer |
| `src/niharamesh/agent/**`, `src/niharamesh/runs/**`, `tests/integration/**` | integration owner |
| everything under `src/niharamesh/coordination/**` | **nobody in Milestone A** — read-only |
| `packages/contracts/**` | integration owner (published from the generated schemas) |
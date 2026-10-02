# Scenarios: authoring, validation and import/export

Seven named scenarios ship with the project, covering every contested geometry and
failure mode in the specification. They are built programmatically in
`src/niharamesh/scenario/library.py` and exported to versioned JSON under
`scenarios/`, so the library is both **reviewable** and **reproducible**.

```bash
uv run nihara scenarios export      # rebuild the JSON from the builders
uv run nihara scenarios list
uv run nihara scenarios validate --structural-only
uv run nihara scenarios show headon-aisle
```

---

## 1. The library

| Scenario id | Contests | Key property under test |
|---|---|---|
| `headon-aisle` | Two robots entering one 1.40 m aisle from opposite ends | Exactly one traverses; the other holds at a berth. Separates real coordination from stop-and-wait most directly |
| `three-way-junction` | Three robots, one junction zone | Right of way follows canonical order and every acquisition is inspectable |
| `cycle-with-holding` | Three consecutive segments of one aisle | A robot must release, reach a berth, and only then seek the next |
| `blocked-exit` | Obstacle inserted into a shared aisle mid-run | Reroute-vs-wait cost comparison is visible; the robot never drives into the obstacle |
| `dynamic-arrivals` | Tasks released at 0/60/120/180 s | Late allocation rounds; no duplicate award or custody |
| `asymmetric-partition` | Directed cut `amr-01 → amr-02` for 45 s | Only that pair degrades; `amr-03` keeps delivering |
| `infeasible-layout` | Drop row sealed off from pickup row | Correct result is a **safe explained stop**, not a delivery |

---

## 2. Map geometry and its invariants

Every authored map uses the same 26 m × 18 m lattice:

```text
  y=18 ┌──────────────────────────────────────────────────────────┐
       │  perimeter corridor                                      │
  17.1 ├──── cross aisle ────────────────────────────────────────┤
       │ [shelf row 2]  [shelf row 2]  [shelf row 2]  [shelf row 2] │
  11.9 ├──── cross aisle ────────────────────────────────────────┤
       │ [shelf row 1]  ...                                      │
   6.9 ├──── cross aisle ────────────────────────────────────────┤
       │ [shelf row 0]  ...                                      │
   1.3 └──── cross aisle ────────────────────────────────────────┘
  y=0  └──────────────────────────────────────────────────────────┘
        2.5    8.9    13.5    18.1                          24.0
```

| Constant | Value | Why |
|---|---|---|
| Chassis | 0.60 m × 0.40 m | Declared `AMR_FOOTPRINT` |
| Payload | 0.30 m × 0.24 m, 0.0 m offset | Overhang is included in every clearance test |
| Clearance radius | 0.36 m | `hypot(0.30, 0.20)` |
| Aisle clear width | **1.40 m** | Leaves 1.00 m of lateral freedom for a 0.40 m chassis |
| Nominal speed | 0.4 m/s | **Configured assumption**, not a measured or certified value |
| Physics step | 20 Hz | Fixed step, deterministic |

`assert_aisle_clearance()` enforces the 1.40 m lattice invariant at build time, so a
map cannot silently become an undersized passage.

### Zones and berths

Zones are authored **per shelf row** (`row_zone`), not per whole aisle. A zone's
protected rectangle is the corridor grown by the clearance radius on every side —
two robots inside one aisle are in conflict even when their centres are a full
aisle width apart.

Queue and exit berths for interior aisles sit **±1.5 m laterally off the aisle
centre line**, inside the cross aisle. That offset is not cosmetic: a berth on the
centre line at a cross-aisle `y` falls inside its own zone's protected area, which
would mean a robot stopping there still holds another robot's resource.
`validate_berth_separation` catches exactly this, and it caught it during authoring.

Because rows are separated by a full cross aisle, consecutive zones along one aisle
are always divided by a safe stopping place. That is what makes "at most one
outstanding grant per robot" practical: a robot can always release its grant, come
to rest, and only then seek the next.

---

## 3. File format

```jsonc
{
  "schema_version": "1.0.0",
  "scenario_id": "headon-aisle",
  "revision": 1,
  "name": "Head-on narrow aisle",
  "description": "...",
  "kind": "nominal",            // nominal | fault | diagnostic | benchmark
  "intent": {
    "goal": "Deliver two opposing transports through one shared aisle segment without contact.",
    "expect": "Exactly one robot enters the aisle at a time; ...",
    "expected_failure_reason": ""   // required when kind == "diagnostic"
  },
  "map": {
    "map_id": "map-headon",
    "boundary": { "min_x": 0, "min_y": 0, "max_x": 26, "max_y": 18 },
    "obstacles": [ { "id": "shelf-00", "kind": "shelf", "pose": {...}, "length_m": 3.2, "width_m": 3.6 } ],
    "stations":  [ { "id": "stn-pick-a", "kind": "pickup", "pose": {...}, "service_time_s": 4.0 } ],
    "berths":    [ { "id": "brt-00", "pose": {...}, "capacity": 2 } ],
    "zones":     [ { "id": "zn-headon-mid", "protected_origin": [..], "protected_extent": [..],
                     "entry_pose": {...}, "exit_pose": {...},
                     "queue_berth_id": "brt-07", "exit_berth_id": "brt-12" } ],
    "stop_lines":[ { "id": "sl-...", "zone_id": "zn-...", "start": [x,y], "end": [x,y] } ],
    "grid_resolution_m": 0.1,
    "nominal_aisle_width_m": 1.4
  },
  "robots":  [ { "robot_id": "amr-01", "footprint": {...}, "max_linear_mps": 0.4 } ],
  "starts":  [ { "robot_id": "amr-01", "pose": {...}, "assigned_task_id": "t-headon-up" } ],
  "tasks":   [ { "task_id": "...", "pickup_station_id": "...", "drop_station_id": "...",
                "release_at_s": 0.0, "service_time_s": 3.0,
                "required_capabilities": ["carry_payload"], "priority": 100 } ],
  "faults":  [ { "fault_id": "...", "target": {...}, "start_at_s": 25.0,
                "duration_s": 45.0, "seed": 33, "expected_invariant": "..." } ],
  "policy":  { "coordination": "canonical_sequential", "assignment": "local_auction",
               "routing": "blocked_aware", "comparison_mode": "coordination_only",
               "planner_seed": 11, "sensor_seed": 22, "fault_seed": 33 },
  "simulation": { "physics_step_hz": 20, "state_publish_hz": 10, "actuator": {...},
                  "sensor": {...}, "battery": {...}, "stopping": {...},
                  "protocol": {...}, "features": {...}, "physical_actuation_enabled": false },
  "seed": 20260101,
  "max_sim_time_s": 600.0
}
```

Unknown fields are **rejected**, not ignored. A file authored against an
incompatible `schema_version` is refused rather than migrated — a silent migration
would change the meaning of an experiment without anyone noticing.

---

## 4. Validation: two severities, deliberately distinct

| Severity | Meaning | Effect |
|---|---|---|
| `STRUCTURAL` | The scenario cannot be launched at all | **Blocks launch**, unconditionally |
| `WORKLOAD` | Layout is sound, workload may be unsatisfiable | May run **only** as an explicitly labelled expected-failure experiment |
| `WARNING` | Launchable, but an operator should know | Reported, non-blocking |

### Structural checks

`duplicate_id`, `start_overlaps_obstacle`, `start_outside_boundary`,
`initial_bodies_overlap`, `task_references_unknown_station`,
`fault_targets_unknown_robot`, `fault_targets_unknown_zone`,
`zone_protected_geometry_overlaps`, `zone_member_claimed_twice`,
`berth_inside_zone`, `undersized_passage`, `diagnostic_without_reason`,
`schema_version_incompatible`, `unexpected_failure_reason`.

### Workload checks

`task_destination_unreachable`, `task_released_after_deadline`.

### What is NOT checked statically

Stated on every validation run, because claiming completeness would be false:

- multi-robot reachability and deadlock-freedom,
- temporal feasibility of every planned traversal,
- sensor observability coverage.

Each run's planner reports its own `UNREACHABLE` result with an explicit reason,
which is authoritative for that leg.

### Example: the diagnostic scenario

```text
infeasible-layout  revision=1  diagnostic-only
  [WORK ] task_destination_unreachable: task 't-infeasible-0' asks for 'stn-pick-a'
         -> stn-drop-a but no single-robot route exists at the declared clearance.
         The correct outcome for this workload is a safe explained stop.
         -> if that is intended, mark the scenario kind='diagnostic' and set
            intent.expected_failure_reason so it is excluded from success comparisons
  [warn ] reachability_is_estimated: ...
  [limit] not checked: multi-robot reachability and deadlock-freedom ...
```

`launchable = False` (a workload problem), `diagnostic_allowed = True` (it is
*structurally* valid). Launching it produces `RunOutcome.EXPECTED_SAFE_STOP` and the
run is excluded from successful-completion comparisons by construction.

**The diagnostic option never bypasses geometry or authority invariants.**

---

## 5. Immutability

A launched run binds an immutable `ScenarioSnapshot` carrying the scenario plus
five digests: scenario, map, config, faults, tasks. Editing the scenario library
afterwards cannot change an experiment already run, and every derived artefact
quotes those digests.

---

## 6. Authoring in the editor

The cockpit's scenario editor is **semantic**, not a drawing canvas: entities are
selected and property-edited with numeric fields, grid snapping and undo/redo.

| Requirement | Behaviour |
|---|---|
| Invalid drafts | **Preserved**, never discarded |
| Launch | Blocked with the full actionable issue list |
| Silent repair | Never. A layout is never quietly "fixed" |
| Structural vs workload | Shown as distinct severities with distinct remedies |
| Save as revision | Creates a new revision; prior runs unaffected |
| Import/export | Versioned JSON round trip |

---

## 7. Import safety

| Control | Behaviour |
|---|---|
| Path traversal | `resolve_scenario_path` refuses anything resolving outside the scenario root, after symlink resolution |
| Size | Refused above 4 MiB, checked **before** parsing |
| Format | JSON only. No `pickle`, no `yaml.load`, no untrusted object deserialisation |
| Schema | Pydantic `extra="forbid"`; unknown fields are errors |
| Version | Incompatible `schema_version` refused, never migrated |
| Output paths | Validated before writing; temporary file then atomic rename |

---

## 8. Adding a scenario

1. Add a builder function in `src/niharamesh/scenario/library.py`.
2. Register it in `_BUILDERS` — it is picked up automatically.
3. `uv run nihara scenarios export`
4. `uv run nihara scenarios validate --structural-only`
5. `uv run pytest tests/scenarios -q`

The builder should use `row_zone`, `aisle_zone`, `berth_id`, `station`, `berth`,
`obstacle` and `partition_fault` so zone/berth references resolve from the lattice
rather than being hard-coded.

---

## 9. Fault schedules inside a scenario

A scheduled fault becomes part of the immutable snapshot. Manual injections from the
fault laboratory become timestamped run events instead — both are recorded, and the
distinction is preserved.

| Field | Meaning |
|---|---|
| `target.channel` | `coordination` (robot↔robot) or `telemetry` (observer) — **never conflated** |
| `target.sender` / `receiver` | Directed targeting. A partition sets **both** for a bidirectional cut |
| `start_at_s` / `duration_s` | Simulation seconds from the run start |
| `seed` | Deterministic; a run is reproducible from its manifest |
| `expected_invariant` | What must remain true — displayed in the UI, checked after the run |

Validation catches faults targeting unknown robots or zones, and warns when a fault
outlives the run so its invariant can never be observed.
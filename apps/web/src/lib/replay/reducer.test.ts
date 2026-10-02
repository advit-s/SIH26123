/**
 * Behaviour tests for replay reconstruction.
 *
 * The rule under test: **seeking backwards removes future state.** A completion,
 * a grant, an obstacle insertion and an alert that happened after the cursor
 * must not exist in the rebuilt world. The implementation achieves this by
 * folding only `events[0..cursor]` — these tests assert the *result*, and also
 * assert that a forward build is never mutated by a later rebuild.
 */
import { describe, expect, it } from "vitest"
import type { DomainEvent } from "@niharamesh/contracts/generated"
import { SCHEMA_VERSION } from "@niharamesh/contracts/generated"
import { buildReplayState, cursorBounds, eventsUpTo, firstFaultSeq, firstViolationSeq } from "./reducer"

let nextSeq = 0

function event(partial: Partial<DomainEvent> & Pick<DomainEvent, "type" | "category">): DomainEvent {
  nextSeq += 1
  return {
    schema_version: SCHEMA_VERSION,
    run_id: "run-1",
    seq: partial.seq ?? nextSeq,
    source: "test",
    source_session: "s1",
    event_time_ns: nextSeq * 1_000_000,
    time_domain: "logical",
    receive_time_ns: nextSeq * 1_000_000,
    receive_time_domain: "logical",
    sim_time_s: nextSeq / 10,
    severity: "info",
    reason: "",
    correlation_id: "c",
    payload: {},
    ...partial,
  } as DomainEvent
}

function reset(): void {
  nextSeq = 0
}

describe("buildReplayState", () => {
  it("removes a future task completion when the cursor moves backwards", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "task.awarded", category: "task", task_id: "T-1", robot_id: "AMR1", payload: { ownership_version: 1 } }),
      event({ type: "zone.granted", category: "authority", zone_id: "Z-1", robot_id: "AMR1" }),
      event({ type: "task.completed", category: "task", task_id: "T-1", robot_id: "AMR1" }),
    ]

    const atEnd = buildReplayState(eventsUpTo(events, 3), SCHEMA_VERSION)
    expect(atEnd.tasks.get("T-1")?.completed).toBe(true)
    expect(atEnd.tasks.get("T-1")?.completed_at_seq).toBe(3)

    // Seek back to before the completion: the completion simply does not exist.
    const rewound = buildReplayState(eventsUpTo(events, 2), SCHEMA_VERSION)
    expect(rewound.tasks.get("T-1")?.completed).toBe(false)
    expect(rewound.tasks.get("T-1")?.completed_at_seq).toBeNull()
    expect(rewound.tasks.get("T-1")?.owner).toBe("AMR1")
    expect(rewound.tasks.get("T-1")?.ownership_version).toBe(1)

    // Seeking forward again rebuilds it. The earlier object was never mutated.
    expect(atEnd.tasks.get("T-1")?.completed).toBe(true)
  })

  it("removes a future zone grant and entry count when the cursor moves backwards", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "zone.promised", category: "authority", zone_id: "Z-2", robot_id: "AMR2" }),
      event({ type: "zone.granted", category: "authority", zone_id: "Z-2", robot_id: "AMR2" }),
      event({ type: "zone.entered", category: "authority", zone_id: "Z-2", robot_id: "AMR2" }),
      event({ type: "zone.released", category: "authority", zone_id: "Z-2", robot_id: "AMR2" }),
    ]

    const atEnd = buildReplayState(events, SCHEMA_VERSION)
    expect(atEnd.zones.get("Z-2")?.authority).toBe("released")
    expect(atEnd.zones.get("Z-2")?.entries).toBe(1)

    const rewound = buildReplayState(eventsUpTo(events, 2), SCHEMA_VERSION)
    expect(rewound.zones.get("Z-2")?.authority).toBe("granted")
    expect(rewound.zones.get("Z-2")?.entries).toBe(0)

    const rewoundFurther = buildReplayState(eventsUpTo(events, 1), SCHEMA_VERSION)
    expect(rewoundFurther.zones.get("Z-2")?.authority).toBe("promised")
    expect(rewoundFurther.robots.get("AMR2")?.holding_zone).toBeNull()
  })

  it("removes a future obstacle insertion when the cursor moves backwards", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "obstacle.inserted", category: "planning", payload: { obstacle_id: "obs-1", kind: "temporary", x: 3, y: 4 } }),
    ]
    expect(buildReplayState(events, SCHEMA_VERSION).obstacles.size).toBe(1)
    expect(buildReplayState([], SCHEMA_VERSION).obstacles.size).toBe(0)
  })

  it("removes a future alert when the cursor moves backwards", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "fault.partition_active", category: "fault", severity: "fault", reason: "AMR2→AMR3 partition" }),
      event({ type: "zone.violation", category: "safety", severity: "violation", zone_id: "Z-1", robot_id: "AMR1" }),
    ]
    expect(buildReplayState(events, SCHEMA_VERSION).alerts).toHaveLength(2)
    expect(buildReplayState(eventsUpTo(events, 1), SCHEMA_VERSION).alerts).toHaveLength(1)
    expect(buildReplayState([], SCHEMA_VERSION).alerts).toHaveLength(0)
  })

  it("clears a robot's payload task when the completion is out of range", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "task.awarded", category: "task", task_id: "T-9", robot_id: "AMR3" }),
      event({ type: "task.completed", category: "task", task_id: "T-9", robot_id: "AMR3" }),
    ]
    expect(buildReplayState(events, SCHEMA_VERSION).robots.get("AMR3")?.task_id).toBeNull()
    expect(buildReplayState(eventsUpTo(events, 1), SCHEMA_VERSION).robots.get("AMR3")?.task_id).toBe("T-9")
  })

  it("counts events it does not model instead of silently omitting them", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "robot.something_new", category: "planning" }),
      event({ type: "robot.something_new", category: "planning" }),
    ]
    const state = buildReplayState(events, SCHEMA_VERSION)
    expect(state.eventsConsidered).toBe(2)
    expect(state.eventsApplied).toBe(0)
    expect(state.unknownTypes).toEqual([{ type: "robot.something_new", count: 2 }])
    expect(state.problems.some((p) => p.kind === "unknown_event_type")).toBe(true)
  })

  it("fails usefully and visibly on an event schema version it does not understand", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "zone.granted", category: "authority", zone_id: "Z-1", robot_id: "AMR1" }),
      event({ type: "zone.entered", category: "authority", zone_id: "Z-1", robot_id: "AMR1", schema_version: "99.0.0" }),
    ]
    const state = buildReplayState(events, SCHEMA_VERSION)
    expect(state.usable).toBe(false)
    const problem = state.problems.find((p) => p.kind === "unsupported_version")
    expect(problem).toBeDefined()
    expect(problem?.message).toMatch(/newer than this console understands/)
    expect(problem?.message).toMatch(/stopped rather than shown with missing state/)
  })

  it("reports a sequence hole as a problem rather than stitching over it", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "zone.granted", category: "authority", zone_id: "Z-1", robot_id: "AMR1", seq: 1 }),
      event({ type: "zone.entered", category: "authority", zone_id: "Z-1", robot_id: "AMR1", seq: 7 }),
    ]
    const state = buildReplayState(events, SCHEMA_VERSION)
    expect(state.problems.some((p) => p.kind === "sequence_hole")).toBe(true)
  })

  it("folds poses and never invents one for a robot with no samples", () => {
    reset()
    const events: DomainEvent[] = [
      event({
        type: "telemetry.sample",
        category: "telemetry",
        robot_id: "AMR1",
        payload: { x: 1.5, y: 2.5, theta: 0.5, stop_reason: "none" },
      }),
      event({ type: "lifecycle.crashed", category: "lifecycle", robot_id: "AMR2" }),
    ]
    const state = buildReplayState(events, SCHEMA_VERSION)
    expect(state.robots.get("AMR1")?.x).toBe(1.5)
    expect(state.robots.get("AMR2")?.x).toBeNull()
    expect(state.robots.get("AMR2")?.faulted).toBe(true)
  })
})

describe("cursor helpers", () => {
  it("computes bounds and marker sequences", () => {
    reset()
    const events: DomainEvent[] = [
      event({ type: "zone.granted", category: "authority", zone_id: "Z-1", robot_id: "AMR1", seq: 4 }),
      event({ type: "fault.partition_active", category: "fault", severity: "fault", seq: 9 }),
      event({ type: "zone.violation", category: "safety", severity: "violation", seq: 15 }),
    ]
    expect(cursorBounds(events)).toEqual({ first: 4, last: 15 })
    expect(cursorBounds([])).toEqual({ first: null, last: null })
    expect(firstFaultSeq(events)).toBe(9)
    expect(firstViolationSeq(events)).toBe(15)
    expect(firstViolationSeq([])).toBeNull()
  })

  it("returns a new array rather than mutating the source log", () => {
    reset()
    const events: DomainEvent[] = [event({ type: "zone.granted", category: "authority", zone_id: "Z-1", robot_id: "AMR1" })]
    const prefix = eventsUpTo(events, 0)
    expect(prefix).toHaveLength(0)
    expect(events).toHaveLength(1)
  })
})
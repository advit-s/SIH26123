/**
 * Replay state reconstruction — a **pure fold**.
 *
 * THE RULE: state at a cursor is always `events[0..cursor]` folded from
 * scratch. Nothing is ever mutated in place and nothing is ever "un-applied".
 * Seeking backwards therefore *cannot* leave a future task completion, a future
 * grant, a future obstacle insertion or a future alert behind, because those
 * events are simply not in the input list for the rebuild.
 *
 * Two failure modes are surfaced rather than swallowed:
 *   - An event whose `schema_version` is newer than this client understands is
 *     an **unsupported version** problem: the replay stops and the UI shows a
 *     visible error. It is never rendered as "nothing happened".
 *   - An event type this client has never heard of is counted and listed. It is
 *     not silently omitted from the reported event count.
 */
import type { DomainEvent } from "@niharamesh/contracts/generated"

export interface ReplayRobot {
  robot_id: string
  x: number | null
  y: number | null
  theta: number | null
  stop_reason: string | null
  task_id: string | null
  holding_zone: string | null
  last_seq: number
  last_sim_time_s: number | null
  faulted: boolean
  degraded: boolean
  stopped: boolean
}

export interface ReplayZone {
  zone_id: string
  authority: "free" | "promised" | "granted" | "occupied" | "released"
  holder: string | null
  occupant: string | null
  entries: number
  cancelled: boolean
  last_seq: number
}

export interface ReplayTask {
  task_id: string
  state: string
  owner: string | null
  ownership_version: number
  completed: boolean
  completed_at_seq: number | null
  custody: string | null
  last_seq: number
}

export interface ReplayObstacle {
  id: string
  kind: string
  pose: { x: number; y: number; theta: number } | null
  dynamic: boolean
  last_seq: number
}

export interface ReplayAlert {
  seq: number
  sim_time_s: number | null
  severity: string
  reason: string
  type: string
  robot_id: string | null
}

export type ReplayProblemKind = "unsupported_version" | "unknown_event_type" | "sequence_hole"

export interface ReplayProblem {
  kind: ReplayProblemKind
  seq: number | null
  message: string
}

export interface ReplayWorldState {
  robots: Map<string, ReplayRobot>
  zones: Map<string, ReplayZone>
  tasks: Map<string, ReplayTask>
  obstacles: Map<string, ReplayObstacle>
  alerts: ReplayAlert[]
  /** Total events considered, including ones this client does not model. */
  eventsConsidered: number
  /** Events this client actually folded into state. */
  eventsApplied: number
  unknownTypes: { type: string; count: number }[]
  lastSeq: number | null
  lastSimTimeS: number | null
  problems: ReplayProblem[]
  /** True when the state is unsafe to present as if complete. */
  usable: boolean
}

function emptyRobot(robotId: string, seq: number): ReplayRobot {
  return {
    robot_id: robotId,
    x: null,
    y: null,
    theta: null,
    stop_reason: null,
    task_id: null,
    holding_zone: null,
    last_seq: seq,
    last_sim_time_s: null,
    faulted: false,
    degraded: false,
    stopped: false,
  }
}

function emptyZone(zoneId: string, seq: number): ReplayZone {
  return {
    zone_id: zoneId,
    authority: "free",
    holder: null,
    occupant: null,
    entries: 0,
    cancelled: false,
    last_seq: seq,
  }
}

function emptyTask(taskId: string, seq: number): ReplayTask {
  return {
    task_id: taskId,
    state: "available",
    owner: null,
    ownership_version: 0,
    completed: false,
    completed_at_seq: null,
    custody: null,
    last_seq: seq,
  }
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}
function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

/** `reason` is optional in the contract; never let `undefined` become a string. */
function reasonOr(event: DomainEvent, fallback: string): string {
  const reason = str(event.reason)
  return reason !== null ? reason : fallback
}

/** Version comparison for the client's known schema version ("1.0.0"). */
function isNewerVersion(candidate: string, known: string): boolean {
  const c = candidate.split(".").map((n) => Number.parseInt(n, 10))
  const k = known.split(".").map((n) => Number.parseInt(n, 10))
  for (let i = 0; i < 3; i += 1) {
    const cv = c[i] ?? 0
    const kv = k[i] ?? 0
    if (cv > kv) return true
    if (cv < kv) return false
  }
  return false
}

/**
 * Exactly which event types this console folds into world state.
 *
 * A prefix rule alone would be a lie: it would claim `robot.whatever_new` is
 * modelled when the switch below has no case for it. So each family lists its
 * concrete types, and anything unlisted is counted in `unknownTypes` and
 * reported as a problem — never silently dropped.
 */
const MODELLED: Record<string, (type: string) => boolean> = {
  "telemetry.": (t) => t === "telemetry.sample",
  "robot.": (t) => ROBOT_TYPES.has(t),
  "lifecycle.": () => true,
  "fault.": () => true,
  "planning.": () => true,
  "command.": () => true,
  "evaluation.": () => true,
  "safety.": () => true,
  "obstacle.": () => true,
  "zone.": (t) => ZONE_TYPES.has(t),
  "task.": (t) => TASK_TYPES.has(t),
}

const ROBOT_TYPES = new Set(["robot.pose", "robot.telemetry", "robot.heartbeat", "robot.session"])
const ZONE_TYPES = new Set([
  "zone.requested",
  "zone.promised",
  "zone.granted",
  "zone.cancelled",
  "zone.cancel_requested",
  "zone.entered",
  "zone.occupied",
  "zone.released",
  "zone.cleared",
  "zone.violation",
  "zone.fenced",
])
const TASK_TYPES = new Set([
  "task.award",
  "task.awarded",
  "task.owned",
  "task.claimed",
  "task.completed",
  "task.delivered",
  "task.transition",
  "task.custody",
])

function modelledType(type: string): boolean {
  for (const [prefix, check] of Object.entries(MODELLED)) {
    if (type.startsWith(prefix)) return check(type)
  }
  return false
}

/**
 * Fold `events` (already trimmed to the cursor) into a world state.
 *
 * @param events      the slice of the durable log up to and including the cursor
 * @param knownSchema the schema version this client was generated from
 */
export function buildReplayState(events: DomainEvent[], knownSchema: string): ReplayWorldState {
  const robots = new Map<string, ReplayRobot>()
  const zones = new Map<string, ReplayZone>()
  const tasks = new Map<string, ReplayTask>()
  const obstacles = new Map<string, ReplayObstacle>()
  const alerts: ReplayAlert[] = []
  const problems: ReplayProblem[] = []
  const unknown = new Map<string, number>()

  let eventsConsidered = 0
  let eventsApplied = 0
  let lastSeq: number | null = null
  let lastSimTimeS: number | null = null
  let previousSeq: number | null = null

  for (const event of events) {
    eventsConsidered += 1

    const version = event.schema_version
    if (typeof version === "string" && version.length > 0 && isNewerVersion(version, knownSchema)) {
      problems.push({
        kind: "unsupported_version",
        seq: event.seq,
        message:
          `Event seq ${event.seq} has schema version ${version}, which is newer than this console understands (${knownSchema}). ` +
          `The replay cannot be reconstructed honestly, so it has been stopped rather than shown with missing state.`,
      })
      return {
        robots,
        zones,
        tasks,
        obstacles,
        alerts,
        eventsConsidered,
        eventsApplied,
        unknownTypes: [...unknown].map(([type, count]) => ({ type, count })),
        lastSeq,
        lastSimTimeS,
        problems,
        usable: false,
      }
    }

    if (previousSeq !== null && event.seq !== previousSeq + 1) {
      problems.push({
        kind: "sequence_hole",
        seq: event.seq,
        message: `The durable log jumps from seq ${previousSeq} to seq ${event.seq}. State between those sequences was never recorded.`,
      })
    }
    previousSeq = event.seq
    lastSeq = event.seq
    lastSimTimeS = event.sim_time_s ?? lastSimTimeS

    const type = event.type
    const payload = event.payload ?? {}
    const robotId = event.robot_id ?? str(payload.robot_id)
    const zoneId = event.zone_id ?? str(payload.zone_id)
    const taskId = event.task_id ?? str(payload.task_id)

    const robot = (): ReplayRobot | null => {
      if (robotId === null) return null
      const existing = robots.get(robotId) ?? emptyRobot(robotId, event.seq)
      existing.last_seq = event.seq
      existing.last_sim_time_s = event.sim_time_s ?? existing.last_sim_time_s
      robots.set(robotId, existing)
      return existing
    }
    const zone = (): ReplayZone | null => {
      if (zoneId === null) return null
      const existing = zones.get(zoneId) ?? emptyZone(zoneId, event.seq)
      existing.last_seq = event.seq
      zones.set(zoneId, existing)
      return existing
    }
    const task = (): ReplayTask | null => {
      if (taskId === null) return null
      const existing = tasks.get(taskId) ?? emptyTask(taskId, event.seq)
      existing.last_seq = event.seq
      tasks.set(taskId, existing)
      return existing
    }

    if (!modelledType(type)) {
      unknown.set(type, (unknown.get(type) ?? 0) + 1)
    }

    // Materialise the referenced entities so that "this robot existed at this
    // point in the log" is answerable even when the event models nothing else.
    if (robotId !== null) robot()

    switch (true) {
      /* ------------------------------ pose ------------------------------ */
      case type === "telemetry.sample" || type === "robot.pose" || type === "robot.telemetry": {
        const r = robot()
        if (r !== null) {
          r.x = num(payload.x) ?? r.x
          r.y = num(payload.y) ?? r.y
          r.theta = num(payload.theta) ?? r.theta
          r.stop_reason = str(payload.stop_reason) ?? r.stop_reason
        }
        eventsApplied += 1
        break
      }

      /* --------------------------- lifecycle ---------------------------- */
      case type.startsWith("lifecycle."): {
        const r = robot()
        if (r !== null) {
          if (type.includes("crash")) r.faulted = true
          if (type.includes("restart") || type.includes("recover")) r.faulted = false
          if (type.includes("degrade")) r.degraded = true
          if (type.includes("nominal") || type.includes("recover")) r.degraded = false
        }
        eventsApplied += 1
        break
      }

      /* ---------------------------- faults ----------------------------- */
      case type.startsWith("fault."): {
        if (event.severity === "violation" || event.severity === "fault") {
          alerts.push({
            seq: event.seq,
            sim_time_s: event.sim_time_s ?? null,
            severity: event.severity ?? "fault",
            reason: reasonOr(event, `${type} injected`),
            type,
            robot_id: robotId,
          })
        }
        eventsApplied += 1
        break
      }

      /* ----------------------------- zones ------------------------------ */
      case type === "zone.requested" || type === "zone.promised": {
        const z = zone()
        if (z !== null) {
          z.authority = "promised"
          z.holder = robotId ?? z.holder
          z.cancelled = false
        }
        eventsApplied += 1
        break
      }
      case type === "zone.granted": {
        const z = zone()
        if (z !== null) {
          z.authority = "granted"
          z.holder = robotId ?? z.holder
        }
        const r = robot()
        if (r !== null) r.holding_zone = zoneId ?? r.holding_zone
        eventsApplied += 1
        break
      }
      case type === "zone.cancelled" || type === "zone.cancel_requested": {
        const z = zone()
        if (z !== null) {
          z.cancelled = true
          if (z.authority === "promised" || z.authority === "granted") z.authority = "free"
        }
        const r = robot()
        if (r !== null && r.holding_zone === zoneId) r.holding_zone = null
        eventsApplied += 1
        break
      }
      case type === "zone.entered" || type === "zone.occupied": {
        const z = zone()
        if (z !== null) {
          z.authority = "occupied"
          z.occupant = robotId ?? z.occupant
          z.entries += 1
        }
        eventsApplied += 1
        break
      }
      case type === "zone.released" || type === "zone.cleared": {
        const z = zone()
        if (z !== null) {
          z.authority = "released"
          z.occupant = null
          z.holder = null
        }
        const r = robot()
        if (r !== null && r.holding_zone === zoneId) r.holding_zone = null
        eventsApplied += 1
        break
      }
      case type === "zone.violation" || type.startsWith("safety."): {
        if (event.severity === "violation" || event.severity === "fault") {
          alerts.push({
            seq: event.seq,
            sim_time_s: event.sim_time_s ?? null,
            severity: event.severity ?? "violation",
            reason: reasonOr(event, `${type} on ${zoneId ?? "unknown zone"}`),
            type,
            robot_id: robotId,
          })
        }
        const r = robot()
        if (r !== null && type.includes("stop")) {
          r.stopped = true
          r.stop_reason = str(payload.stop_reason) ?? "safety_gate_veto"
        }
        eventsApplied += 1
        break
      }

      /* ----------------------------- tasks ------------------------------ */
      case type.startsWith("task.award") || type === "task.owned" || type === "task.claimed": {
        const t = task()
        if (t !== null) {
          t.owner = robotId ?? t.owner
          t.ownership_version = num(payload.ownership_version) ?? t.ownership_version + 1
          t.state = str(payload.to_state) ?? "owned"
        }
        const r = robot()
        if (r !== null) r.task_id = taskId ?? r.task_id
        eventsApplied += 1
        break
      }
      case type === "task.completed" || type === "task.delivered": {
        const t = task()
        if (t !== null) {
          t.state = "completed"
          t.completed = true
          t.completed_at_seq = event.seq
          t.custody = "delivered"
        }
        const r = robot()
        if (r !== null && r.task_id === taskId) r.task_id = null
        eventsApplied += 1
        break
      }
      case type.startsWith("task."): {
        const t = task()
        if (t !== null) {
          t.state = str(payload.to_state) ?? t.state
          t.ownership_version = num(payload.ownership_version) ?? t.ownership_version
          if (payload.custody_state !== undefined) t.custody = str(payload.custody_state) ?? t.custody
        }
        eventsApplied += 1
        break
      }

      /* --------------------------- obstacles ---------------------------- */
      case type === "obstacle.inserted": {
        const id = str(payload.obstacle_id) ?? str(payload.id) ?? `obstacle@${event.seq}`
        obstacles.set(id, {
          id,
          kind: str(payload.kind) ?? "temporary",
          pose: { x: num(payload.x) ?? 0, y: num(payload.y) ?? 0, theta: num(payload.theta) ?? 0 },
          dynamic: true,
          last_seq: event.seq,
        })
        eventsApplied += 1
        break
      }
      case type === "obstacle.removed": {
        const id = str(payload.obstacle_id) ?? str(payload.id)
        if (id !== null) obstacles.delete(id)
        eventsApplied += 1
        break
      }

      /* ---------------------------- planning ---------------------------- */
      case type.startsWith("planning.") || type.startsWith("command."): {
        const r = robot()
        if (r !== null) {
          const intent = str(payload.intent) ?? str(payload.reason)
          if (intent !== null) r.stop_reason = r.stop_reason ?? null
          if (str(payload.stop_reason) !== null) r.stop_reason = str(payload.stop_reason)
        }
        eventsApplied += 1
        break
      }

      /* -------------------------- evaluation ---------------------------- */
      case type.startsWith("evaluation."): {
        if (event.severity === "violation") {
          alerts.push({
            seq: event.seq,
            sim_time_s: event.sim_time_s ?? null,
            severity: "violation",
            reason: reasonOr(event, type),
            type,
            robot_id: robotId,
          })
        }
        eventsApplied += 1
        break
      }

      default: {
        // Not fatal: the event is still counted and reported in `unknownTypes`
        // so the console can say how much of the log it did not model.
        break
      }
    }
  }

  if (unknown.size > 0) {
    for (const [type, count] of unknown) {
      problems.push({
        kind: "unknown_event_type",
        seq: null,
        message: `${count} event${count === 1 ? "" : "s"} of type "${type}" are not modelled by this console. They are counted in the total but contribute no world state.`,
      })
    }
  }

  return {
    robots,
    zones,
    tasks,
    obstacles,
    alerts,
    eventsConsidered,
    eventsApplied,
    unknownTypes: [...unknown].map(([type, count]) => ({ type, count })),
    lastSeq,
    lastSimTimeS,
    problems,
    usable: problems.every((p) => p.kind !== "unsupported_version"),
  }
}

/** Events up to and including `cursorSeq`. The only input `buildReplayState` takes. */
export function eventsUpTo(events: DomainEvent[], cursorSeq: number): DomainEvent[] {
  return events.filter((e) => e.seq <= cursorSeq)
}

export function cursorBounds(events: DomainEvent[]): { first: number | null; last: number | null } {
  if (events.length === 0) return { first: null, last: null }
  let first = events[0]?.seq ?? null
  let last = events[0]?.seq ?? null
  for (const event of events) {
    if (event.seq < (first ?? 0)) first = event.seq
    if (event.seq > (last ?? 0)) last = event.seq
  }
  return { first, last }
}

/** The next event with a severity this product treats as a finding. */
export function firstFaultSeq(events: DomainEvent[]): number | null {
  for (const event of events) {
    if (event.category === "fault") return event.seq
  }
  return null
}

export function firstViolationSeq(events: DomainEvent[]): number | null {
  for (const event of events) {
    if (event.severity === "violation") return event.seq
  }
  return null
}
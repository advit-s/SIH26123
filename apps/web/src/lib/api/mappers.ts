/**
 * Wire -> read-model mapping.
 *
 * The API is developed in parallel with this cockpit, so every mapper is
 * **tolerant of a missing field but never invents one**. A missing number maps
 * to `null` and a missing metric maps to `source: "unavailable"`. Nothing here
 * substitutes a default, a zero, or an "empty" object, because that is exactly
 * how a dashboard ends up telling an operator that a zone is free when the
 * recorder simply never wrote a release.
 *
 * Domain objects that the contracts package already defines (Zone, Task,
 * RunManifest, FaultRecord, DomainEvent, ...) are cast through after a shallow
 * shape check rather than re-declared.
 */
import type {
  BatteryState,
  DomainEvent,
  FaultRecord,
  Pose2,
  PoseEstimate,
  ReplayIndex,
  RunDescriptor,
  RunManifest,
  RunResult,
  Scenario,
  Task,
  TaskOwnership,
  Zone,
} from "@niharamesh/contracts/generated"
import type {
  AgentReason,
  ApiMode,
  BatterySource,
  BidComponentSet,
  BidComponentView,
  CommandReceipt,
  CommandRecord,
  CommandStageState,
  CommunicationCell,
  DoctorReport,
  EventPage,
  ExperimentBatchSummary,
  ExperimentCell,
  ExperimentDetail,
  ExperimentMatrix,
  FreshnessClass,
  HealthStatus,
  MapGeometry,
  PairedRow,
  ReplayDetail,
  ReportBundle,
  RobotInspection,
  RunDetail,
  RunStateSnapshot,
  ScenarioDetail,
  ScenarioSummary,
  Sourced,
  TaskInspection,
  TelemetryPage,
  TelemetrySampleView,
  ValidationProblem,
  ValidationReport,
  WhyWaiting,
  ZoneHoldView,
  ZoneInspection,
  ZoneOccupancyView,
  ZoneRequestView,
  ZoneResponseView,
} from "./types"
import type { ApiPolicy, MetricSource, MotionState } from "./types"

/* -------------------------------------------------------------------------- */
/* Primitive readers. Each returns `null` rather than a default.               */
/* -------------------------------------------------------------------------- */

type Json = Record<string, unknown>

function obj(value: unknown): Json | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? (value as Json) : null
}

function arr(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function str(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null
}

export function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null
}

export function bool(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null
}

export function strList(value: unknown): string[] {
  return arr(value).filter((v): v is string => typeof v === "string")
}

/** `[x, y]` tuples arrive as `[unknown, unknown]` from the generated types. */
export function point(value: unknown): [number, number] | null {
  if (!Array.isArray(value) || value.length < 2) return null
  const a = num(value[0])
  const b = num(value[1])
  return a === null || b === null ? null : [a, b]
}

export function pointList(value: unknown): [number, number][] {
  const out: [number, number][] = []
  for (const item of arr(value)) {
    const p = point(item)
    if (p !== null) out.push(p)
  }
  return out
}

function pose(value: unknown): Pose2 | null {
  const o = obj(value)
  if (o === null) return null
  const x = num(o.x)
  const y = num(o.y)
  const theta = num(o.theta)
  if (x === null || y === null) return null
  return { x, y, theta: theta ?? 0 }
}

function nested(source: unknown, key: string): unknown {
  return obj(source)?.[key]
}

function nestedObj(source: unknown, key: string): Json | null {
  return obj(nested(source, key))
}

function nestedList(source: unknown, key: string): unknown[] {
  return arr(nested(source, key))
}

/** `0` is a legitimate value; only `null`/`undefined` are absent. */
function pickNum(source: unknown, key: string): number | null {
  const o = obj(source)
  return o === null ? null : num(o[key])
}

function pickStr(source: unknown, key: string): string | null {
  const o = obj(source)
  return o === null ? null : str(o[key])
}

function pickBool(source: unknown, key: string): boolean | null {
  const o = obj(source)
  return o === null ? null : bool(o[key])
}

/**
 * Read a number that must declare where it came from. If the API omits the
 * source we report `unavailable` rather than assuming "measured".
 */
export function sourced(
  source: unknown,
  key: string,
  fallbackSource: MetricSource = "measured",
): Sourced {
  const o = obj(source)
  if (o === null) return { value: null, source: "unavailable", age_s: null }
  const rawSource = str(o.source)
  const allowed: MetricSource[] = ["measured", "simulated", "estimated", "unavailable"]
  const src: MetricSource =
    rawSource !== null && (allowed as string[]).includes(rawSource) ? (rawSource as MetricSource) : fallbackSource
  const raw = o[key]
  const value = num(raw)
  if (value === null) return { value: null, source: "unavailable", age_s: pickNum(o, "age_s"), note: str(o.note) ?? undefined }
  return { value, source: src, age_s: pickNum(o, "age_s"), note: str(o.note) ?? undefined }
}

/* -------------------------------------------------------------------------- */
/* Health / doctor                                                            */
/* -------------------------------------------------------------------------- */

export function mapHealth(raw: unknown): HealthStatus {
  const o = obj(raw) ?? {}
  const status = str(o.status) === "degraded" ? "degraded" : "ok"
  const mode = str(o.mode) ?? "unknown"
  return {
    status,
    version: str(o.version) ?? "unknown",
    schema_version: str(o.schema_version) ?? "unknown",
    protocol_version: str(o.protocol_version) ?? "unknown",
    mode,
    run_id: str(o.run_id),
    recording_healthy: pickBool(o, "recording_healthy") ?? false,
    uptime_s: num(o.uptime_s) ?? 0,
  }
}

const CHECK_STATUSES = new Set(["pass", "warn", "fail", "unknown"])

export function mapDoctor(raw: unknown): DoctorReport {
  const o = obj(raw) ?? {}
  const build = nestedObj(o, "build") ?? {}
  const compat = nestedObj(o, "schema_compatibility") ?? {}
  const recording = nestedObj(o, "recording") ?? {}
  return {
    generated_at_utc: str(o.generated_at_utc) ?? "",
    build: {
      version: str(build.version) ?? "unknown",
      schema_version: str(build.schema_version) ?? "unknown",
      protocol_version: str(build.protocol_version) ?? "unknown",
      source_revision: str(build.source_revision),
      config_digest: str(build.config_digest),
    },
    schema_compatibility: {
      expected: str(compat.expected) ?? "unknown",
      actual: str(compat.actual),
      status: CHECK_STATUSES.has(String(compat.status)) ? (compat.status as "pass") : "unknown",
      detail: str(compat.detail) ?? "The API did not report schema compatibility details.",
    },
    recording: {
      healthy: pickBool(recording, "healthy") ?? false,
      gaps: arr(recording.gaps) as never[],
      detail: str(recording.detail) ?? "No recording health detail was published.",
    },
    processes: arr(o.processes).map((p) => {
      const po = obj(p) ?? {}
      const raw_status = str(po.status)
      const status: "running" | "stopped" | "unknown" =
        raw_status === "running" || raw_status === "stopped" ? raw_status : "unknown"
      return {
        name: str(po.name) ?? "unnamed",
        role: str(po.role) ?? "",
        status,
        pid: num(po.pid),
        host: str(po.host),
      }
    }),
    endpoints: arr(o.endpoints).map((e) => {
      const eo = obj(e) ?? {}
      const raw_status = str(eo.status)
      return {
        name: str(eo.name) ?? "endpoint",
        url: str(eo.url) ?? "",
        status: CHECK_STATUSES.has(String(raw_status)) ? (raw_status as "pass") : "unknown",
        latency_ms: num(eo.latency_ms),
      }
    }),
    journals: arr(o.journals).map((j) => {
      const jo = obj(j) ?? {}
      const raw_status = str(jo.status)
      return {
        name: str(jo.name) ?? "journal",
        path: str(jo.path),
        status: CHECK_STATUSES.has(String(raw_status)) ? (raw_status as "pass") : "unknown",
        detail: str(jo.detail) ?? "",
      }
    }),
    checks: arr(o.checks).map((c) => {
      const co = obj(c) ?? {}
      const raw_status = str(co.status)
      return {
        id: str(co.id) ?? str(co.label) ?? "check",
        label: str(co.label) ?? "Unnamed check",
        status: CHECK_STATUSES.has(String(raw_status)) ? (raw_status as "pass") : "unknown",
        detail: str(co.detail) ?? "",
        measured: obj(co.measured) as Record<string, string | number | boolean | null> | null,
      }
    }),
  }
}

/* -------------------------------------------------------------------------- */
/* Scenarios                                                                  */
/* -------------------------------------------------------------------------- */

export function mapValidationReport(raw: unknown): ValidationReport {
  const o = obj(raw) ?? {}
  const problems: ValidationProblem[] = arr(o.problems).map((p) => {
    const po = obj(p) ?? {}
    const sev = str(po.severity)
    return {
      code: str(po.code) ?? "unknown",
      severity: sev === "error" || sev === "warning" || sev === "info" ? sev : "error",
      path: str(po.path) ?? "",
      message: str(po.message) ?? "The API reported a problem with no message.",
      hint: str(po.hint) ?? undefined,
    }
  })
  const counts = nestedObj(o, "counts") ?? {}
  const errorCount = num(counts.error) ?? problems.filter((p) => p.severity === "error").length
  const warningCount = num(counts.warning) ?? problems.filter((p) => p.severity === "warning").length
  const infoCount = num(counts.info) ?? problems.filter((p) => p.severity === "info").length
  const valid = pickBool(o, "valid")
  const launchable = pickBool(o, "launchable")
  return {
    validated: true,
    valid: valid ?? errorCount === 0,
    launchable: launchable ?? errorCount === 0,
    scenario_digest: str(o.scenario_digest),
    problems,
    counts: { error: errorCount, warning: warningCount, info: infoCount },
    expected_failure: pickBool(o, "expected_failure") ?? false,
    expected_failure_reason: str(o.expected_failure_reason),
  }
}

export function mapScenarioSummary(raw: unknown): ScenarioSummary {
  const o = obj(raw) ?? {}
  return {
    scenario_id: str(o.scenario_id) ?? "unknown",
    name: str(o.name) ?? "Unnamed scenario",
    revision: num(o.revision) ?? 0,
    kind: str(o.kind) ?? "nominal",
    description: str(o.description),
    robot_count: num(o.robot_count) ?? 0,
    task_count: num(o.task_count) ?? 0,
    zone_count: num(o.zone_count) ?? 0,
    updated_utc: str(o.updated_utc),
    map_id: str(o.map_id),
    map_revision: num(o.map_revision),
  }
}

export function mapScenarioDetail(raw: unknown): ScenarioDetail {
  const o = obj(raw) ?? {}
  const scenario = (nested(o, "scenario") ?? nested(o, "document") ?? {}) as Scenario
  const validationRaw = nested(o, "validation") ?? nested(o, "validation_report")
  return {
    scenario_id: str(o.scenario_id) ?? scenario.scenario_id ?? "unknown",
    revision: num(o.revision) ?? scenario.revision ?? 0,
    scenario,
    validation: validationRaw ? mapValidationReport(validationRaw) : emptyValidation(),
  }
}

/** A validation report for a draft the API has not seen yet. Never "valid". */
export function emptyValidation(): ValidationReport {
  return {
    validated: false,
    valid: false,
    launchable: false,
    scenario_digest: null,
    problems: [],
    counts: { error: 0, warning: 0, info: 0 },
    expected_failure: false,
    expected_failure_reason: null,
  }
}

/* -------------------------------------------------------------------------- */
/* Runs                                                                       */
/* -------------------------------------------------------------------------- */

export function mapRunDescriptor(raw: unknown): RunDescriptor {
  const o = obj(raw) ?? {}
  return {
    run_id: str(o.run_id) ?? "unknown",
    state: (str(o.state) ?? "queued") as RunDescriptor["state"],
    outcome: (str(o.outcome) ?? "failed") as RunDescriptor["outcome"],
    scenario_revision: num(o.scenario_revision) ?? 0,
    seed: num(o.seed) ?? 0,
    coordination_policy: str(o.coordination_policy) ?? "unknown",
    created_utc_ns: num(o.created_utc_ns) ?? 0,
    sim_duration_s: num(o.sim_duration_s) ?? 0,
    tasks_completed: num(o.tasks_completed) ?? 0,
    tasks_total: num(o.tasks_total) ?? 0,
    collisions: num(o.collisions) ?? 0,
    makespan_s: num(o.makespan_s),
    evidence_complete: pickBool(o, "evidence_complete") ?? false,
    note: str(o.note) ?? undefined,
    idempotency_key: str(o.idempotency_key) ?? undefined,
  }
}

export function mapRunDetail(raw: unknown): RunDetail {
  const o = obj(raw) ?? {}
  return {
    run_id: str(o.run_id) ?? "unknown",
    manifest: (nested(o, "manifest") ?? {}) as RunManifest,
    state: str(o.state) ?? "unknown",
    result: (nested(o, "result") ?? null) as RunResult | null,
    recording_healthy: pickBool(o, "recording_healthy") ?? false,
    scenario: (nested(o, "scenario") ?? nested(o, "snapshot") ?? null) as Scenario | null,
    snapshot_id: str(o.snapshot_id),
  }
}

export function mapRunState(raw: unknown): RunStateSnapshot {
  const o = obj(raw) ?? {}
  const paused = pickBool(o, "paused")
  const state = str(o.state) ?? "unknown"
  const mode: ApiMode | string = str(o.mode) ?? "unknown"
  return {
    run_id: str(o.run_id) ?? "unknown",
    mode,
    state,
    outcome: str(o.outcome) ?? "unknown",
    sim_time_s: num(o.sim_time_s) ?? 0,
    wall_time_utc: str(o.wall_time_utc),
    speed_multiplier: num(o.speed_multiplier),
    paused: paused ?? state === "paused",
    tick: num(o.tick),
    max_sim_time_s: num(o.max_sim_time_s),
    robot_count: num(o.robot_count) ?? 0,
    coordination_policy: str(o.coordination_policy) ?? "unknown",
    assignment_policy: str(o.assignment_policy),
    routing_policy: str(o.routing_policy),
    scenario_id: str(o.scenario_id),
    scenario_revision: num(o.scenario_revision),
    scenario_digest: str(o.scenario_digest),
    map_id: str(o.map_id),
    map_revision: num(o.map_revision),
    map_digest: str(o.map_digest),
    recording_healthy: pickBool(o, "recording_healthy") ?? false,
    recording_gaps: arr(o.recording_gaps) as never[],
    last_seq: num(o.last_seq) ?? 0,
  }
}

/* -------------------------------------------------------------------------- */
/* Robots                                                                     */
/* -------------------------------------------------------------------------- */

function battery(value: unknown): BatteryState | null {
  const o = obj(value)
  if (o === null) return null
  const raw = str(o.source)
  const source: BatterySource =
    raw === "measured" || raw === "simulated" || raw === "estimated" ? raw : "unavailable"
  return {
    source,
    fraction: num(o.fraction),
    drain_model: str(o.drain_model),
    estimated_range_m: num(o.estimated_range_m),
  }
}

function motion(value: unknown): MotionState | null {
  const o = obj(value)
  if (o === null) return null
  const stopReason = str(o.stop_reason)
  const actuator = str(o.actuator)
  const allowedStops = [
    "none",
    "command_expired",
    "safety_gate_veto",
    "zone_authority_missing",
    "freshness_uncertain",
    "obstacle_in_path",
    "stale_localisation",
    "control_loop_stalled",
    "operator_request",
    "scheduled_stop",
    "workload_complete",
    "crash_recovery",
    "actuator_fault",
  ]
  const allowedActuators = ["enabled", "disabled", "braking", "watchdog_braking", "estop", "fault"]
  return {
    ...(stopReason !== null && (allowedStops as string[]).includes(stopReason)
      ? { stop_reason: stopReason as MotionState["stop_reason"] }
      : {}),
    ...(num(o.linear_velocity_mps) === null ? {} : { linear_velocity_mps: num(o.linear_velocity_mps) as number }),
    ...(num(o.angular_velocity_radps) === null
      ? {}
      : { angular_velocity_radps: num(o.angular_velocity_radps) as number }),
    ...(num(o.commanded_linear_mps) === null ? {} : { commanded_linear_mps: num(o.commanded_linear_mps) as number }),
    ...(num(o.commanded_angular_radps) === null
      ? {}
      : { commanded_angular_radps: num(o.commanded_angular_radps) as number }),
    ...(num(o.command_seq) === null ? {} : { command_seq: num(o.command_seq) as number }),
    ...(num(o.command_expires_at_ns) === null ? {} : { command_expires_at_ns: num(o.command_expires_at_ns) as number }),
    ...(actuator !== null && (allowedActuators as string[]).includes(actuator)
      ? { actuator: actuator as MotionState["actuator"] }
      : {}),
    ...(bool(o.actuation_enabled) === null ? {} : { actuation_enabled: bool(o.actuation_enabled) as boolean }),
  }
}

function whyWaiting(value: unknown): WhyWaiting | null {
  const o = obj(value)
  if (o === null) return null
  return {
    blocked: pickBool(o, "blocked") ?? false,
    reason: str(o.reason) ?? "The API did not explain this robot's current hold.",
    blocking_request_id: str(o.blocking_request_id),
    blocking_peer: str(o.blocking_peer),
    blocking_resource: str(o.blocking_resource),
    blocking_zone_id: str(o.blocking_zone_id),
    evidence_age_s: num(o.evidence_age_s),
    recovery_condition: str(o.recovery_condition),
    timer_expires_permission_only: pickBool(o, "timer_expires_permission_only") ?? true,
  }
}

function reasons(value: unknown): AgentReason[] {
  return arr(value)
    .map((r) => {
      const ro = obj(r) ?? {}
      return {
        at_seq: num(ro.at_seq) ?? 0,
        sim_time_s: num(ro.sim_time_s),
        category: str(ro.category) ?? "note",
        text: str(ro.text) ?? "",
        severity: str(ro.severity) ?? "info",
      }
    })
    .filter((r) => r.text.length > 0)
    .slice(-12)
}

function zoneHolds(value: unknown): ZoneHoldView[] {
  return arr(value).map((h) => {
    const ho = obj(h) ?? {}
    return {
      zone_id: str(ho.zone_id) ?? "",
      robot_id: str(ho.robot_id) ?? "",
      state: str(ho.state) ?? "unknown",
      since_seq: num(ho.since_seq),
      acquired_at_sim_s: num(ho.acquired_at_sim_s),
    }
  })
}

function zoneOccupancies(value: unknown): ZoneOccupancyView[] {
  return arr(value).map((z) => {
    const zo = obj(z) ?? {}
    const source = str(zo.source)
    return {
      zone_id: str(zo.zone_id) ?? "",
      occupant: str(zo.occupant),
      state: str(zo.state) ?? "unknown",
      source: source === "evaluator" ? "evaluator" : "agent_report",
      confidence: num(zo.confidence),
      age_s: num(zo.age_s),
    }
  })
}

export function mapRobotInspection(raw: unknown, index: number): RobotInspection {
  const o = obj(raw) ?? {}
  const identityObj = obj(nested(o, "identity"))
  const robotId = str(o.robot_id) ?? str(identityObj?.robot_id) ?? "unknown"
  const identity =
    identityObj !== null
      ? (identityObj as unknown as RobotInspection["identity"])
      : ({ robot_id: robotId, footprint: { length_m: 0.9, width_m: 0.7 } } as RobotInspection["identity"])
  return {
    robot_id: robotId,
    index,
    identity,
    session: (nested(o, "session") ?? null) as never,
    pose_estimate: (nested(o, "pose_estimate") ?? null) as PoseEstimate | null,
    motion: motion(o.motion),
    battery: battery(nested(o, "battery")),
    task: (nested(o, "task") ?? null) as Task | null,
    ownership: (nested(o, "ownership") ?? null) as TaskOwnership | null,
    custody: (nested(o, "custody") ?? null) as never,
    carrying_payload: pickBool(o, "carrying_payload") ?? false,
    held_zones: zoneHolds(o.held_zones),
    observed_zones: zoneOccupancies(o.observed_zones),
    last_accepted_intent: str(o.last_accepted_intent),
    planner_state: str(o.planner_state),
    plan_version: num(o.plan_version),
    map_epoch: str(o.map_epoch),
    degraded: pickBool(o, "degraded") ?? false,
    degraded_reason: str(o.degraded_reason),
    why_waiting: whyWaiting(o.why_waiting),
    reasons: reasons(o.reasons),
    stale: pickBool(o, "stale") ?? false,
    pose_age_s: num(o.pose_age_s),
    recent_events: arr(o.recent_events) as DomainEvent[],
  }
}

export function mapRobots(raw: unknown): RobotInspection[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "robots"))
  return list.map((r, i) => mapRobotInspection(r, i))
}

/* -------------------------------------------------------------------------- */
/* Zones                                                                      */
/* -------------------------------------------------------------------------- */

function zoneResponse(value: unknown): ZoneResponseView {
  const o = obj(value) ?? {}
  const response = str(o.response)
  return {
    peer: str(o.peer) ?? str(o.robot_id) ?? "unknown",
    response: response === "grant" || response === "refuse" ? response : "no_response",
    reason: str(o.reason),
    age_s: num(o.age_s),
    at_seq: num(o.at_seq),
  }
}

function zoneRequest(value: unknown): ZoneRequestView {
  const o = obj(value) ?? {}
  const responses = arr(o.responses).map(zoneResponse)
  const required = strList(o.required_peers)
  return {
    request_id: str(o.request_id) ?? "unknown",
    requester: str(o.requester) ?? "unknown",
    state: str(o.state) ?? "unknown",
    required_peers: required,
    responses_received: responses,
    responses_required: num(o.responses_required) ?? required.length,
    responses_received_count: responses.filter((r) => r.response !== "no_response").length,
    outstanding: strList(o.outstanding),
    granted_at_seq: num(o.granted_at_seq),
    cancelled: pickBool(o, "cancelled") ?? false,
    note: str(o.note),
  }
}

const AUTHORITIES = new Set(["held", "granted_pending_entry", "free", "contested", "occupied", "unknown"])

export function mapZoneInspection(raw: unknown): ZoneInspection {
  const o = obj(raw) ?? {}
  const mapZone = (nested(o, "map_zone") ?? nested(o, "zone") ?? null) as Zone | null
  const authorityRaw = str(o.authority)
  return {
    zone_id: str(o.zone_id) ?? mapZone?.id ?? "unknown",
    map_zone: mapZone,
    authority: AUTHORITIES.has(String(authorityRaw)) ? (authorityRaw as ZoneInspection["authority"]) : "unknown",
    authority_holder: str(o.authority_holder),
    physical_occupancy:
      str(o.physical_occupancy) === "occupied" ? "occupied" : str(o.physical_occupancy) === "believed_free" ? "believed_free" : "unknown",
    occupant: str(o.occupant),
    evaluator_occupancy: bool(o.evaluator_occupancy),
    entries: num(o.entries) ?? 0,
    requests: arr(o.requests).map(zoneRequest),
    entry_withheld: pickBool(o, "entry_withheld") ?? false,
    entry_withheld_reason: str(o.entry_withheld_reason),
    required_peers: strList(o.required_peers),
    stop_line_in: str(o.stop_line_in),
    stop_line_out: str(o.stop_line_out),
    queue_berth_id: str(o.queue_berth_id),
    exit_berth_id: str(o.exit_berth_id),
    protected_origin: point(nested(o, "protected_origin")),
    protected_extent: point(nested(o, "protected_extent")),
    entry_pose: pose(nested(o, "entry_pose")),
    exit_pose: pose(nested(o, "exit_pose")),
  }
}

export function mapZones(raw: unknown): ZoneInspection[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "zones"))
  return list.map(mapZoneInspection)
}

/* -------------------------------------------------------------------------- */
/* Tasks                                                                      */
/* -------------------------------------------------------------------------- */

function bidSet(value: unknown): BidComponentSet {
  const o = obj(value) ?? {}
  const components: BidComponentView[] = arr(o.components).map((c) => {
    const co = obj(c) ?? {}
    return {
      name: str(co.name) ?? "component",
      value: num(co.value) ?? 0,
      unit: str(co.unit) ?? "",
    }
  })
  return {
    robot_id: str(o.robot_id) ?? "unknown",
    total_cost: num(o.total_cost) ?? 0,
    feasible: pickBool(o, "feasible") ?? true,
    infeasible_reason: str(o.infeasible_reason),
    components,
    tie_break: num(o.tie_break),
    round_id: str(o.round_id),
  }
}

export function mapTaskInspection(raw: unknown): TaskInspection {
  const o = obj(raw) ?? {}
  const task = (nested(o, "task") ?? null) as Task | null
  const bids = arr(o.bids).map(bidSet)
  return {
    task_id: str(o.task_id) ?? task?.task_id ?? "unknown",
    task,
    owner: str(o.owner),
    ownership_version: num(o.ownership_version) ?? 0,
    ownership_state: str(o.ownership_state) ?? "unowned",
    custody: (nested(o, "custody") ?? null) as never,
    bids,
    feasible_bids: num(o.feasible_bids) ?? bids.filter((b) => b.feasible).length,
    infeasible_bids: num(o.infeasible_bids) ?? bids.filter((b) => !b.feasible).length,
    awarded: pickBool(o, "awarded") ?? false,
    winner: str(o.winner),
    completed: pickBool(o, "completed") ?? false,
    completion_evidence: (nested(o, "completion_evidence") ?? null) as DomainEvent | null,
    blocked_reason: str(o.blocked_reason),
  }
}

export function mapTasks(raw: unknown): TaskInspection[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "tasks"))
  return list.map(mapTaskInspection)
}

/* -------------------------------------------------------------------------- */
/* Communication                                                              */
/* -------------------------------------------------------------------------- */

const FRESHNESS = new Set<unknown>(["fresh", "aging", "stale", "unknown", "never"])

export function mapCommunication(raw: unknown): CommunicationCell[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "matrix"))
  return list.map((c) => {
    const co = obj(c) ?? {}
    const freshness = co.freshness
    return {
      from: str(co.from) ?? "unknown",
      to: str(co.to) ?? "unknown",
      heard: pickBool(co, "heard") ?? false,
      last_rx_age_s: num(co.last_rx_age_s),
      dropped: num(co.dropped) ?? 0,
      freshness: FRESHNESS.has(freshness) ? (freshness as FreshnessClass) : "unknown",
      note: str(co.note),
    }
  })
}

/* -------------------------------------------------------------------------- */
/* Telemetry / events                                                         */
/* -------------------------------------------------------------------------- */

export function mapTelemetrySample(raw: unknown): TelemetrySampleView | null {
  const o = obj(raw)
  if (o === null) return null
  const x = num(o.x)
  const y = num(o.y)
  const theta = num(o.theta)
  const simTime = num(o.sim_time_s)
  const robotId = str(o.robot_id)
  if (x === null || y === null || theta === null || simTime === null || robotId === null) return null
  return {
    run_id: str(o.run_id) ?? "unknown",
    robot_id: robotId,
    sample_index: num(o.sample_index) ?? 0,
    sim_time_s: simTime,
    x,
    y,
    theta,
    linear_mps: num(o.linear_mps) ?? 0,
    angular_radps: num(o.angular_radps) ?? 0,
    battery_fraction: num(o.battery_fraction),
    stop_reason: str(o.stop_reason),
  }
}

export function mapTelemetryPage(raw: unknown): TelemetryPage {
  const o = obj(raw) ?? {}
  return {
    samples: arr(o.samples).map(mapTelemetrySample).filter((s): s is TelemetrySampleView => s !== null),
    next_index: num(o.next_index) ?? 0,
  }
}

export function mapEventPage(raw: unknown): EventPage {
  const o = obj(raw) ?? {}
  return {
    events: arr(o.events) as DomainEvent[],
    next_seq: num(o.next_seq) ?? 0,
    has_more: pickBool(o, "has_more") ?? false,
  }
}

/* -------------------------------------------------------------------------- */
/* Commands                                                                   */
/* -------------------------------------------------------------------------- */

const STAGES = new Set<unknown>(["unknown", "requested", "acknowledged", "applied", "observed", "refused", "failed"])

function stage(value: unknown): CommandStageState {
  const o = obj(value)
  if (o === null) return { state: "unknown", at_utc: null, detail: null }
  const raw = o.state
  return {
    state: STAGES.has(raw) ? (raw as CommandStageState["state"]) : "unknown",
    at_utc: str(o.at_utc),
    detail: str(o.detail),
  }
}

export function mapCommandRecord(raw: unknown): CommandRecord {
  const o = obj(raw) ?? {}
  return {
    command_id: str(o.command_id) ?? "unknown",
    idempotency_key: str(o.idempotency_key) ?? "",
    command: str(o.command) ?? "unknown",
    params: obj(o.params) ?? {},
    requested: stage(nested(o, "requested")),
    acknowledged: stage(nested(o, "acknowledged")),
    applied: stage(nested(o, "applied")),
    observed: stage(nested(o, "observed")),
    requested_by: str(o.requested_by) ?? "operator",
    run_id: str(o.run_id) ?? "unknown",
  }
}

export function mapCommands(raw: unknown): CommandRecord[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "commands"))
  return list.map(mapCommandRecord)
}

export function mapCommandReceipt(raw: unknown): CommandReceipt {
  const o = obj(raw) ?? {}
  return {
    command_id: str(o.command_id) ?? "unknown",
    command: str(o.command) ?? "unknown",
    requested: stage(nested(o, "requested")),
    accepted: pickBool(o, "accepted") ?? false,
    detail: str(o.detail) ?? "",
  }
}

/* -------------------------------------------------------------------------- */
/* Faults                                                                     */
/* -------------------------------------------------------------------------- */

export function mapFaultRecord(raw: unknown): FaultRecord {
  const o = obj(raw) ?? {}
  return {
    fault_id: str(o.fault_id) ?? "unknown",
    state: (str(o.state) ?? "scheduled") as FaultRecord["state"],
    started_at_ns: num(o.started_at_ns) ?? 0,
    ended_at_ns: num(o.ended_at_ns),
    injected_by: str(o.injected_by) ?? undefined,
    manual: pickBool(o, "manual") ?? false,
    note: str(o.note) ?? undefined,
    digest: str(o.digest) ?? undefined,
  }
}

export function mapFaults(raw: unknown): FaultRecord[] {
  const list = Array.isArray(raw) ? raw : arr(nested(raw, "faults"))
  return list.map(mapFaultRecord)
}

/* -------------------------------------------------------------------------- */
/* Experiments                                                                */
/* -------------------------------------------------------------------------- */

export function mapExperimentMatrix(raw: unknown): ExperimentMatrix {
  const o = obj(raw) ?? {}
  return {
    batches: arr(nested(o, "batches")).map((b): ExperimentBatchSummary => {
      const bo = obj(b) ?? {}
      const raw_state = str(bo.state)
      const state: ExperimentBatchSummary["state"] =
        raw_state === "queued" || raw_state === "running" || raw_state === "completed" || raw_state === "failed"
          ? raw_state
          : "partial"
      return {
        batch_id: str(bo.batch_id) ?? "unknown",
        name: str(bo.name) ?? "Unnamed batch",
        created_utc: str(bo.created_utc),
        run_count: num(bo.run_count) ?? 0,
        state,
      }
    }),
    axes: arr(nested(o, "axes")).map((a) => {
      const ao = obj(a) ?? {}
      return { name: str(ao.name) ?? "axis", values: strList(ao.values) }
    }),
    total_runs: num(o.total_runs) ?? 0,
  }
}

export function mapExperimentCell(raw: unknown): ExperimentCell {
  const o = obj(raw) ?? {}
  const stateRaw = str(o.state)
  const allowed = new Set(["queued", "running", "completed", "unsafe", "failed", "timed_out", "cancelled"])
  return {
    run_id: str(o.run_id) ?? "unknown",
    scenario_id: str(o.scenario_id) ?? "unknown",
    scenario_revision: num(o.scenario_revision) ?? 0,
    seed: num(o.seed) ?? 0,
    coordination_policy: str(o.coordination_policy) ?? "unknown",
    state: (allowed.has(String(stateRaw)) ? stateRaw : "failed") as ExperimentCell["state"],
    outcome: str(o.outcome) ?? "failed",
    makespan_s: num(o.makespan_s),
    tasks_completed: num(o.tasks_completed) ?? 0,
    tasks_total: num(o.tasks_total) ?? 0,
    // `collisions` is a measured outcome. Absent means absent, not zero.
    collisions: num(o.collisions),
    evidence_complete: pickBool(o, "evidence_complete") ?? false,
  }
}

export function mapExperimentDetail(raw: unknown): ExperimentDetail {
  const o = obj(raw) ?? {}
  const runs = arr(nested(o, "runs")).map(mapExperimentCell)
  const elig = nestedObj(o, "eligibility") ?? {}
  const ineligible: { run_id: string; reason: string }[] = arr(elig.ineligible_runs).map((r) => {
    const ro = obj(r) ?? {}
    return { run_id: str(ro.run_id) ?? "unknown", reason: str(ro.reason) ?? "Ineligible for an undocumented reason." }
  })
  const paired: PairedRow[] = arr(nested(o, "paired")).map((p) => {
    const po = obj(p) ?? {}
    return {
      seed: num(po.seed) ?? 0,
      baseline_run_id: str(po.baseline_run_id) ?? "unknown",
      candidate_run_id: str(po.candidate_run_id) ?? "unknown",
      baseline_makespan_s: num(po.baseline_makespan_s),
      candidate_makespan_s: num(po.candidate_makespan_s),
      improvement_pct: num(po.improvement_pct),
      eligible: pickBool(po, "eligible") ?? false,
      ineligible_reason: str(po.ineligible_reason),
    }
  })
  return {
    batch_id: str(o.batch_id) ?? "unknown",
    name: str(o.name) ?? "Unnamed batch",
    config_diff: arr(nested(o, "config_diff")).map((d) => {
      const dd = obj(d) ?? {}
      return {
        field: str(dd.field) ?? "field",
        values: arr(dd.values).map((v) => {
          const vo = obj(v) ?? {}
          return { run_id: str(vo.run_id) ?? "unknown", value: str(vo.value) ?? "unavailable" }
        }),
        material: pickBool(dd, "material") ?? false,
      }
    }),
    runs,
    eligibility: {
      total_runs: num(elig.total_runs) ?? runs.length,
      eligible_pairs: num(elig.eligible_pairs) ?? paired.filter((p) => p.eligible).length,
      ineligible_runs: ineligible,
    },
    paired,
    report_available: pickBool(o, "report_available") ?? false,
  }
}

export function mapReportBundle(raw: unknown): ReportBundle {
  const o = obj(raw) ?? {}
  return {
    batch_id: str(o.batch_id) ?? "unknown",
    markdown: str(o.markdown) ?? "",
    csv: str(o.csv) ?? "",
    generated_utc: str(o.generated_utc),
  }
}

/* -------------------------------------------------------------------------- */
/* Replays / map                                                              */
/* -------------------------------------------------------------------------- */

export function mapReplayIndex(raw: unknown): ReplayIndex {
  const o = obj(raw) ?? {}
  return {
    run_id: str(o.run_id) ?? "unknown",
    events_path: str(o.events_path) ?? "",
    event_count: num(o.event_count) ?? 0,
    first_sim_time_s: num(o.first_sim_time_s) ?? 0,
    last_sim_time_s: num(o.last_sim_time_s) ?? 0,
    complete: pickBool(o, "complete") ?? false,
    categories: obj(nested(o, "categories")) as Record<string, number> | undefined,
    gaps: arr(nested(o, "gaps")) as never[],
    notes: str(o.notes) ?? undefined,
  }
}

export function mapReplayDetail(raw: unknown): ReplayDetail {
  const o = obj(raw) ?? {}
  return {
    index: mapReplayIndex(nested(o, "index") ?? o),
    manifest: (nested(o, "manifest") ?? null) as RunManifest | null,
    result: (nested(o, "result") ?? null) as RunResult | null,
  }
}

export function mapMapGeometry(raw: unknown): MapGeometry | null {
  const o = obj(raw)
  const map = obj(o?.map) ?? o
  if (map === null) return null
  const boundary = nestedObj(map, "boundary")
  const mapId = str(map.map_id)
  if (boundary === null || mapId === null) return null
  const mapObj = {
    ...map,
    map_id: mapId,
    boundary: {
      min_x: num(boundary.min_x) ?? 0,
      min_y: num(boundary.min_y) ?? 0,
      max_x: num(boundary.max_x) ?? 0,
      max_y: num(boundary.max_y) ?? 0,
    },
  } as MapGeometry["map"]
  return {
    map: mapObj,
    obstacles: nestedList(map, "obstacles") as never[],
    stations: nestedList(map, "stations") as never[],
    berths: nestedList(map, "berths") as never[],
    stop_lines: nestedList(map, "stop_lines") as never[],
    zones: nestedList(map, "zones") as never[],
  }
}

export function mapPolicy(raw: unknown): ApiPolicy {
  const o = obj(raw) ?? {}
  return o as ApiPolicy
}

/** Pick the first present array field; used for tolerant list envelopes. */
export { pickNum, pickStr, pickBool, pickNum as pickNumber }

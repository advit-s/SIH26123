/**
 * Local API adapter types for the NĪHĀRAMESH application API.
 *
 * ---------------------------------------------------------------------------
 * Why this file exists
 * ---------------------------------------------------------------------------
 * `packages/contracts/generated` holds the *authoritative domain* types
 * (Pose2, Zone, TelemetrySample, DomainEvent, FaultSpec, RunResult, ...).
 * Those are generated from the Python models and are never hand-edited.
 *
 * The API additionally serves **composite read models** — projections the
 * recorder builds for the cockpit (a RobotInspection is a join of identity,
 * session, pose estimate, motion state, task ownership, custody, battery and
 * the agent's own reasons). Those shapes are owned by the API surface, not by
 * the domain schema set, so they are declared here as explicit interfaces.
 *
 * Domain objects are *referenced*, never duplicated: `ZoneInspection.map_zone`
 * is the generated `Zone`, `RobotInspection.identity` is the generated
 * `RobotIdentity`. Mapping happens in `./mappers.ts`.
 */
import type {
  BatteryState,
  Berth,
  DomainEvent,
  FaultRecord,
  MotionState,
  Obstacle,
  PayloadCustody,
  Pose2,
  PoseEstimate,
  RecordingGap,
  ReplayIndex,
  RobotIdentity,
  RobotSession,
  RunManifest,
  RunResult,
  RunPolicy,
  Scenario,
  Station,
  StopLine,
  Task,
  TaskOwnership,
  WarehouseMap,
  Zone,
} from "@niharamesh/contracts/generated"

/** An error the API refused to serve, or a transport failure. Never coerced to zeros. */
export class ApiError extends Error {
  readonly code: string
  readonly status: number
  readonly requestId: string | null
  readonly details: Record<string, unknown> | null
  /** True when the request never reached the API (server down, DNS, refused). */
  readonly unreachable: boolean

  constructor(init: {
    code: string
    message: string
    status: number
    requestId?: string | null
    details?: Record<string, unknown> | null
    unreachable?: boolean
  }) {
    super(init.message)
    this.name = "ApiError"
    this.code = init.code
    this.status = init.status
    this.requestId = init.requestId ?? null
    this.details = init.details ?? null
    this.unreachable = init.unreachable ?? false
  }
}

/* -------------------------------------------------------------------------- */
/* Stream                                                                     */
/* -------------------------------------------------------------------------- */

export type StreamStatus = "idle" | "connecting" | "live" | "stale" | "paused" | "reconnecting" | "closed" | "error"

export type StreamEnvelope =
  | {
      kind: "snapshot"
      run_id: string
      cursor: number
      payload: RunStateSnapshot & { robots: RobotInspection[]; zones: ZoneInspection[] }
    }
  | { kind: "telemetry"; run_id: string; cursor: number; samples: TelemetrySampleView[] }
  | { kind: "event"; run_id: string; cursor: number; events: DomainEvent[] }
  | { kind: "gap"; run_id: string; cursor: number; gap: RecordingGap }
  | { kind: "status"; run_id: string; cursor: number; status: "live" | "stale" | "paused" | "reconnecting" | "closed"; since?: string }

/* -------------------------------------------------------------------------- */
/* Health                                                                     */
/* -------------------------------------------------------------------------- */

export type ApiMode = "deterministic" | "processes" | "replay"

export interface HealthStatus {
  status: "ok" | "degraded"
  version: string
  schema_version: string
  protocol_version: string
  mode: ApiMode | string
  run_id: string | null
  recording_healthy: boolean
  uptime_s: number
}

/* -------------------------------------------------------------------------- */
/* Doctor                                                                     */
/* -------------------------------------------------------------------------- */

export type CheckStatus = "pass" | "warn" | "fail" | "unknown"

export interface DoctorCheck {
  id: string
  label: string
  status: CheckStatus
  detail: string
  /** Measured values are only present when actually collected. */
  measured?: Record<string, string | number | boolean | null> | null
}

export interface DoctorProcess {
  name: string
  role: string
  status: "running" | "stopped" | "unknown"
  pid: number | null
  host: string | null
}

export interface DoctorEndpoint {
  name: string
  url: string
  status: CheckStatus
  latency_ms: number | null
}

export interface DoctorJournal {
  name: string
  path: string | null
  status: CheckStatus
  detail: string
}

export interface DoctorReport {
  generated_at_utc: string
  build: {
    version: string
    schema_version: string
    protocol_version: string
    source_revision: string | null
    config_digest: string | null
  }
  schema_compatibility: {
    expected: string
    actual: string | null
    status: CheckStatus
    detail: string
  }
  recording: {
    healthy: boolean
    gaps: RecordingGap[]
    detail: string
  }
  processes: DoctorProcess[]
  endpoints: DoctorEndpoint[]
  journals: DoctorJournal[]
  checks: DoctorCheck[]
}

/* -------------------------------------------------------------------------- */
/* Scenarios                                                                  */
/* -------------------------------------------------------------------------- */

export type ValidationSeverity = "error" | "warning" | "info"

/**
 * `error` = structural invalidity: the JSON cannot be executed at all and
 * launch is blocked.
 * `warning` may include an intentionally infeasible workload, which is a legal
 * experiment only when explicitly labelled expected-failure.
 */
export interface ValidationProblem {
  code: string
  severity: ValidationSeverity
  path: string
  message: string
  hint?: string
}

export interface ValidationReport {
  /**
   * `false` means "nobody has checked this document yet". It is deliberately
   * distinct from "validated and blocked": an unvalidated draft must never read
   * as a verdict, because a verdict implies a check that did not happen.
   */
  validated: boolean
  valid: boolean
  launchable: boolean
  scenario_digest: string | null
  problems: ValidationProblem[]
  counts: { error: number; warning: number; info: number }
  /** True when the authored intent is an expected-failure experiment. */
  expected_failure: boolean
  expected_failure_reason: string | null
}

export interface ScenarioSummary {
  scenario_id: string
  name: string
  revision: number
  kind: string
  description: string | null
  robot_count: number
  task_count: number
  zone_count: number
  updated_utc: string | null
  map_id: string | null
  map_revision: number | null
}

export interface ScenarioDetail {
  scenario_id: string
  revision: number
  scenario: Scenario
  validation: ValidationReport
}

/* -------------------------------------------------------------------------- */
/* Runs                                                                       */
/* -------------------------------------------------------------------------- */

export interface RunDetail {
  run_id: string
  manifest: RunManifest
  state: string
  result: RunResult | null
  recording_healthy: boolean
  scenario: Scenario | null
  snapshot_id: string | null
}

/**
 * The context-bar payload. Everything here is a *declared* state of the run
 * harness, never an inferred one.
 */
export interface RunStateSnapshot {
  run_id: string
  mode: ApiMode | string
  state: string
  outcome: string
  sim_time_s: number
  wall_time_utc: string | null
  speed_multiplier: number | null
  paused: boolean
  tick: number | null
  max_sim_time_s: number | null
  robot_count: number
  coordination_policy: string
  assignment_policy: string | null
  routing_policy: string | null
  scenario_id: string | null
  scenario_revision: number | null
  scenario_digest: string | null
  map_id: string | null
  map_revision: number | null
  map_digest: string | null
  recording_healthy: boolean
  recording_gaps: RecordingGap[]
  /** Highest `seq` the API has produced. Used to detect event-stream holes. */
  last_seq: number
}

export type MetricSource = "measured" | "simulated" | "estimated" | "unavailable"

/** Provenance of a battery reading. Mirrors the domain `BatteryState.source`. */
export type BatterySource = "measured" | "simulated" | "estimated" | "unavailable"

/** One page of the durable event log. */
export interface EventPage {
  events: DomainEvent[]
  next_seq: number
  has_more: boolean
}

/** A number that may legitimately be absent. `null` renders as "unavailable". */
export interface Sourced {
  value: number | null
  source: MetricSource
  /** Age of the underlying evidence, in seconds, when known. */
  age_s: number | null
  note?: string
}

export interface WhyWaiting {
  blocked: boolean
  /** Plain-language sentence naming the blocking resource. */
  reason: string
  blocking_request_id: string | null
  blocking_peer: string | null
  blocking_resource: string | null
  blocking_zone_id: string | null
  evidence_age_s: number | null
  /** What must happen for the block to clear. */
  recovery_condition: string | null
  /** Timer names are permission to assume, never physical occupancy. */
  timer_expires_permission_only: boolean
}

export interface RobotInspection {
  robot_id: string
  index: number
  identity: RobotIdentity
  session: RobotSession | null
  /** The agent's own declared observation, with its uncertainty and age. */
  pose_estimate: PoseEstimate | null
  motion: MotionState | null
  battery: BatteryState | null
  task: Task | null
  ownership: TaskOwnership | null
  custody: PayloadCustody | null
  carrying_payload: boolean
  /** Zones the agent believes it holds authority over. */
  held_zones: ZoneHoldView[]
  /** Zones the agent believes are occupied by somebody. */
  observed_zones: ZoneOccupancyView[]
  last_accepted_intent: string | null
  planner_state: string | null
  plan_version: number | null
  map_epoch: string | null
  degraded: boolean
  degraded_reason: string | null
  why_waiting: WhyWaiting | null
  reasons: AgentReason[]
  stale: boolean
  pose_age_s: number | null
  /** Latest durable events about this robot, oldest first. */
  recent_events: DomainEvent[]
}

export interface AgentReason {
  at_seq: number
  sim_time_s: number | null
  category: string
  text: string
  severity: string
}

export interface ZoneHoldView {
  zone_id: string
  robot_id: string
  state: string
  since_seq: number | null
  acquired_at_sim_s: number | null
}

export interface ZoneOccupancyView {
  zone_id: string
  occupant: string | null
  state: string
  source: "agent_report" | "evaluator"
  confidence: number | null
  age_s: number | null
}

export interface ZoneRequestView {
  request_id: string
  requester: string
  state: string
  required_peers: string[]
  responses_received: ZoneResponseView[]
  responses_required: number
  responses_received_count: number
  outstanding: string[]
  granted_at_seq: number | null
  cancelled: boolean
  note: string | null
}

export interface ZoneResponseView {
  peer: string
  response: "grant" | "refuse" | "no_response"
  reason: string | null
  age_s: number | null
  at_seq: number | null
}

export interface ZoneInspection {
  zone_id: string
  map_zone: Zone | null
  authority: "held" | "granted_pending_entry" | "free" | "contested" | "occupied" | "unknown"
  authority_holder: string | null
  /** Conservative occupancy: a lost heartbeat does NOT empty the zone. */
  physical_occupancy: "occupied" | "believed_free" | "unknown"
  occupant: string | null
  /** When the *evaluator* believes the zone is occupied. Steel-blue only. */
  evaluator_occupancy: boolean | null
  entries: number
  requests: ZoneRequestView[]
  entry_withheld: boolean
  entry_withheld_reason: string | null
  required_peers: string[]
  stop_line_in: string | null
  stop_line_out: string | null
  queue_berth_id: string | null
  exit_berth_id: string | null
  protected_origin: [number, number] | null
  protected_extent: [number, number] | null
  entry_pose: Pose2 | null
  exit_pose: Pose2 | null
}

export interface BidComponentView {
  name: string
  value: number
  unit: string
}

export interface TaskInspection {
  task_id: string
  task: Task | null
  owner: string | null
  ownership_version: number
  ownership_state: string
  custody: PayloadCustody | null
  bids: BidComponentSet[]
  feasible_bids: number
  infeasible_bids: number
  awarded: boolean
  winner: string | null
  completed: boolean
  completion_evidence: DomainEvent | null
  blocked_reason: string | null
}

export interface BidComponentSet {
  robot_id: string
  total_cost: number
  feasible: boolean
  infeasible_reason: string | null
  components: BidComponentView[]
  tie_break: number | null
  round_id: string | null
}

export type FreshnessClass = "fresh" | "aging" | "stale" | "unknown" | "never"

export interface CommunicationCell {
  from: string
  to: string
  /** Direction matters: "A hears B" is not "B hears A". */
  heard: boolean
  last_rx_age_s: number | null
  dropped: number
  freshness: FreshnessClass
  note: string | null
}

export interface TelemetryPage {
  samples: TelemetrySampleView[]
  next_index: number
}

export interface TelemetrySampleView {
  run_id: string
  robot_id: string
  sample_index: number
  sim_time_s: number
  x: number
  y: number
  theta: number
  linear_mps: number
  angular_radps: number
  battery_fraction: number | null
  stop_reason: string | null
}

/* -------------------------------------------------------------------------- */
/* Commands                                                                   */
/* -------------------------------------------------------------------------- */

export type CommandName =
  | "pause"
  | "resume"
  | "step"
  | "request_stop"
  | "clear_stop"
  | "set_speed"
  | "reassign_task"
  | "export"

export interface CommandStageState {
  state: "unknown" | "requested" | "acknowledged" | "applied" | "observed" | "refused" | "failed"
  at_utc: string | null
  detail: string | null
}

export interface CommandRecord {
  command_id: string
  idempotency_key: string
  command: string
  params: Record<string, unknown>
  /** A sent command is NOT an observed stop. These four are distinct. */
  requested: CommandStageState
  acknowledged: CommandStageState
  applied: CommandStageState
  observed: CommandStageState
  requested_by: string
  run_id: string
}

export interface CommandReceipt {
  command_id: string
  command: string
  requested: CommandStageState
  accepted: boolean
  detail: string
}

/* -------------------------------------------------------------------------- */
/* Experiments                                                                */
/* -------------------------------------------------------------------------- */

export type ExperimentCellState =
  | "queued"
  | "running"
  | "completed"
  | "unsafe"
  | "failed"
  | "timed_out"
  | "cancelled"

export interface ExperimentCell {
  run_id: string
  scenario_id: string
  scenario_revision: number
  seed: number
  coordination_policy: string
  state: ExperimentCellState
  outcome: string
  makespan_s: number | null
  tasks_completed: number
  tasks_total: number
  collisions: number | null
  evidence_complete: boolean
}

export interface ExperimentMatrix {
  batches: ExperimentBatchSummary[]
  axes: { name: string; values: string[] }[]
  total_runs: number
}

export interface ExperimentBatchSummary {
  batch_id: string
  name: string
  created_utc: string | null
  run_count: number
  state: "queued" | "running" | "completed" | "partial" | "failed"
}

export interface ExperimentDetail {
  batch_id: string
  name: string
  config_diff: ConfigDifference[]
  runs: ExperimentCell[]
  eligibility: EligibilitySummary
  paired: PairedRow[]
  report_available: boolean
}

export interface ConfigDifference {
  field: string
  values: { run_id: string; value: string }[]
  /** True when this difference could change the measured outcome. */
  material: boolean
}

export interface EligibilitySummary {
  total_runs: number
  eligible_pairs: number
  ineligible_runs: { run_id: string; reason: string }[]
}

export interface PairedRow {
  seed: number
  baseline_run_id: string
  candidate_run_id: string
  baseline_makespan_s: number | null
  candidate_makespan_s: number | null
  improvement_pct: number | null
  eligible: boolean
  ineligible_reason: string | null
}

export interface ReportBundle {
  batch_id: string
  markdown: string
  csv: string
  generated_utc: string | null
}

/* -------------------------------------------------------------------------- */
/* Replays                                                                    */
/* -------------------------------------------------------------------------- */

export interface ReplayDetail {
  index: ReplayIndex
  manifest: RunManifest | null
  result: RunResult | null
}

/* -------------------------------------------------------------------------- */
/* Static map / geometry that the map layer needs                            */
/* -------------------------------------------------------------------------- */

export interface MapGeometry {
  map: WarehouseMap
  obstacles: Obstacle[]
  stations: Station[]
  berths: Berth[]
  stop_lines: StopLine[]
  zones: Zone[]
}

export interface ApiPolicy extends RunPolicy {}

/* The generated domain types the UI passes through unchanged are referenced,
 * not re-declared. `MotionState` is re-exported for mapper ergonomics. */
export type { FaultRecord, MotionState, PayloadCustody, RecordingGap, TaskOwnership }

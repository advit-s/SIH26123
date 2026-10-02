// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RunManifest.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type AssignmentPolicy = string;
export type ComparisonMode = string;
export type ConfigDigest = string;
export type CoordinationPolicy = string;
export type CreatedUtcNs = number;
export type Accelerator = string;
export type CpuCount = number;
export type CpuModel = string;
export type Docker = boolean;
export type Machine = string;
export type OsName = string;
export type OsVersion = string;
export type PythonVersion = string;
export type WallEndUtcNs = number;
export type WallStartUtcNs = number;
export type ExpectedFailureReason = string;
export type ExpectedFailureScenario = boolean;
export type FaultIds = string[];
export type MapDigest = string;
export type MaxSimTimeS = number;
export type Mode = "deterministic" | "processes";
export type Notes = string;
export type RobotIds = string[];
export type RoutingPolicy = string;
export type RunId = string;
export type ScenarioDigest = string;
export type ScenarioRevision = number;
export type SchemaVersion = string;
export type SchemaVersionId = string;
export type Seed = number;
export type SourceDirty = boolean;
export type SourceRevision = string;
export type TaskCount = number;

/**
 * Everything needed to reproduce and audit one run.
 */
export interface RunManifest {
  assignment_policy: AssignmentPolicy;
  comparison_mode: ComparisonMode;
  config_digest: ConfigDigest;
  coordination_policy: CoordinationPolicy;
  created_utc_ns: CreatedUtcNs;
  environment?: EnvironmentRecord;
  expected_failure_reason?: ExpectedFailureReason;
  expected_failure_scenario?: ExpectedFailureScenario;
  fault_ids?: FaultIds;
  feature_flags?: FeatureFlags;
  map_digest: MapDigest;
  max_sim_time_s?: MaxSimTimeS;
  mode: Mode;
  notes?: Notes;
  robot_ids?: RobotIds;
  routing_policy: RoutingPolicy;
  run_id: RunId;
  scenario_digest: ScenarioDigest;
  scenario_revision: ScenarioRevision;
  schema_version?: SchemaVersion;
  schema_version_id?: SchemaVersionId;
  seed: Seed;
  source_dirty?: SourceDirty;
  source_revision: SourceRevision;
  task_count: TaskCount;
}
/**
 * What the run actually executed on. Recorded, never guessed.
 */
export interface EnvironmentRecord {
  accelerator?: Accelerator;
  cpu_count?: CpuCount;
  cpu_model?: CpuModel;
  docker?: Docker;
  machine: Machine;
  os_name: OsName;
  os_version: OsVersion;
  python_version: PythonVersion;
  wall_end_utc_ns?: WallEndUtcNs;
  wall_start_utc_ns?: WallStartUtcNs;
}
export interface FeatureFlags {
  [k: string]: boolean;
}

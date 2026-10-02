// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ScenarioSnapshot.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type ConfigDigest = string;
export type CreatedUtcNs = number;
export type FaultDigest = string;
export type MapDigest = string;
export type Description = string;
export type DurationS = number;
export type ExpectedInvariant = string;
export type FaultId = string;
export type FaultParam = number | boolean | string;
export type SchemaVersion = string;
export type Seed = number;
export type StartAtS = number;
export type FaultChannel = "coordination" | "telemetry";
export type FaultKind =
  | "delay"
  | "loss"
  | "duplicate"
  | "reorder"
  | "partition"
  | "clock_skew"
  | "obstacle_insert"
  | "obstacle_remove"
  | "sensor_stale"
  | "sensor_dropout"
  | "control_overload"
  | "process_crash"
  | "process_restart"
  | "journal_corrupt";
export type MessageKind = string | null;
export type Position = [unknown, unknown] | null;
export type Receiver = string | null;
export type Robot = string | null;
export type Sender = string | null;
export type ZoneId = string | null;
export type Faults = FaultSpec[];
export type Expect = string;
export type ExpectedFailureReason = string;
export type Goal = string;
export type Kind = "nominal" | "fault" | "diagnostic" | "benchmark";
export type Capacity = number;
export type Id = string;
export type Theta = number;
export type X = number;
export type Y = number;
export type Berths = Berth[];
export type MaxX = number;
export type MaxY = number;
export type MinX = number;
export type MinY = number;
export type CostM = number;
export type Id1 = string;
export type OneWay = boolean;
export type DirectedRoutes = RouteEdge[];
export type GridResolutionM = number;
export type MapId = string;
export type Name = string;
export type NominalAisleWidthM = number;
export type Dynamic = boolean;
export type Id2 = string;
export type ObstacleKind = "shelf" | "wall" | "pillar" | "temporary";
export type LengthM = number;
export type WidthM = number;
export type Obstacles = Obstacle[];
export type Revision = number;
export type SchemaVersion1 = string;
export type Capacity1 = number;
export type Id3 = string;
export type StationKind = "pickup" | "drop" | "charge";
export type ServiceTimeS = number;
export type Stations = Station[];
export type Approach = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type End = [unknown, unknown];
export type Id4 = string;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Start = [unknown, unknown];
export type ZoneId1 = string;
export type StopLines = StopLine[];
/**
 * The protected movement a zone authorises.
 *
 * ``FWD``  - traverse along the zone's declared axis, either direction.
 * ``REV``  - traverse against the declared axis (used for one-way aisles).
 * ``CROSS``- cross the zone (intersections / junctions).
 */
export type ZoneMovement = "forward" | "reverse" | "cross";
export type AllowedMovement = ZoneMovement[];
export type Description1 = string;
export type ExitBerthId = string | null;
export type Id5 = string;
export type Kind1 = string;
export type Members = string[];
export type OneWayHeadingRad = number | null;
/**
 * @minItems 2
 * @maxItems 2
 */
export type ProtectedExtent = [unknown, unknown];
/**
 * @minItems 2
 * @maxItems 2
 */
export type ProtectedOrigin = [unknown, unknown];
export type QueueBerthId = string | null;
export type StopLineIn = string | null;
export type StopLineOut = string | null;
export type Zones = Zone[];
export type MaxSimTimeS = number;
export type Name1 = string;
export type AssignmentPolicy = "none" | "local_auction";
export type ComparisonMode = "coordination_only" | "end_to_end";
/**
 * The two policies that must sit behind identical interfaces.
 */
export type CoordinationPolicy = "stop_and_wait" | "canonical_sequential";
export type FaultSeed = number;
export type PlannerSeed = number;
export type RoutingPolicy = "shortest" | "blocked_aware" | "temporal_sipp_approx";
export type SensorSeed = number;
export type Revision1 = number;
export type Capability = "carry_payload" | "tow" | "spot_fill" | "dock" | "clean";
export type Capabilities = Capability[];
export type LengthM1 = number;
export type PayloadLengthM = number;
export type PayloadOffsetM = number;
export type PayloadWidthM = number;
export type TurningRadiusM = number;
export type WidthM1 = number;
export type MaxAngularRadps = number;
export type MaxLinearMps = number;
export type Model = string;
export type RobotId = string;
export type SchemaVersion2 = string;
export type Robots = RobotIdentity[];
export type ScenarioId = string;
export type SchemaVersion3 = string;
export type Seed1 = number;
export type AccelMps2 = number;
export type AngularAccelRadps2 = number;
export type CommandTtlS = number;
export type DecelMps2 = number;
export type MaxAngularRadps1 = number;
export type MaxLinearMps1 = number;
export type DrainPerMetreC = number;
export type DrainPerSecondIdleC = number;
export type ServiceDrainC = number;
export type Source = string;
export type StartFraction = number;
export type BlockedAwareRouting = boolean;
export type DisableSafetyGate = boolean;
export type FairnessAwarePriority = boolean;
export type TaskReassignment = boolean;
export type TemporalPlanning = boolean;
export type TimerExpiryOccupancy = boolean;
export type UnsafeFlags = string[];
export type UnsafeResearchVariant = boolean;
export type PhysicalActuationEnabled = boolean;
export type PhysicsStepHz = number;
export type CancelTimeoutS = number;
export type ControlPeriodS = number;
export type FreshnessHorizonS = number;
export type HeartbeatPeriodS = number;
export type IntentPublishPeriodS = number;
export type IntentValidityS = number;
export type QueueTiebreakS = number;
export type ReleaseTimeoutS = number;
export type SolicitTimeoutS = number;
export type StatePublishPeriodS = number;
export type SchemaVersion4 = string;
export type AngularResolutionRad = number;
export type DropoutProbability = number;
export type FieldOfViewRad = number;
export type HeadingSigmaRad = number;
export type ObservationLatencyS = number;
export type PositionSigmaM = number;
export type RangeM = number;
export type RangeNoiseM = number;
export type SimulatedActuationEnabled = boolean;
export type StatePublishHz = number;
export type BrakingDecelMps2 = number;
export type ExtraMarginM = number;
export type MaxSpeedMps = number;
export type ReactionTimeS = number;
export type AssignedTaskId = string | null;
export type HoldingTaskId = string | null;
export type RobotId1 = string;
export type Starts = RobotStart[];
export type DropStationId = string;
export type PickupStationId = string;
export type Priority = number;
export type ReleaseAtS = number;
export type RequiredCapabilities = string[];
export type SchemaVersion5 = string;
export type ServiceTimeS1 = number;
export type TaskId = string;
export type WeightKg = number;
export type Tasks = Task[];
export type ScenarioDigest = string;
export type SnapshotId = string;
export type TaskDigest = string;

/**
 * A frozen copy handed to a launched run.
 *
 * Contains the full scenario plus the digests that must be quoted by every
 * result derived from it. Never mutated after creation.
 */
export interface ScenarioSnapshot {
  config_digest: ConfigDigest;
  created_utc_ns: CreatedUtcNs;
  fault_digest: FaultDigest;
  map_digest: MapDigest;
  scenario: Scenario;
  scenario_digest: ScenarioDigest;
  snapshot_id: SnapshotId;
  task_digest: TaskDigest;
}
/**
 * The authored experiment. Validated separately (structure vs feasibility).
 */
export interface Scenario {
  description?: Description;
  faults?: Faults;
  intent: IntentDescription;
  kind?: Kind;
  map: WarehouseMap;
  max_sim_time_s?: MaxSimTimeS;
  name: Name1;
  policy?: RunPolicy;
  revision?: Revision1;
  robots: Robots;
  scenario_id: ScenarioId;
  schema_version?: SchemaVersion3;
  seed?: Seed1;
  simulation?: SimulationConfig;
  starts: Starts;
  tasks?: Tasks;
}
export interface FaultSpec {
  duration_s?: DurationS;
  expected_invariant: ExpectedInvariant;
  fault_id: FaultId;
  params?: Params;
  schema_version?: SchemaVersion;
  seed?: Seed;
  start_at_s?: StartAtS;
  target: FaultTarget;
}
export interface Params {
  [k: string]: FaultParam;
}
/**
 * Explicit sender/receiver targeting. A fault with no target is invalid -
 * the brief requires directed fault injection, not a global toggle.
 */
export interface FaultTarget {
  channel: FaultChannel;
  kind: FaultKind;
  message_kind?: MessageKind;
  position?: Position;
  receiver?: Receiver;
  robot?: Robot;
  sender?: Sender;
  zone_id?: ZoneId;
}
/**
 * Human-readable description of the experiment, shown in the UI.
 */
export interface IntentDescription {
  expect?: Expect;
  expected_failure_reason?: ExpectedFailureReason;
  goal: Goal;
}
/**
 * Immutable shared map. Every agent receives exactly this object.
 */
export interface WarehouseMap {
  berths?: Berths;
  boundary: MapBoundary;
  directed_routes?: DirectedRoutes;
  grid_resolution_m?: GridResolutionM;
  map_id: MapId;
  name?: Name;
  nominal_aisle_width_m?: NominalAisleWidthM;
  obstacles?: Obstacles;
  revision?: Revision;
  schema_version?: SchemaVersion1;
  stations?: Stations;
  stop_lines?: StopLines;
  zones?: Zones;
}
/**
 * A safe resting place: a place where a stopped robot is *not* holding
 * another robot's zone authority.
 */
export interface Berth {
  capacity?: Capacity;
  id: Id;
  pose: Pose2;
}
/**
 * Planar pose in metres/radians. Distinct from a *measured* pose estimate.
 */
export interface Pose2 {
  theta: Theta;
  x: X;
  y: Y;
}
/**
 * Axis-aligned usable envelope of the warehouse, in metres.
 */
export interface MapBoundary {
  max_x: MaxX;
  max_y: MaxY;
  min_x: MinX;
  min_y: MinY;
}
/**
 * Directed travel edge for the optional directed-route graph.
 *
 * When a map declares ``directed_routes``, the planner must respect
 * ``one_way`` on each edge. This is a topological *hint*, not authority.
 */
export interface RouteEdge {
  cost_m: CostM;
  from_pose: Pose2;
  id: Id1;
  one_way?: OneWay;
  to_pose: Pose2;
}
export interface Obstacle {
  dynamic?: Dynamic;
  id: Id2;
  kind?: ObstacleKind;
  length_m: LengthM;
  pose: Pose2;
  width_m: WidthM;
}
export interface Station {
  capacity?: Capacity1;
  id: Id3;
  kind: StationKind;
  pose: Pose2;
  service_time_s?: ServiceTimeS;
}
/**
 * Physical line a robot must not cross without the named authority.
 *
 * ``zone_id`` names the authority required. This is the geometric anchor for
 * "stop-line violation", which the evaluator checks independently.
 */
export interface StopLine {
  approach?: Approach;
  end: End;
  id: Id4;
  start: Start;
  zone_id: ZoneId1;
}
/**
 * An exclusive resource with disjoint protected geometry.
 *
 * Every exclusive zone's protected geometry must be **disjoint** from every
 * other exclusive zone's. Where a traversal needs two adjacent resources with
 * no safe berth between them, they must be authored as ONE compound zone
 * (see ``members``), not as two zones a robot might partially hold.
 */
export interface Zone {
  allowed_movement?: AllowedMovement;
  description?: Description1;
  entry_pose: Pose2;
  exit_berth_id?: ExitBerthId;
  exit_pose: Pose2;
  id: Id5;
  kind?: Kind1;
  members?: Members;
  one_way_heading_rad?: OneWayHeadingRad;
  protected_extent: ProtectedExtent;
  protected_origin: ProtectedOrigin;
  queue_berth_id?: QueueBerthId;
  stop_line_in?: StopLineIn;
  stop_line_out?: StopLineOut;
}
export interface RunPolicy {
  assignment?: AssignmentPolicy;
  comparison_mode?: ComparisonMode;
  coordination?: CoordinationPolicy;
  fault_seed?: FaultSeed;
  planner_seed?: PlannerSeed;
  routing?: RoutingPolicy;
  sensor_seed?: SensorSeed;
}
/**
 * Persistent identity of a physical robot.
 */
export interface RobotIdentity {
  capabilities?: Capabilities;
  footprint: Footprint;
  max_angular_radps?: MaxAngularRadps;
  max_linear_mps?: MaxLinearMps;
  model?: Model;
  robot_id: RobotId;
  schema_version?: SchemaVersion2;
}
/**
 * Finite robot geometry, plus payload overhang when carrying.
 *
 * ``length_m``/``width_m`` describe the chassis. ``payload_length_m`` and
 * ``payload_width_m`` describe the largest carried load. ``payload_offset_m``
 * is the distance from the chassis centre to the payload centre along the
 * chassis ``+x`` axis (positive = front overhang).
 */
export interface Footprint {
  length_m: LengthM1;
  payload_length_m?: PayloadLengthM;
  payload_offset_m?: PayloadOffsetM;
  payload_width_m?: PayloadWidthM;
  turning_radius_m?: TurningRadiusM;
  width_m: WidthM1;
}
export interface SimulationConfig {
  actuator?: ActuatorModel;
  battery?: BatteryModel;
  features?: FeatureFlags;
  physical_actuation_enabled?: PhysicalActuationEnabled;
  physics_step_hz?: PhysicsStepHz;
  protocol?: ProtocolTiming;
  schema_version?: SchemaVersion4;
  sensor?: SensorModel;
  simulated_actuation_enabled?: SimulatedActuationEnabled;
  state_publish_hz?: StatePublishHz;
  stopping?: StoppingBudget;
}
export interface ActuatorModel {
  accel_mps2?: AccelMps2;
  angular_accel_radps2?: AngularAccelRadps2;
  command_ttl_s?: CommandTtlS;
  decel_mps2?: DecelMps2;
  max_angular_radps?: MaxAngularRadps1;
  max_linear_mps?: MaxLinearMps1;
}
/**
 * Declared battery model. UI must state ``source`` alongside any value.
 */
export interface BatteryModel {
  drain_per_metre_c?: DrainPerMetreC;
  drain_per_second_idle_c?: DrainPerSecondIdleC;
  service_drain_c?: ServiceDrainC;
  source?: Source;
  start_fraction?: StartFraction;
}
/**
 * Ablation switches. Unsafe research variants are namespaced so they can
 * never be enabled by accident in a physical deployment.
 */
export interface FeatureFlags {
  blocked_aware_routing?: BlockedAwareRouting;
  disable_safety_gate?: DisableSafetyGate;
  fairness_aware_priority?: FairnessAwarePriority;
  task_reassignment?: TaskReassignment;
  temporal_planning?: TemporalPlanning;
  timer_expiry_occupancy?: TimerExpiryOccupancy;
  unsafe_flags?: UnsafeFlags;
  unsafe_research_variant?: UnsafeResearchVariant;
}
/**
 * All protocol deadlines live in the agent's declared time domain.
 */
export interface ProtocolTiming {
  cancel_timeout_s?: CancelTimeoutS;
  control_period_s?: ControlPeriodS;
  freshness_horizon_s?: FreshnessHorizonS;
  heartbeat_period_s?: HeartbeatPeriodS;
  intent_publish_period_s?: IntentPublishPeriodS;
  intent_validity_s?: IntentValidityS;
  queue_tiebreak_s?: QueueTiebreakS;
  release_timeout_s?: ReleaseTimeoutS;
  solicit_timeout_s?: SolicitTimeoutS;
  state_publish_period_s?: StatePublishPeriodS;
}
/**
 * Declared sensing limits and noise. Every value is a simulation
 * configuration, labelled as such wherever it is displayed.
 */
export interface SensorModel {
  angular_resolution_rad?: AngularResolutionRad;
  dropout_probability?: DropoutProbability;
  field_of_view_rad?: FieldOfViewRad;
  heading_sigma_rad?: HeadingSigmaRad;
  observation_latency_s?: ObservationLatencyS;
  position_sigma_m?: PositionSigmaM;
  range_m?: RangeM;
  range_noise_m?: RangeNoiseM;
}
/**
 * Derived stopping distance parameters.
 *
 * These are *configured assumptions* for a low-speed simulation. They are not
 * certified real-world limits and are never presented as a safety guarantee.
 *
 * Example from the brief at v=0.4 m/s, t_r=0.30 s, a=0.8 m/s^2, margin=0.10 m:
 * reaction 0.12 m + braking 0.10 m + margin 0.10 m = 0.32 m.
 */
export interface StoppingBudget {
  braking_decel_mps2?: BrakingDecelMps2;
  extra_margin_m?: ExtraMarginM;
  max_speed_mps?: MaxSpeedMps;
  reaction_time_s?: ReactionTimeS;
}
export interface RobotStart {
  assigned_task_id?: AssignedTaskId;
  holding_task_id?: HoldingTaskId;
  pose: Pose2;
  robot_id: RobotId1;
}
/**
 * A transport job. Generated independently of assignment.
 */
export interface Task {
  drop_station_id: DropStationId;
  pickup_station_id: PickupStationId;
  priority?: Priority;
  release_at_s?: ReleaseAtS;
  required_capabilities?: RequiredCapabilities;
  schema_version?: SchemaVersion5;
  service_time_s?: ServiceTimeS1;
  task_id: TaskId;
  weight_kg?: WeightKg;
}

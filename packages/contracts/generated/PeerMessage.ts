// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PeerMessage.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Body =
  | ZoneRequestBody
  | ZoneGrantBody
  | ZoneCancelBody
  | ZoneCancelAckBody
  | ZoneOccupyBody
  | ZoneReleaseBody
  | ZoneFenceBody
  | PeerState
  | PeerIntent
  | ObstructionReport
  | Heartbeat;
/**
 * @minItems 3
 * @maxItems 3
 */
export type EntryPose = [unknown, unknown, unknown];
export type Epoch = string;
/**
 * @minItems 3
 * @maxItems 3
 */
export type ExitPose = [unknown, unknown, unknown];
export type ExpiresAtNs = number;
export type MembershipDigest = string;
export type Movement = string;
export type ProtocolVersion = string;
export type RequestVersion = number;
export type Requester = string;
export type RequesterSession = string;
export type RunId = string;
export type SchemaVersion = string;
/**
 * Named clock domains. Values are never mixed across domains.
 *
 * ``LOGICAL``
 *     Injected logical simulation time. Freezes when the harness pauses and
 *     advances under acceleration. Used by the deterministic mode.
 * ``SIM_SECONDS``
 *     Simulation seconds elapsed since the declared common run start. Derived
 *     from ``LOGICAL``; identical semantics, different unit framing.
 * ``MONOTONIC``
 *     The agent's own ``time.monotonic_ns()``. Never comparable across
 *     processes without an explicit measured offset *and* uncertainty.
 * ``DISPLAY_UTC``
 *     Wall-clock UTC for human display only. Never used for expiry.
 */
export type TimeDomain = "logical" | "sim_seconds" | "monotonic" | "display_utc";
export type ZoneId = string;
export type Epoch1 = string;
export type GrantId = string;
export type IsSelfVoter = boolean;
export type PersistenceRecordId = string;
export type ProtocolVersion1 = string;
export type RequestVersion1 = number;
export type Requester1 = string;
export type RequesterSession1 = string;
export type RequiredSetDigest = string;
export type RunId1 = string;
export type SchemaVersion1 = string;
export type ZoneId1 = string;
export type CancelSeq = number;
export type DurablyNonExecutable = boolean;
export type Epoch2 = string;
export type GrantId1 = string;
export type ProtocolVersion2 = string;
export type Reason = string;
export type RequestVersion2 = number;
export type Requester2 = string;
export type RequesterSession2 = string;
export type RunId2 = string;
export type SchemaVersion2 = string;
export type ZoneId2 = string;
export type CancelSeq1 = number;
export type NoRecord = boolean;
export type RequestVersion3 = number;
export type Requester3 = string;
export type RequesterSession3 = string;
export type Voter = string;
export type VoterSession = string;
export type ZoneId3 = string;
export type Epoch3 = string;
export type GrantId2 = string;
export type OccupancySeq = number;
export type RequestVersion4 = number;
export type Requester4 = string;
export type RequesterSession4 = string;
export type RunId3 = string;
export type ZoneId4 = string;
export type AssertsFullClearance = boolean;
export type Epoch4 = string;
export type GrantId3 = string;
export type OccupancySeq1 = number;
export type ProtocolVersion3 = string;
export type ReleaseSeq = number;
export type RequestVersion5 = number;
export type Requester5 = string;
export type RequesterSession5 = string;
export type RunId4 = string;
export type SchemaVersion3 = string;
export type ZoneId5 = string;
export type Epoch5 = string;
export type FencedBy = string;
export type OperatorAuthorised = boolean;
export type PreviousHolder = string | null;
export type PreviousRequesterSession = string | null;
export type Reason1 = string;
export type RunId5 = string;
export type SchemaVersion4 = string;
export type ZoneId6 = string;
export type BatteryFraction = number | null;
export type BatterySource = string;
export type CarryingTaskId = string | null;
/**
 * @minItems 3
 * @maxItems 3
 */
export type Pose = [unknown, unknown, unknown];
export type RobotId = string;
export type SentAtNs = number;
export type Seq = number;
export type SessionId = string;
export type StopReason = string;
export type UncertaintyM = number;
export type UncertaintyRad = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Velocity = [unknown, unknown];
export type Epoch6 = string;
export type ExpectedZones = string[];
export type MapDigest = string;
export type MapId = string;
export type PlanVersion = number;
export type ProjectedPath = [unknown, unknown, unknown][];
export type ProtocolVersion4 = string;
export type RobotId1 = string;
export type RunId6 = string;
export type SchemaVersion5 = string;
export type SentAtNs1 = number;
export type Seq1 = number;
export type SessionId1 = string;
export type ValidityHorizonNs = number;
export type Confidence = number;
export type Kind = string;
export type ObservationAgeNs = number;
export type ObservedAtNs = number;
/**
 * @minItems 2
 * @maxItems 2
 */
export type Position = [unknown, unknown];
export type RobotId2 = string;
export type SessionId2 = string;
export type ZoneId7 = string | null;
export type Degraded = boolean;
export type DegradedReason = string;
export type Epoch7 = string;
export type RobotId3 = string;
export type RunId7 = string;
export type SchemaVersion6 = string;
export type SentAtNs2 = number;
export type Seq2 = number;
export type SessionId3 = string;
export type BodyKind = string;
export type CorrelationId = string;
export type Epoch8 = string;
export type Kind1 = string;
export type ProtocolVersion5 = string;
export type RunId8 = string;
export type Sender = string;
export type SenderSession = string;
export type SentAtNs3 = number;
export type Seq3 = number;

/**
 * A peer message: envelope plus exactly one typed body.
 *
 * Dispatch on ``envelope.kind``. Bodies are stored as validated models (not
 * raw dicts) so an unknown critical field is a validation error rather than a
 * silently dropped key.
 */
export interface PeerMessage {
  body: Body;
  body_kind: BodyKind;
  envelope: PeerEnvelope;
}
/**
 * Request to acquire ``zone_id`` for protected movement ``movement``.
 */
export interface ZoneRequestBody {
  entry_pose: EntryPose;
  epoch: Epoch;
  exit_pose: ExitPose;
  expires_at_ns: ExpiresAtNs;
  membership_digest: MembershipDigest;
  movement: Movement;
  protocol_version?: ProtocolVersion;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  run_id: RunId;
  schema_version?: SchemaVersion;
  time_domain: TimeDomain;
  zone_id: ZoneId;
}
/**
 * A durable promise. The voter has persisted this before sending it.
 */
export interface ZoneGrantBody {
  epoch: Epoch1;
  grant_id: GrantId;
  is_self_voter?: IsSelfVoter;
  persistence_record_id: PersistenceRecordId;
  protocol_version?: ProtocolVersion1;
  request_version: RequestVersion1;
  requester: Requester1;
  requester_session: RequesterSession1;
  required_set_digest: RequiredSetDigest;
  run_id: RunId1;
  schema_version?: SchemaVersion1;
  zone_id: ZoneId1;
}
/**
 * Owner-initiated, durable cancellation.
 *
 * Sent only *after* the owner has persisted ``non_executable = true``. The
 * ``cancel_seq`` makes cancellation idempotent and makes late grants
 * identifiable.
 */
export interface ZoneCancelBody {
  cancel_seq: CancelSeq;
  durably_non_executable: DurablyNonExecutable;
  epoch: Epoch2;
  grant_id: GrantId1;
  protocol_version?: ProtocolVersion2;
  reason: Reason;
  request_version: RequestVersion2;
  requester: Requester2;
  requester_session: RequesterSession2;
  run_id: RunId2;
  schema_version?: SchemaVersion2;
  time_domain: TimeDomain;
  zone_id: ZoneId2;
}
export interface ZoneCancelAckBody {
  cancel_seq: CancelSeq1;
  no_record?: NoRecord;
  request_version: RequestVersion3;
  requester: Requester3;
  requester_session: RequesterSession3;
  voter: Voter;
  voter_session: VoterSession;
  zone_id: ZoneId3;
}
/**
 * Owner declares physical entry into the zone.
 */
export interface ZoneOccupyBody {
  epoch: Epoch3;
  grant_id: GrantId2;
  occupancy_seq: OccupancySeq;
  request_version: RequestVersion4;
  requester: Requester4;
  requester_session: RequesterSession4;
  run_id: RunId3;
  zone_id: ZoneId4;
}
/**
 * Owner declares exit and requests the authority be handed back.
 *
 * Release is **not** effective on send. It becomes effective only after every
 * voter has reconciled the release (a matching release message, never a
 * timeout).
 */
export interface ZoneReleaseBody {
  asserts_full_clearance?: AssertsFullClearance;
  epoch: Epoch4;
  grant_id: GrantId3;
  occupancy_seq: OccupancySeq1;
  protocol_version?: ProtocolVersion3;
  release_seq: ReleaseSeq;
  request_version: RequestVersion5;
  requester: Requester5;
  requester_session: RequesterSession5;
  run_id: RunId4;
  schema_version?: SchemaVersion3;
  time_domain: TimeDomain;
  zone_id: ZoneId5;
}
/**
 * Supervised, explicit fencing of a zone whose holder failed.
 *
 * There is deliberately no "force release" message. Fencing makes the zone
 * unavailable and is logged as an explicit, operator-visible state change.
 */
export interface ZoneFenceBody {
  epoch: Epoch5;
  fenced_by: FencedBy;
  operator_authorised?: OperatorAuthorised;
  previous_holder?: PreviousHolder;
  previous_requester_session?: PreviousRequesterSession;
  reason: Reason1;
  run_id: RunId5;
  schema_version?: SchemaVersion4;
  zone_id: ZoneId6;
}
/**
 * Published robot state. A claim, never ground truth.
 */
export interface PeerState {
  battery_fraction?: BatteryFraction;
  battery_source?: BatterySource;
  carrying_task_id?: CarryingTaskId;
  pose: Pose;
  robot_id: RobotId;
  sent_at_ns: SentAtNs;
  seq: Seq;
  session_id: SessionId;
  stop_reason?: StopReason;
  time_domain: TimeDomain;
  uncertainty_m: UncertaintyM;
  uncertainty_rad: UncertaintyRad;
  velocity: Velocity;
}
/**
 * Predicted path and the resources the sender expects to need.
 *
 * An intent is a *prediction*, never an authorization. Receiving one grants
 * nothing.
 */
export interface PeerIntent {
  epoch: Epoch6;
  expected_zones?: ExpectedZones;
  map_digest: MapDigest;
  map_id: MapId;
  plan_version: PlanVersion;
  projected_path?: ProjectedPath;
  protocol_version?: ProtocolVersion4;
  robot_id: RobotId1;
  run_id: RunId6;
  schema_version?: SchemaVersion5;
  sent_at_ns: SentAtNs1;
  seq: Seq1;
  session_id: SessionId1;
  time_domain: TimeDomain;
  validity_horizon_ns: ValidityHorizonNs;
}
/**
 * Shared observation of an obstruction, with provenance and age.
 */
export interface ObstructionReport {
  confidence?: Confidence;
  kind: Kind;
  observation_age_ns: ObservationAgeNs;
  observed_at_ns: ObservedAtNs;
  position: Position;
  robot_id: RobotId2;
  session_id: SessionId2;
  time_domain: TimeDomain;
  zone_id?: ZoneId7;
}
/**
 * Liveness only. Explicitly *not* usable intent and *not* clearance.
 */
export interface Heartbeat {
  degraded?: Degraded;
  degraded_reason?: DegradedReason;
  epoch: Epoch7;
  robot_id: RobotId3;
  run_id: RunId7;
  schema_version?: SchemaVersion6;
  sent_at_ns: SentAtNs2;
  seq: Seq2;
  session_id: SessionId3;
  time_domain: TimeDomain;
}
/**
 * Transport framing metadata. Present on every message, checked on receipt.
 */
export interface PeerEnvelope {
  correlation_id?: CorrelationId;
  epoch: Epoch8;
  kind: Kind1;
  protocol_version?: ProtocolVersion5;
  run_id: RunId8;
  sender: Sender;
  sender_session: SenderSession;
  sent_at_ns: SentAtNs3;
  seq: Seq3;
  time_domain: TimeDomain;
}

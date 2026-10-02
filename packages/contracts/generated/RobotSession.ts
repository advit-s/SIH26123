// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/RobotSession.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Host = string;
export type ListeningPort = number;
export type Pid = number;
export type ProtocolVersion = string;
export type RobotId = string;
export type SchemaVersion = string;
export type SessionId = string;
export type StartedAtNs = number;

/**
 * One incarnation (boot) of a robot.
 *
 * Every protocol message carries the session id of its sender. A message from
 * a stale session is rejected, never merged into current state.
 */
export interface RobotSession {
  host?: Host;
  listening_port?: ListeningPort;
  pid?: Pid;
  protocol_version?: ProtocolVersion;
  robot_id: RobotId;
  schema_version?: SchemaVersion;
  session_id: SessionId;
  started_at_ns: StartedAtNs;
}

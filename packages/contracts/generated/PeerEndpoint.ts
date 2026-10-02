// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/PeerEndpoint.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Host = string;
export type Port = number;
export type RobotId = string;

export interface PeerEndpoint {
  host?: Host;
  port: Port;
  robot_id: RobotId;
}

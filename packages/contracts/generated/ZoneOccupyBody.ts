// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneOccupyBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Epoch = string;
export type GrantId = string;
export type OccupancySeq = number;
export type RequestVersion = number;
export type Requester = string;
export type RequesterSession = string;
export type RunId = string;
export type ZoneId = string;

/**
 * Owner declares physical entry into the zone.
 */
export interface ZoneOccupyBody {
  epoch: Epoch;
  grant_id: GrantId;
  occupancy_seq: OccupancySeq;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  run_id: RunId;
  zone_id: ZoneId;
}

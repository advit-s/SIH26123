// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneGrantBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type Epoch = string;
export type GrantId = string;
export type IsSelfVoter = boolean;
export type PersistenceRecordId = string;
export type ProtocolVersion = string;
export type RequestVersion = number;
export type Requester = string;
export type RequesterSession = string;
export type RequiredSetDigest = string;
export type RunId = string;
export type SchemaVersion = string;
export type ZoneId = string;

/**
 * A durable promise. The voter has persisted this before sending it.
 */
export interface ZoneGrantBody {
  epoch: Epoch;
  grant_id: GrantId;
  is_self_voter?: IsSelfVoter;
  persistence_record_id: PersistenceRecordId;
  protocol_version?: ProtocolVersion;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  required_set_digest: RequiredSetDigest;
  run_id: RunId;
  schema_version?: SchemaVersion;
  zone_id: ZoneId;
}

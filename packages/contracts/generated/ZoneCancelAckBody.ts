// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/ZoneCancelAckBody.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type CancelSeq = number;
export type NoRecord = boolean;
export type RequestVersion = number;
export type Requester = string;
export type RequesterSession = string;
export type Voter = string;
export type VoterSession = string;
export type ZoneId = string;

export interface ZoneCancelAckBody {
  cancel_seq: CancelSeq;
  no_record?: NoRecord;
  request_version: RequestVersion;
  requester: Requester;
  requester_session: RequesterSession;
  voter: Voter;
  voter_session: VoterSession;
  zone_id: ZoneId;
}

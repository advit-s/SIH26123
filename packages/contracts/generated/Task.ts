// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/Task.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
export type DropStationId = string;
export type PickupStationId = string;
export type Priority = number;
export type ReleaseAtS = number;
export type RequiredCapabilities = string[];
export type SchemaVersion = string;
export type ServiceTimeS = number;
export type TaskId = string;
export type WeightKg = number;

/**
 * A transport job. Generated independently of assignment.
 */
export interface Task {
  drop_station_id: DropStationId;
  pickup_station_id: PickupStationId;
  priority?: Priority;
  release_at_s?: ReleaseAtS;
  required_capabilities?: RequiredCapabilities;
  schema_version?: SchemaVersion;
  service_time_s?: ServiceTimeS;
  task_id: TaskId;
  weight_kg?: WeightKg;
}

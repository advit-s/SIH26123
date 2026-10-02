// GENERATED FILE - DO NOT EDIT BY HAND.
// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/EnvironmentRecord.json
// Regenerate: pnpm --filter @niharamesh/contracts generate
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

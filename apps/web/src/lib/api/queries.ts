/**
 * TanStack Query bindings.
 *
 * Server state only. Every hook returns the domain read model or an `ApiError`;
 * nothing here substitutes a default for a failed request, so components can
 * render a real error state instead of zeros.
 *
 * Poll cadences are chosen from what the operator actually needs:
 *   health / doctor  — slow (5s, 15s): liveness and build identity
 *   run state        — 1s while live: the context bar clocks
 *   robots / zones   — 1s while live: inspectors
 *   tasks            — 2s: auctions resolve on human timescales
 *   telemetry        — NOT polled. It arrives on the WebSocket stream, because
 *                      polling high-rate replaceable data would waste the
 *                      recorder and produce aliasing. See `./stream.ts`.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { api } from "./client"
import {
  mapCommands,
  mapCommunication,
  mapDoctor,
  mapEventPage,
  mapExperimentDetail,
  mapExperimentMatrix,
  mapFaults,
  mapHealth,
  mapMapGeometry,
  mapReplayDetail,
  mapReplayIndex,
  mapReportBundle,
  mapRobots,
  mapRunDescriptor,
  mapRunDetail,
  mapRunState,
  mapScenarioDetail,
  mapScenarioSummary,
  mapTaskInspection,
  mapValidationReport,
  mapZoneInspection,
} from "./mappers"
import type { Scenario } from "@niharamesh/contracts/generated"
import type { ApiPolicy, TaskInspection, ZoneInspection } from "./types"

export const queryKeys = {
  health: ["health"] as const,
  doctor: ["doctor"] as const,
  scenarios: ["scenarios"] as const,
  scenario: (id: string) => ["scenario", id] as const,
  runs: ["runs"] as const,
  run: (runId: string) => ["run", runId] as const,
  runState: (runId: string) => ["run-state", runId] as const,
  robots: (runId: string) => ["robots", runId] as const,
  zones: (runId: string) => ["zones", runId] as const,
  tasks: (runId: string) => ["tasks", runId] as const,
  events: (runId: string, filter: string) => ["events", runId, filter] as const,
  communication: (runId: string) => ["communication", runId] as const,
  commands: (runId: string) => ["commands", runId] as const,
  faults: (runId: string) => ["faults", runId] as const,
  experiments: ["experiments"] as const,
  experiment: (batchId: string) => ["experiment", batchId] as const,
  report: (batchId: string) => ["report", batchId] as const,
  replays: ["replays"] as const,
  replay: (runId: string) => ["replay", runId] as const,
}

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: async () => mapHealth(await api.health()),
    refetchInterval: 5000,
    staleTime: 2000,
    // Short backoff: an operations console must surface a refused read quickly.
    // The long default (1s) hides the honest error behind a spinner.
    retry: 1,
    retryDelay: 400,
  })
}

export function useDoctor(enabled = true) {
  return useQuery({
    queryKey: queryKeys.doctor,
    queryFn: async () => mapDoctor(await api.doctor()),
    enabled,
    refetchInterval: 15000,
    staleTime: 10000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useScenarioLibrary() {
  return useQuery({
    queryKey: queryKeys.scenarios,
    queryFn: async () => {
      const raw = await api.scenarios()
      return asArray(raw).map(mapScenarioSummary)
    },
    staleTime: 10000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useScenarioDetail(scenarioId: string | null) {
  return useQuery({
    queryKey: queryKeys.scenario(scenarioId ?? ""),
    queryFn: async () => mapScenarioDetail(await api.scenario(scenarioId as string)),
    enabled: scenarioId !== null,
    staleTime: 30000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useRuns() {
  return useQuery({
    queryKey: queryKeys.runs,
    queryFn: async () => asArray(await api.runs()).map(mapRunDescriptor),
    refetchInterval: 5000,
    staleTime: 3000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useRunDetail(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.run(runId ?? ""),
    queryFn: async () => mapRunDetail(await api.run(runId as string)),
    enabled: runId !== null,
    staleTime: 10000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useRunState(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.runState(runId ?? ""),
    queryFn: async () => mapRunState(await api.runState(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1000 : 10000,
    staleTime: live ? 500 : 4000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useRobots(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.robots(runId ?? ""),
    queryFn: async () => mapRobots(await api.robots(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1000 : 10000,
    staleTime: live ? 500 : 4000,
    // Refetching must never discard the last good inspector payload; the UI
    // decides how to show staleness.
    retry: 1,
    retryDelay: 500,
  })
}

export function useZones(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.zones(runId ?? ""),
    queryFn: async () => mapZonesFrom(await api.zones(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1000 : 10000,
    staleTime: live ? 500 : 4000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useTasks(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.tasks(runId ?? ""),
    queryFn: async () => mapTasksFrom(await api.tasks(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 2000 : 15000,
    staleTime: 1500,
    retry: 1,
    retryDelay: 500,
  })
}

export interface EventFilters {
  afterSeq?: number
  limit?: number
  robotId?: string
  zoneId?: string
  taskId?: string
  categories?: string[]
}

export function useEvents(runId: string | null, filters: EventFilters, enabled = true) {
  const filterKey = JSON.stringify(filters)
  return useQuery({
    queryKey: queryKeys.events(runId ?? "", filterKey),
    queryFn: async () =>
      mapEventPage(
        await api.events(runId as string, {
          after_seq: filters.afterSeq,
          limit: filters.limit ?? 200,
          robot_id: filters.robotId,
          zone_id: filters.zoneId,
          task_id: filters.taskId,
          categories: filters.categories?.join(","),
        }),
      ),
    enabled: enabled && runId !== null,
    staleTime: 1000,
    refetchInterval: 2000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useCommunication(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.communication(runId ?? ""),
    queryFn: async () => mapCommunication(await api.communication(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1500 : 15000,
    staleTime: 1200,
    retry: 1,
    retryDelay: 500,
  })
}

export function useCommands(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.commands(runId ?? ""),
    queryFn: async () => mapCommands(await api.commands(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1000 : 15000,
    staleTime: 800,
    retry: 1,
    retryDelay: 500,
  })
}

export function useFaults(runId: string | null, live: boolean) {
  return useQuery({
    queryKey: queryKeys.faults(runId ?? ""),
    queryFn: async () => mapFaults(await api.faults(runId as string)),
    enabled: runId !== null,
    refetchInterval: live ? 1500 : 15000,
    staleTime: 1200,
    retry: 1,
    retryDelay: 500,
  })
}

export function useExperiments() {
  return useQuery({
    queryKey: queryKeys.experiments,
    queryFn: async () => mapExperimentMatrix(await api.experiments()),
    staleTime: 10000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useExperimentDetail(batchId: string | null) {
  return useQuery({
    queryKey: queryKeys.experiment(batchId ?? ""),
    queryFn: async () => mapExperimentDetail(await api.experiment(batchId as string)),
    enabled: batchId !== null,
    staleTime: 5000,
    refetchInterval: 5000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useExperimentReport(batchId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.report(batchId ?? ""),
    queryFn: async () => mapReportBundle(await api.experimentReport(batchId as string)),
    enabled: enabled && batchId !== null,
    staleTime: 60000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useReplayIndex() {
  return useQuery({
    queryKey: queryKeys.replays,
    queryFn: async () => asArray(await api.replays()).map(mapReplayIndex),
    staleTime: 15000,
    retry: 1,
    retryDelay: 500,
  })
}

export function useReplayDetail(runId: string | null) {
  return useQuery({
    queryKey: queryKeys.replay(runId ?? ""),
    queryFn: async () => mapReplayDetail(await api.replay(runId as string)),
    enabled: runId !== null,
    staleTime: 30000,
    retry: 1,
    retryDelay: 500,
  })
}

/* -------------------------------------------------------------------------- */
/* Mutations                                                                  */
/* -------------------------------------------------------------------------- */

export function useValidateScenario() {
  return useMutation({
    mutationFn: async (scenario: Scenario) => mapValidationReport(await api.validateScenario(scenario)),
  })
}

export function useSaveScenario() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (scenario: Scenario) => mapScenarioSummary(await api.saveScenario(scenario)),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.scenarios })
    },
  })
}

export interface LaunchResult {
  run_id: string
  snapshot_id: string | null
}

export function useLaunchScenario() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (input: { scenarioId: string; idempotencyKey: string }): Promise<LaunchResult> => {
      const raw = (await api.launchScenario(input.scenarioId, input.idempotencyKey)) as unknown
      const o = (raw ?? {}) as Record<string, unknown>
      const runId = typeof o.run_id === "string" ? o.run_id : null
      if (runId === null) {
        throw new Error("The API accepted the launch but did not return a run_id, so there is nothing to open.")
      }
      return { run_id: runId, snapshot_id: typeof o.snapshot_id === "string" ? o.snapshot_id : null }
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.runs })
    },
  })
}

export function useSendCommand(runId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { command: string; params: Record<string, unknown>; idempotency_key: string }) =>
      api.sendCommand(runId as string, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.commands(runId ?? "") })
    },
  })
}

export function useInjectFault(runId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: unknown) => api.injectFault(runId as string, body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.faults(runId ?? "") })
      void qc.invalidateQueries({ queryKey: queryKeys.events(runId ?? "", "") })
    },
  })
}

export function useClearFault(runId: string | null) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (faultId: string) => api.clearFault(runId as string, faultId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.faults(runId ?? "") })
    },
  })
}

export function useCreateExperimentBatch() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: { scenario_id: string; seeds: number[]; coordination: string[]; revisions: number[] }) =>
      api.createExperimentBatch(body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: queryKeys.experiments })
    },
  })
}

export function useExportRun(runId: string | null) {
  return useMutation({
    mutationFn: async () => api.exportRun(runId as string),
  })
}

/* -------------------------------------------------------------------------- */
/* Map geometry                                                               */
/* -------------------------------------------------------------------------- */

export function useMapGeometry(runId: string | null, scenario: unknown) {
  return useQuery({
    queryKey: ["map-geometry", runId, scenario === null ? "none" : "scenario"],
    queryFn: async () => {
      const detail = await api.run(runId as string)
      const o = (detail ?? {}) as Record<string, unknown>
      const snapshot = o.snapshot ?? o.scenario
      if (snapshot) {
        const m = mapMapGeometry(snapshot)
        if (m) return m
      }
      return mapMapGeometry(scenario)
    },
    enabled: runId !== null || scenario !== null,
    staleTime: 60000,
    retry: 1,
    retryDelay: 500,
  })
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

/** Tolerate `{ robots: [...] }` and bare `[...]` alike. */
function mapZonesFrom(raw: unknown): ZoneInspection[] {
  const list = Array.isArray(raw) ? raw : asArray((raw as Record<string, unknown>)?.zones)
  return list.map(mapZoneInspection)
}

function mapTasksFrom(raw: unknown): TaskInspection[] {
  const list = Array.isArray(raw) ? raw : asArray((raw as Record<string, unknown>)?.tasks)
  return list.map(mapTaskInspection)
}

export type { ApiPolicy }

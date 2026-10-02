/**
 * API availability probe for the browser workflows.
 *
 * Every spec in this folder needs the NĪHĀRAMESH application API. Without it the
 * cockpit correctly shows an error state and no run data, which would make the
 * workflow specs fail for a reason that has nothing to do with the workflow.
 *
 * Rather than letting them fail obscurely — or silently passing — each spec calls
 * `requireApi()` first. If the API is not answering, the test is **skipped with
 * a reason that names the command which starts it**. A skipped test therefore
 * always says why.
 */
import { expect, test } from "@playwright/test"

const API_BASE = process.env.NIHARA_API_BASE ?? "http://127.0.0.1:8100"
const HEALTH_URL = `${API_BASE}/api/v1/health`

export interface ApiProbe {
  ok: boolean
  status: string | null
  version: string | null
  runId: string | null
  mode: string | null
  reason: string
}

let cached: ApiProbe | null = null

/** Probe `/api/v1/health`. Cached for the duration of the worker. */
export async function probeApi(): Promise<ApiProbe> {
  if (cached !== null) return cached
  try {
    const response = await fetch(HEALTH_URL, { signal: AbortSignal.timeout(4000) })
    if (!response.ok) {
      cached = {
        ok: false,
        status: null,
        version: null,
        runId: null,
        mode: null,
        reason: `GET ${HEALTH_URL} answered HTTP ${response.status}.`,
      }
      return cached
    }
    const body = (await response.json()) as Record<string, unknown>
    cached = {
      ok: true,
      status: typeof body.status === "string" ? body.status : null,
      version: typeof body.version === "string" ? body.version : null,
      runId: typeof body.run_id === "string" ? body.run_id : null,
      mode: typeof body.mode === "string" ? body.mode : null,
      reason: `GET ${HEALTH_URL} answered ${String(body.status)} (v${String(body.version)}).`,
    }
    return cached
  } catch (error: unknown) {
    cached = {
      ok: false,
      status: null,
      version: null,
      runId: null,
      mode: null,
      reason: `GET ${HEALTH_URL} could not be reached: ${error instanceof Error ? error.message : String(error)}`,
    }
    return cached
  }
}

const START_HINT = [
  "the NĪHÄRAMESH API is not running.",
  "Start it with `pnpm dev` (API on http://127.0.0.1:8100 + cockpit on http://127.0.0.1:5173),",
  "or diagnose it with `pnpm doctor`, then re-run this spec with:",
  "pnpm test:e2e",
].join(" ")

/**
 * Skip the calling spec with an explicit reason when the API is unreachable.
 * Returns the probe when the API is healthy.
 */
export async function requireApi(): Promise<ApiProbe> {
  const probe = await probeApi()
  test.skip(!probe.ok, `${START_HINT} Probe: ${probe.reason}`)
  return probe
}

/**
 * Skip when the API answers but has no run to inspect. This is a *different*
 * situation from "API down" and must read differently.
 */
export async function requireRun(probe: ApiProbe): Promise<string> {
  if (probe.runId !== null && probe.runId.length > 0) return probe.runId
  const runs = await listRuns()
  if (runs.length > 0) return runs[0] as string
  test.skip(
    true,
    "The API is running but has no run recorded yet, so there is nothing to inspect. " +
      "Create one with `pnpm demo` (guided three-robot run with fault injection) or `pnpm benchmark:smoke`, then re-run this spec.",
  )
  return ""
}

async function listRuns(): Promise<string[]> {
  try {
    const response = await fetch(`${API_BASE}/api/v1/runs`, { signal: AbortSignal.timeout(4000) })
    if (!response.ok) return []
    const body = (await response.json()) as unknown
    const list = Array.isArray(body) ? body : []
    return list
      .map((item) => (typeof item === "object" && item !== null ? (item as { run_id?: unknown }).run_id : null))
      .filter((id): id is string => typeof id === "string")
  } catch {
    return []
  }
}

/** A convenience assertion that the cockpit is talking to a real API. */
export async function expectHealthyApi(probe: ApiProbe): Promise<void> {
  expect(probe.ok, probe.reason).toBe(true)
}
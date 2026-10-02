/**
 * Thin fetch wrapper for the NĪHĀRAMESH application API.
 *
 * Two rules this file exists to enforce:
 *   1. A failed request NEVER becomes a fabricated value. Every non-2xx response
 *      and every transport failure becomes an `ApiError` carrying the API's
 *      stable `code`, so views can render an honest error state instead of
 *      zeros.
 *   2. No convenience here reaches across an authority boundary. This module
 *      only *reads* what the API publishes; it never advances robot truth,
 *      never grants authority, and never fills a missing field with a default.
 */
import { ApiError } from "./types"

const RAW_BASE = import.meta.env.VITE_API_BASE
export const API_BASE = (typeof RAW_BASE === "string" && RAW_BASE.length > 0 ? RAW_BASE : "http://127.0.0.1:8100").replace(
  /\/+$/,
  "",
)
export const API_ROOT = `${API_BASE}/api/v1`

interface ErrorEnvelope {
  error?: {
    code?: unknown
    message?: unknown
    request_id?: unknown
    details?: unknown
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

/** Parse the documented error envelope; fall back honestly when it is absent. */
function toApiError(status: number, body: unknown, rawText: string): ApiError {
  const envelope = isRecord(body) ? (body as ErrorEnvelope) : undefined
  const err = envelope?.error
  const code = typeof err?.code === "string" ? err.code : `http_${status}`
  const message =
    typeof err?.message === "string" && err.message.length > 0
      ? err.message
      : `The API returned HTTP ${status} without a readable error envelope.`
  const requestId = typeof err?.request_id === "string" ? err.request_id : null
  const details = isRecord(err?.details) ? (err.details as Record<string, unknown>) : null
  void rawText
  return new ApiError({ code, message, status, requestId, details })
}

export interface RequestOptions {
  method?: "GET" | "POST" | "DELETE"
  query?: Record<string, string | number | boolean | undefined | null>
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

function buildUrl(path: string, query: RequestOptions["query"]): string {
  const url = `${API_ROOT}${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue
    params.set(key, String(value))
  }
  const qs = params.toString()
  return qs.length > 0 ? `${url}?${qs}` : url
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", query, body, headers = {}, signal } = options
  const init: RequestInit = { method, signal, headers: { Accept: "application/json", ...headers } }
  if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { ...init.headers, "Content-Type": "application/json" }
  }

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), init)
  } catch (cause) {
    // Distinguish "server not running" from a mid-flight abort so the UI can
    // say "the API is not reachable" rather than "error".
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause
    throw new ApiError({
      code: "api_unreachable",
      message: `Could not reach the NĪHĀRAMESH API at ${API_BASE}. Start it with \`pnpm dev\`.`,
      status: 0,
      unreachable: true,
    })
  }

  const text = await response.text()
  let parsed: unknown = null
  if (text.length > 0) {
    try {
      parsed = JSON.parse(text)
    } catch {
      parsed = null
    }
  }

  if (!response.ok) throw toApiError(response.status, parsed, text)

  if (parsed === null) {
    throw new ApiError({
      code: "malformed_response",
      message: `The API returned HTTP ${response.status} with a body that is not JSON. This run's evidence cannot be trusted.`,
      status: response.status,
    })
  }
  return parsed as T
}

/* -------------------------------------------------------------------------- */
/* Read endpoints                                                             */
/* -------------------------------------------------------------------------- */

export const api = {
  health: () => request<unknown>("/health"),
  doctor: () => request<unknown>("/system/doctor"),
  scenarios: () => request<unknown>("/scenarios"),
  scenario: (id: string) => request<unknown>(`/scenarios/${encodeURIComponent(id)}`),
  runs: () => request<unknown>("/runs"),
  run: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}`),
  runState: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/state`),
  robots: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/robots`),
  zones: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/zones`),
  tasks: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/tasks`),
  events: (
    runId: string,
    q: {
      after_seq?: number
      limit?: number
      robot_id?: string
      zone_id?: string
      task_id?: string
      categories?: string
    },
  ) => request<unknown>(`/runs/${encodeURIComponent(runId)}/events`, { query: q }),
  telemetry: (runId: string, q: { after?: number; limit?: number }) =>
    request<unknown>(`/runs/${encodeURIComponent(runId)}/telemetry`, { query: q }),
  communication: (runId: string) =>
    request<unknown>(`/runs/${encodeURIComponent(runId)}/communication`),
  commands: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/commands`),
  faults: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/faults`),
  experiments: () => request<unknown>("/experiments"),
  experiment: (batchId: string) =>
    request<unknown>(`/experiments/${encodeURIComponent(batchId)}`),
  experimentReport: (batchId: string) =>
    request<unknown>(`/experiments/${encodeURIComponent(batchId)}/report`),
  replays: () => request<unknown>("/replays"),
  replay: (runId: string) => request<unknown>(`/replays/${encodeURIComponent(runId)}`),

  /* Write endpoints ------------------------------------------------------ */

  validateScenario: (scenario: unknown) =>
    request<unknown>("/scenarios/validate", { method: "POST", body: scenario }),

  saveScenario: (scenario: unknown) =>
    request<unknown>("/scenarios", { method: "POST", body: scenario }),

  launchScenario: (scenarioId: string, idempotencyKey: string) =>
    request<unknown>(`/scenarios/${encodeURIComponent(scenarioId)}/launch`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
    }),

  sendCommand: (runId: string, body: unknown) =>
    request<unknown>(`/runs/${encodeURIComponent(runId)}/commands`, { method: "POST", body }),

  injectFault: (runId: string, body: unknown) =>
    request<unknown>(`/runs/${encodeURIComponent(runId)}/faults`, { method: "POST", body }),

  clearFault: (runId: string, faultId: string) =>
    request<unknown>(`/runs/${encodeURIComponent(runId)}/faults/${encodeURIComponent(faultId)}`, {
      method: "DELETE",
    }),

  createExperimentBatch: (body: unknown) =>
    request<unknown>("/experiments", { method: "POST", body }),

  exportRun: (runId: string) => request<unknown>(`/runs/${encodeURIComponent(runId)}/export`, { method: "POST" }),
}

/* -------------------------------------------------------------------------- */
/* Event page envelope                                                        */
/* -------------------------------------------------------------------------- */

export type { EventPage } from "./types"

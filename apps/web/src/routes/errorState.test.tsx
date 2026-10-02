/**
 * Behaviour test for the API-failure path.
 *
 * Invariant 2: no invented measurements. When the API refuses, the cockpit must
 * render a stated error — never a panel full of zeros that reads like "nothing
 * happened" or "nothing is wrong".
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { OperationsPage } from "./OperationsPage"

function client(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
  })
}

function wrapper(ui: React.ReactNode) {
  return <QueryClientProvider client={client()}>{ui}</QueryClientProvider>
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("OperationsPage error handling", () => {
  it("states the API error instead of rendering zero-valued metrics", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        if (url.includes("/health")) {
          return new Response(
            JSON.stringify({
              status: "ok",
              version: "0.1.0",
              schema_version: "1.0.0",
              protocol_version: "1.0.0",
              mode: "deterministic",
              run_id: null,
              recording_healthy: true,
              uptime_s: 3,
            }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          )
        }
        return new Response(
          JSON.stringify({
            error: {
              code: "recorder_unavailable",
              message: "The recorder process is not attached to this run.",
              request_id: "req-77",
              details: { run_id: "run-x" },
            },
          }),
          { status: 503, headers: { "Content-Type": "application/json" } },
        )
      }),
    )

    render(wrapper(<OperationsPage runId="run-x" freshnessHorizonS={2.5} physicalActuation={false} onGoToScenarios={() => {}} />))

    // The cockpit retries a failed read once with backoff before declaring the
    // failure, so allow for that delay rather than weakening the assertion.
    await waitFor(
      () => {
        expect(screen.getAllByText(/could not be loaded/i).length).toBeGreaterThan(0)
      },
      { timeout: 8000 },
    )

    // The API's own stable code and message are surfaced.
    expect(screen.getAllByText("recorder_unavailable").length).toBeGreaterThan(0)
    expect(screen.getAllByText("The recorder process is not attached to this run.").length).toBeGreaterThan(0)
    expect(screen.getAllByText("req-77").length).toBeGreaterThan(0)

    // And nothing pretends to have measured zero robots.
    expect(screen.queryByText("0 agents")).toBeNull()
  })

  it("explains that the API is not running, and names the command that starts it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch")
      }),
    )

    render(wrapper(<OperationsPage runId="run-x" freshnessHorizonS={2.5} physicalActuation={false} onGoToScenarios={() => {}} />))

    await waitFor(
      () => {
        expect(screen.getAllByText(/The API is not reachable/i).length).toBeGreaterThan(0)
      },
      { timeout: 8000 },
    )
    expect(screen.getAllByText("pnpm dev").length).toBeGreaterThan(0)
    expect(screen.getAllByText(/api_unreachable/).length).toBeGreaterThan(0)
  })

  it("offers no run at all rather than an empty map when no run is attached", () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 200 })))
    render(wrapper(<OperationsPage runId={null} freshnessHorizonS={2.5} physicalActuation={false} onGoToScenarios={() => {}} />))
    expect(screen.getByText("No run attached")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Go to Scenarios" })).toBeInTheDocument()
  })
})
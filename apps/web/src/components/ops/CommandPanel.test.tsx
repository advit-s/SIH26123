/**
 * Behaviour tests for the command lifecycle.
 *
 * The rule under test: **a sent command is not an observed stop.** The four
 * stages must render as four distinct states, and a command that has only been
 * requested must say so rather than implying the robot stopped.
 */
import { screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { CommandPanel } from "./CommandPanel"
import { renderWithProviders } from "../../test/renderWithProviders"
import type { CommandRecord, RunStateSnapshot } from "../../lib/api/types"

function state(overrides: Partial<RunStateSnapshot> = {}): RunStateSnapshot {
  return {
    run_id: "run-1",
    mode: "deterministic",
    state: "running",
    outcome: "unknown",
    sim_time_s: 12,
    wall_time_utc: null,
    speed_multiplier: 1,
    paused: false,
    tick: 1200,
    max_sim_time_s: 600,
    robot_count: 3,
    coordination_policy: "canonical_sequential",
    assignment_policy: "local_auction",
    routing_policy: null,
    scenario_id: "s",
    scenario_revision: 1,
    scenario_digest: null,
    map_id: "m",
    map_revision: 1,
    map_digest: null,
    recording_healthy: true,
    recording_gaps: [],
    last_seq: 10,
    ...overrides,
  }
}

function record(overrides: Partial<CommandRecord> = {}): CommandRecord {
  return {
    command_id: "cmd-1",
    idempotency_key: "cockpit-request_stop-0001",
    command: "request_stop",
    params: { scope: "run" },
    requested: { state: "requested", at_utc: "2026-10-02T09:20:00Z", detail: "accepted by the API" },
    acknowledged: { state: "unknown", at_utc: null, detail: null },
    applied: { state: "unknown", at_utc: null, detail: null },
    observed: { state: "unknown", at_utc: null, detail: null },
    requested_by: "operator",
    run_id: "run-1",
    ...overrides,
  }
}

function renderPanel(props: { state: RunStateSnapshot; records: CommandRecord[] }): void {
  renderWithProviders(
    <CommandPanel runId="run-1" state={props.state} records={props.records} physicalActuation={false} />,
  )
}

describe("CommandPanel", () => {
  it("labels the panel as the simulation harness, never as an emergency stop", () => {
    renderPanel({ state: state(), records: [] })
    expect(screen.getByText("experiment harness — simulation")).toBeInTheDocument()
    expect(screen.getByText(/It is not an emergency stop/)).toBeInTheDocument()
    expect(screen.getByText(/cannot stop a physical robot/)).toBeInTheDocument()
  })

  it("shows requested and observed as distinct stages", () => {
    renderPanel({ state: state(), records: [record()] })
    const line = screen.getByTestId("command-stage-cmd-1")
    expect(line).toHaveTextContent("requested=requested")
    expect(line).toHaveTextContent("acknowledged=unknown")
    expect(line).toHaveTextContent("applied=unknown")
    expect(line).toHaveTextContent("observed=unknown")
    // And it says in words that this has not been confirmed by evidence.
    expect(screen.getByText(/Not observed yet/)).toBeInTheDocument()
  })

  it("reports the four stages independently when only some have happened", () => {
    renderPanel({
      state: state(),
      records: [
        record({
          acknowledged: { state: "acknowledged", at_utc: null, detail: "coordinator accepted" },
          applied: { state: "applied", at_utc: null, detail: "stop request forwarded" },
        }),
      ],
    })
    const line = screen.getByTestId("command-stage-cmd-1")
    expect(line).toHaveTextContent("acknowledged=acknowledged")
    expect(line).toHaveTextContent("applied=applied")
    expect(line).toHaveTextContent("observed=unknown")
    // Still not observed, and it still says so.
    expect(screen.getByText(/Not observed yet/)).toBeInTheDocument()
  })

  it("shows the observed stage once the world confirms the stop", () => {
    renderPanel({
      state: state({ paused: true, state: "paused" }),
      records: [
        record({
          acknowledged: { state: "acknowledged", at_utc: null, detail: null },
          applied: { state: "applied", at_utc: null, detail: null },
          observed: {
            state: "observed",
            at_utc: "2026-10-02T09:20:04Z",
            detail: "AMR2 reports linear velocity 0.00 m/s with stop_reason operator_request",
          },
        }),
      ],
    })
    const line = screen.getByTestId("command-stage-cmd-1")
    expect(line).toHaveTextContent("observed=observed")
    expect(screen.getByText(/AMR2 reports linear velocity 0.00 m\/s/)).toBeInTheDocument()
    expect(screen.queryByText(/Not observed yet/)).toBeNull()
  })

  it("offers resume rather than pause when the harness is already paused", () => {
    renderPanel({ state: state({ paused: true }), records: [] })
    expect(screen.getByTestId("cmd-pause")).toHaveTextContent("Resume simulation")
  })

  it("states that physical actuation is disabled for this run", () => {
    renderPanel({ state: state(), records: [] })
    const strip = screen.getByText(/Physical actuation is/).closest("div")
    expect(strip?.textContent).toContain("disabled")
  })
})
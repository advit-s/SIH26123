/**
 * Behaviour tests for the context bar.
 *
 * The product's single most important visual promise is that an operator can
 * never confuse recorded playback, a paused harness, a deterministic run and a
 * live run of separate processes. These tests assert the *distinctions*, not the
 * wording: the mode plate changes kind, changes paint and changes the caption.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { ContextBar } from "./ContextBar"
import type { HealthStatus, RunStateSnapshot } from "../../lib/api/types"

function state(overrides: Partial<RunStateSnapshot> = {}): RunStateSnapshot {
  return {
    run_id: "run-2026-10-02-abc123",
    mode: "deterministic",
    state: "running",
    outcome: "unknown",
    sim_time_s: 42.5,
    wall_time_utc: "2026-10-02T09:15:00Z",
    speed_multiplier: 1,
    paused: false,
    tick: 4250,
    max_sim_time_s: 600,
    robot_count: 3,
    coordination_policy: "canonical_sequential",
    assignment_policy: "local_auction",
    routing_policy: "blocked_aware",
    scenario_id: "three-way",
    scenario_revision: 4,
    scenario_digest: "d1g2e3s4t5",
    map_id: "warehouse-a",
    map_revision: 2,
    map_digest: "m1a2p3",
    recording_healthy: true,
    recording_gaps: [],
    last_seq: 812,
    ...overrides,
  }
}

const HEALTH: HealthStatus = {
  status: "ok",
  version: "0.1.0",
  schema_version: "1.0.0",
  protocol_version: "1.0.0",
  mode: "deterministic",
  run_id: "run-2026-10-02-abc123",
  recording_healthy: true,
  uptime_s: 128.4,
}

function renderBar(overrides: Partial<RunStateSnapshot> = {}, replaying = false) {
  return render(
    <ContextBar
      state={state(overrides)}
      health={HEALTH}
      streamStatus="live"
      streamAgeS={0.2}
      replaying={replaying}
      physicalActuation={false}
    />,
  )
}

describe("ContextBar", () => {
  it("shows the execution mode, the run id and the immutable scenario revision", () => {
    renderBar()
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("DETERMINISTIC")
    expect(screen.getByTestId("context-run-id")).toHaveTextContent("run-2026-10-02-abc123")
    expect(screen.getByText("three-way r4")).toBeInTheDocument()
    expect(screen.getByText("warehouse-a r2")).toBeInTheDocument()
  })

  it("reports the simulation clock in the logical domain and the wall clock separately", () => {
    renderBar()
    // 42.5 sim seconds -> 0:42.5 in the logical domain.
    expect(screen.getByTestId("context-sim-time")).toHaveTextContent("0:42.5")
    expect(screen.getByText("2026-10-02 09:15:00 UTC")).toBeInTheDocument()
    // Each clock names its own domain. They are never merged.
    expect(screen.getByText("sim s · logical")).toBeInTheDocument()
    expect(screen.getByText("wall · UTC")).toBeInTheDocument()
  })

  it("marks a live run of separate processes differently from a deterministic run", () => {
    const { unmount } = renderBar({ mode: "processes" })
    const plate = screen.getByTestId("execution-plate")
    expect(plate).toHaveAttribute("data-execution-kind", "processes")
    expect(plate).toHaveAttribute("data-frozen", "false")
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("LIVE PROCESSES")
    unmount()

    renderBar()
    expect(screen.getByTestId("execution-plate")).toHaveAttribute("data-execution-kind", "deterministic")
  })

  it("distinguishes a paused harness from a live run and freezes it", () => {
    renderBar({ paused: true, state: "paused" })
    const plate = screen.getByTestId("execution-plate")
    expect(plate).toHaveAttribute("data-execution-kind", "paused")
    expect(plate).toHaveAttribute("data-frozen", "true")
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("PAUSED HARNESS")
  })

  it("distinguishes recorded playback from every live mode, and freezes it", () => {
    renderBar({}, true)
    const plate = screen.getByTestId("execution-plate")
    expect(plate).toHaveAttribute("data-execution-kind", "replay")
    expect(plate).toHaveAttribute("data-frozen", "true")
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("RECORDED PLAYBACK")
    expect(screen.getByText(/Nothing is being simulated/)).toBeInTheDocument()
  })

  it("gives physical operation its own treatment and says what it means", () => {
    render(
      <ContextBar
        state={state({ mode: "processes" })}
        health={HEALTH}
        streamStatus="live"
        streamAgeS={0.1}
        replaying={false}
        physicalActuation
      />,
    )
    const plate = screen.getByTestId("execution-plate")
    expect(plate).toHaveAttribute("data-execution-kind", "hardware")
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("PHYSICAL ACTUATION")
    expect(screen.getByText(/Stopping this browser does not stop the fleet/)).toBeInTheDocument()
  })

  it("reports an intact recording as complete", () => {
    renderBar({ recording_healthy: true, recording_gaps: [] })
    expect(screen.getByText("complete")).toBeInTheDocument()
  })

  it("counts recording gaps instead of hiding them behind a healthy tick", () => {
    renderBar({
      recording_healthy: false,
      recording_gaps: [
        {
          run_id: "r",
          category: "authority",
          cause: "recorder restart",
          from_seq: 400,
          to_seq: 419,
          sim_time_from_s: 12,
          sim_time_to_s: 14,
        },
      ],
    })
    expect(screen.getByText("1 gap")).toBeInTheDocument()
  })

  it("shows the age of the newest stream frame rather than pretending it is current", () => {
    render(
      <ContextBar
        state={state()}
        health={HEALTH}
        streamStatus="reconnecting"
        streamAgeS={12.5}
        replaying={false}
        physicalActuation={false}
      />,
    )
    expect(screen.getByText("reconnecting")).toBeInTheDocument()
    expect(screen.getByText("12.5 s old")).toBeInTheDocument()
  })

  it("says no run is selected instead of rendering placeholder zeros", () => {
    render(
      <ContextBar
        state={null}
        health={null}
        streamStatus="idle"
        streamAgeS={null}
        replaying={false}
        physicalActuation={false}
      />,
    )
    expect(screen.getByTestId("execution-mode")).toHaveTextContent("NO RUN SELECTED")
    expect(screen.getByTestId("context-run-id")).toHaveTextContent("unavailable")
    expect(screen.getByText("no telemetry")).toBeInTheDocument()
  })
})
/**
 * Behaviour tests for experiment eligibility.
 *
 * The rule under test: **no successful performance badge for an incomplete,
 * unsafe, timed-out or cancelled run.** A run that produced no makespan, or one
 * whose recording has gaps, must render as a failure with no check mark.
 */
import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"
import { SuccessBadge, cellVerdict } from "./ExperimentsPage"
import type { ExperimentCell } from "../lib/api/types"

function cell(overrides: Partial<ExperimentCell> = {}): ExperimentCell {
  return {
    run_id: "run-a",
    scenario_id: "three-way",
    scenario_revision: 4,
    seed: 101,
    coordination_policy: "canonical_sequential",
    state: "completed",
    outcome: "success",
    makespan_s: 132.4,
    tasks_completed: 12,
    tasks_total: 12,
    collisions: 0,
    evidence_complete: true,
    ...overrides,
  }
}

describe("cellVerdict", () => {
  it("marks a completed, evidence-complete success as the only eligible kind", () => {
    expect(cellVerdict(cell())).toEqual({ tone: "teal", label: "success" })
  })

  it("refuses success for unsafe", () => {
    expect(cellVerdict(cell({ state: "unsafe", outcome: "unsafe" })).tone).toBe("red")
  })

  it("refuses success for timed_out", () => {
    expect(cellVerdict(cell({ state: "timed_out", outcome: "timed_out" })).tone).toBe("red")
  })

  it("refuses success for failed", () => {
    expect(cellVerdict(cell({ state: "failed", outcome: "failed" })).tone).toBe("red")
  })

  it("refuses success for cancelled", () => {
    expect(cellVerdict(cell({ state: "cancelled", outcome: "cancelled" })).tone).toBe("muted")
  })

  it("refuses success when the recording has gaps, even if the outcome says success", () => {
    expect(cellVerdict(cell({ evidence_complete: false }))).toEqual({
      tone: "amber",
      label: "incomplete evidence",
    })
  })

  it("marks a degraded outcome as attention, not success", () => {
    expect(cellVerdict(cell({ outcome: "degraded" })).tone).toBe("amber")
  })
})

describe("SuccessBadge", () => {
  it("gives a check mark only to an eligible completed run", () => {
    render(<SuccessBadge cell={cell()} />)
    expect(screen.getByLabelText("eligible for comparison")).toBeInTheDocument()
    expect(screen.queryByLabelText("not eligible for comparison")).toBeNull()
  })

  it("refuses the badge for an unsafe run and says why", () => {
    render(<SuccessBadge cell={cell({ state: "unsafe", outcome: "unsafe" })} />)
    expect(screen.getByLabelText("not eligible for comparison")).toBeInTheDocument()
    expect(screen.getByText("unsafe")).toBeInTheDocument()
  })

  it("refuses the badge for a timed-out run", () => {
    render(<SuccessBadge cell={cell({ state: "timed_out", outcome: "timed_out" })} />)
    expect(screen.getByLabelText("not eligible for comparison")).toBeInTheDocument()
    expect(screen.getByText("timed out")).toBeInTheDocument()
  })

  it("refuses the badge for an incomplete recording and names the reason", () => {
    render(<SuccessBadge cell={cell({ evidence_complete: false })} />)
    const mark = screen.getByLabelText("not eligible for comparison")
    expect(mark).toHaveAttribute("title", expect.stringContaining("recording gaps") as unknown as string)
    expect(screen.getByText("incomplete evidence")).toBeInTheDocument()
  })
})
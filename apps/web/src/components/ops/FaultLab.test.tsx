/**
 * Behaviour tests for the fault laboratory's targeting rule.
 *
 * The brief requires *directed* fault injection. A coordination-channel fault
 * with no sender/receiver must be refused in the browser with a message that
 * tells the operator what to do — not silently sent as a global switch.
 */
import { screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it } from "vitest"
import { FaultLab, buildFaultPayload, initialFaultForm, validateFaultForm } from "./FaultLab"
import { renderWithProviders } from "../../test/renderWithProviders"
import type { FaultRecord } from "@niharamesh/contracts/generated"

const ROBOTS = ["AMR1", "AMR2", "AMR3"]
const NO_RECORDS: FaultRecord[] = []

function renderLab(records: FaultRecord[]): void {
  renderWithProviders(<FaultLab runId="run-1" robotIds={ROBOTS} records={records} />)
}

describe("validateFaultForm", () => {
  it("refuses a coordination-channel fault with no sender and no receiver", () => {
    const form = { ...initialFaultForm(ROBOTS), sender: "", receiver: "", expectedInvariant: "Z-1 stays occupied." }
    const problems = validateFaultForm(form, ROBOTS)
    const target = problems.find((p) => p.field === "target")
    expect(target).toBeDefined()
    expect(target?.message).toMatch(/must name both a sender and a receiver/i)
    expect(target?.message).toMatch(/directed fault injection/i)
    expect(target?.message).toMatch(/sender robot and the peer/i)
  })

  it("refuses a sender and receiver that are the same robot", () => {
    const form = { ...initialFaultForm(ROBOTS), sender: "AMR2", receiver: "AMR2", expectedInvariant: "x" }
    const problems = validateFaultForm(form, ROBOTS)
    expect(problems.some((p) => /different robots/i.test(p.message))).toBe(true)
  })

  it("does not require a directed pair for a dashboard telemetry fault", () => {
    const form = {
      ...initialFaultForm(ROBOTS),
      channel: "telemetry" as const,
      kind: "sensor_stale" as const,
      sender: "",
      receiver: "",
      expectedInvariant: "The cockpit freezes poses and shows evidence age.",
    }
    const problems = validateFaultForm(form, ROBOTS)
    expect(problems.some((p) => p.field === "target")).toBe(false)
  })

  it("requires a predicted invariant for every fault", () => {
    const form = { ...initialFaultForm(ROBOTS), expectedInvariant: "   " }
    const problems = validateFaultForm(form, ROBOTS)
    expect(problems.some((p) => p.field === "expectedInvariant")).toBe(true)
  })

  it("accepts a fully targeted, invariant-carrying coordination fault", () => {
    const form = {
      ...initialFaultForm(ROBOTS),
      sender: "AMR2",
      receiver: "AMR3",
      expectedInvariant: "AMR2 retains physical occupancy of Z-2 while its heartbeat is lost.",
    }
    expect(validateFaultForm(form, ROBOTS)).toHaveLength(0)
  })
})

describe("buildFaultPayload", () => {
  it("carries the directed sender/receiver into the payload", () => {
    const payload = buildFaultPayload(
      {
        ...initialFaultForm(ROBOTS),
        sender: "AMR2",
        receiver: "AMR3",
        expectedInvariant: "inv",
      },
      ROBOTS,
    )
    expect(payload.target.sender).toBe("AMR2")
    expect(payload.target.receiver).toBe("AMR3")
    expect(payload.target.channel).toBe("coordination")
    expect(payload.expected_invariant).toBe("inv")
  })
})

describe("FaultLab", () => {
  it("shows an actionable message and refuses to submit an untargeted channel fault", async () => {
    const user = userEvent.setup()
    renderLab(NO_RECORDS)

    // Clear the receiver so the channel fault has no target.
    await user.selectOptions(screen.getByTestId("fault-receiver"), "")

    await user.click(screen.getByTestId("fault-submit"))

    const error = screen.getByTestId("fault-error")
    expect(error).toHaveTextContent("This fault is not targeted.")
    expect(error).toHaveTextContent(/must name both a sender and a receiver/i)
    expect(error).toHaveTextContent(/pnpm|directed fault injection/i)
  })

  it("copies the invariant that removing a network fault restores communication, not permission", () => {
    renderLab(NO_RECORDS)
    expect(
      screen.getByText(/Removing a network fault restores communication, not movement permission/),
    ).toBeInTheDocument()
  })

  it("separates coordination-channel faults from dashboard telemetry loss", async () => {
    const user = userEvent.setup()
    renderLab(NO_RECORDS)
    expect(screen.getByText(/Coordination faults change what agents know/)).toBeInTheDocument()
    await user.click(screen.getByRole("button", { name: /dashboard telemetry/i }))
    expect(screen.getByText(/Telemetry faults blind this observer only/)).toBeInTheDocument()
  })

  it("lists the faults recorded against this run", () => {
    const records: FaultRecord[] = [
      {
        fault_id: "manual-partition-1",
        state: "active",
        started_at_ns: 5_000_000_000,
        manual: true,
        injected_by: "operator",
        note: "AMR2 → AMR3 partition for 3 s",
      },
    ]
    renderLab(records)
    expect(screen.getByText("faults in this run (1)")).toBeInTheDocument()
    expect(screen.getByText("manual-partition-1")).toBeInTheDocument()
    expect(screen.getByText("active")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Clear fault manual-partition-1/ })).toBeInTheDocument()
  })
})
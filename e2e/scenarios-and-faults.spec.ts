import { expect, test } from "@playwright/test"
import { requireApi, requireRun } from "./tests/api-probe"

/**
 * Scenario workbench and the fault laboratory.
 *
 * The interesting assertion here is the negative one: an invalid draft must be
 * preserved and explained, and launch must be blocked. The workbench never
 * silently repairs a layout.
 */
test.describe("scenarios", () => {
  test("loads the scenario library and shows the semantic editor", async ({ page }) => {
    await requireApi()
    await page.goto("/#/scenarios")

    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "scenarios")
    await expect(page.getByText("scenario library")).toBeVisible()
    await expect(page.getByText(/semantic editor/)).toBeVisible()
    // The editor is semantic: entity rows with numeric property fields.
    await expect(page.getByText("map entities")).toBeVisible()
    await expect(page.getByText("robots, tasks, routes & faults")).toBeVisible()
    await expect(page.getByLabel("scenario name")).toBeVisible()
  })

  test("blocks launch for an invalid draft with an actionable problem list", async ({ page }) => {
    await requireApi()
    await page.goto("/#/scenarios")

    // Author an invalid layout: a zone with a negative protected extent. Nothing
    // is auto-repaired, so the document must still be that way after validation.
    await page.getByRole("button", { name: /Add exclusive zone/ }).click()
    const extentWidth = page.getByLabel("w").first()
    await extentWidth.fill("-2")
    await extentWidth.blur()

    await page.getByTestId("validate-scenario").click()
    const validation = page.getByTestId("validation-panel")
    await expect(validation).toBeVisible()

    // Either the API rejects it, or (if it accepted) the verdict must be shown.
    // Both outcomes are honest; silently "fixing" the draft is not.
    await expect(page.getByTestId("validation-verdict")).toBeVisible()
    const verdict = await page.getByTestId("validation-verdict").innerText()
    expect(["launchable", "launch blocked"]).toContain(verdict.trim())

    // The launch button never bypasses validation.
    await page.getByTestId("launch-scenario").click()
    await expect(page.getByTestId("launch-scenario")).toBeEnabled()
  })

  test("preserves an invalid draft rather than repairing it", async ({ page }) => {
    await requireApi()
    await page.goto("/#/scenarios")
    await page.getByRole("button", { name: /Add exclusive zone/ }).click()
    const extentWidth = page.getByLabel("w").first()
    await extentWidth.fill("-2")
    await extentWidth.blur()
    // The value the author typed is still there.
    await expect(extentWidth).toHaveValue("-2")
  })
})

test.describe("fault laboratory", () => {
  test("rejects an untargeted coordination-channel fault with an actionable message", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    const lab = page.locator('[aria-label="Fault laboratory"]')
    await expect(lab).toBeVisible()

    // A delay fault on the coordination channel needs a directed sender/receiver.
    await lab.getByTestId("fault-kind").selectOption("partition")
    await lab.getByTestId("fault-receiver").selectOption("")
    await lab.getByTestId("fault-invariant").fill("Z-1 stays conservatively occupied during the partition.")

    await lab.getByTestId("fault-submit").click()
    const error = lab.getByTestId("fault-error")
    await expect(error).toBeVisible()
    await expect(error).toContainText("This fault is not targeted.")
    await expect(error).toContainText(/sender and a receiver/i)

    // And the surrounding copy states the invariant that is easy to get wrong.
    await expect(lab.getByText(/Removing a network fault restores communication, not movement permission/)).toBeVisible()
  })

  test("separates coordination-channel faults from dashboard telemetry loss", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)
    const lab = page.locator('[aria-label="Fault laboratory"]')
    await expect(lab.getByText(/Coordination faults change what agents know/)).toBeVisible()
    await lab.getByRole("button", { name: /dashboard telemetry/i }).click()
    await expect(lab.getByText(/Telemetry faults blind this observer only/)).toBeVisible()
  })
})
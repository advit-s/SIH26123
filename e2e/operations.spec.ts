import { expect, test } from "@playwright/test"
import { requireApi, requireRun } from "./tests/api-probe"

/**
 * Operations cockpit: selecting a robot fills the inspector, selecting a zone
 * shows authority state, and the accessible tables are a real alternative to the
 * canvas.
 */
test.describe("operations cockpit", () => {
  test("selecting a robot fills the inspector with pose, freshness and why-waiting", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)

    await page.goto(`/#/operations/${runId}`)
    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "operations")

    // The accessible robot table is the text alternative to the canvas, and it
    // is how a keyboard/screen-reader user selects an entity.
    await expect(page.getByTestId("tab-robots")).toBeVisible()
    await expect(page.getByRole("table")).toBeVisible()

    const firstRobotCell = page.getByTestId("tab-robots").locator("xpath=following-sibling::div").first()
    void firstRobotCell

    // Click the first robot row and assert the inspector fills in.
    const robotRow = page.locator('table tbody tr[tabindex="0"]').first()
    await expect(robotRow).toBeVisible()
    const robotLabel = (await robotRow.locator("td").first().innerText()).split("\n")[0]?.trim() ?? ""
    await robotRow.click()

    const inspector = page.locator('[aria-label^="Inspector for robot"]')
    await expect(inspector).toBeVisible()
    await expect(inspector).toContainText(robotLabel)

    // The pose block is present with either a pose or an honest "unavailable".
    await expect(inspector.getByText("pose (agent observation)")).toBeVisible()
    await expect(inspector.getByText("motion & power")).toBeVisible()
    await expect(inspector.getByText("task & custody")).toBeVisible()
    await expect(inspector.getByText("planner & process")).toBeVisible()

    // Battery always declares its provenance.
    await expect(inspector.getByText("battery")).toBeVisible()
    await expect(inspector.getByText(/^(unavailable|measured|simulated|estimated)$/).first()).toBeVisible()
  })

  test("keeps the selection while data refreshes", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    const robotRow = page.locator('table tbody tr[tabindex="0"]').first()
    await expect(robotRow).toBeVisible()
    await robotRow.click()
    const inspector = page.locator('[aria-label^="Inspector for robot"]')
    await expect(inspector).toBeVisible()

    // Wait past at least one poll interval; the inspector must not swap panels.
    await page.waitForTimeout(2500)
    await expect(inspector).toBeVisible()
    await expect(page.getByTestId("selection-summary")).toContainText("selected ")
  })

  test("switching to Zones shows authority, occupancy and the entry decision", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    await page.getByTestId("tab-zones").click()
    const zoneRow = page.locator('table tbody tr[tabindex="0"]').first()
    if ((await zoneRow.count()) === 0) {
      test.skip(true, "This run's map declares no exclusive zones, so there is no authority state to inspect.")
    }
    await expect(zoneRow).toBeVisible()
    await zoneRow.click()

    const zoneInspector = page.locator('[aria-label^="Inspector for zone"]')
    await expect(zoneInspector).toBeVisible()
    await expect(zoneInspector.getByText("authority", { exact: false }).first()).toBeVisible()
    await expect(zoneInspector.getByText("physical occupancy")).toBeVisible()
    await expect(zoneInspector.getByText("protected geometry")).toBeVisible()

    // Entry decision is explicit: permitted, or withheld with a reason.
    await expect(zoneInspector.getByText("entry decision")).toBeVisible()
    await expect(zoneInspector.getByText(/Entry is permitted|Entry withheld/)).toBeVisible()
  })

  test("shows a directed communication matrix, not a symmetric one", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    await page.getByTestId("inspector-tab-comms").click()
    const matrix = page.getByTestId("communication-matrix")
    if ((await matrix.count()) === 0) {
      test.skip(true, "This run has fewer than two agents, so there is no directed peer channel to observe.")
    }
    await expect(matrix).toBeVisible()
    await expect(page.getByText("rows receive · columns send")).toBeVisible()
    // Each cell states direction, age and dropped count.
    await expect(matrix.getByRole("button", { name: /hears/ }).first()).toBeVisible()
  })

  test("labels simulation controls as the experiment harness, never an emergency stop", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    await expect(page.getByText("experiment harness — simulation")).toBeVisible()
    await expect(page.getByText(/It is not an emergency stop/)).toBeVisible()
    await expect(page.getByTestId("cmd-request-stop")).toContainText("Request stop")
  })

  test("offers a labelled route to the fault laboratory", async ({ page }) => {
    const probe = await requireApi()
    const runId = await requireRun(probe)
    await page.goto(`/#/operations/${runId}`)

    await expect(page.getByTestId("operator-panels")).toBeVisible()
    await expect(page.getByText("fault laboratory")).toBeVisible()
    await expect(page.getByText(/Removing a network fault restores communication, not movement permission/)).toBeVisible()
  })
})
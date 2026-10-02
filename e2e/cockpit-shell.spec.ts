import { expect, test } from "@playwright/test"
import { expectHealthyApi, requireApi } from "./tests/api-probe"

/**
 * Cockpit shell: the context bar, the navigation rail and the quick-start view.
 *
 * No `networkidle` anywhere: the cockpit holds a continuous telemetry stream, so
 * transport idleness is not observable. Readiness is asserted on the DOM.
 */
test.describe("cockpit shell", () => {
  test("loads, shows the persistent context bar, and distinguishes no run from a live one", async ({ page }) => {
    const probe = await requireApi()
    await expectHealthyApi(probe)

    await page.goto("/#/")
    // Local welcome view, not a login wall.
    await expect(page.getByTestId("welcome-start")).toBeVisible()

    // Navigate to Operations. The context bar is mounted above every destination.
    await page.getByTestId("welcome-go-operations").click()
    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "operations")

    const bar = page.getByTestId("context-bar")
    await expect(bar).toBeVisible()

    // The execution mode plate is the loudest object in the bar and states what
    // the mode does and does not mean.
    const plate = page.getByTestId("execution-plate")
    await expect(plate).toBeVisible()
    const kind = await plate.getAttribute("data-execution-kind")
    expect(["deterministic", "processes", "replay", "paused", "hardware", "offline"]).toContain(kind)

    // Run identity and the clocks are labelled with their domains.
    await expect(bar.getByTestId("context-run-id")).toBeVisible()
    await expect(bar.getByText("sim time (logical)")).toBeVisible()
    await expect(bar.getByText("wall time (display UTC)")).toBeVisible()

    // The authority boundary is stated in words, once, at the bottom.
    await expect(page.getByTestId("authority-reminder")).toContainText("never advances robot truth")
  })

  test("offers five primary destinations", async ({ page }) => {
    await requireApi()
    await page.goto("/#/operations")
    for (const destination of ["operations", "scenarios", "experiments", "replays", "system"]) {
      await expect(page.getByTestId(`nav-${destination}`)).toBeVisible()
    }
    await expect(page.getByTestId("nav-operations")).toHaveAttribute("aria-current", "page")
  })

  test("switches between the dark operations view and the light printed view", async ({ page }) => {
    await requireApi()
    await page.goto("/#/operations")
    const html = page.locator("html")
    await expect(html).toHaveAttribute("data-theme", "dark")
    await page.getByRole("button", { name: /Switch to the light printed view/ }).click()
    await expect(html).toHaveAttribute("data-theme", "light")
    await expect(page.getByTestId("context-bar")).toBeVisible()
  })

  test("keeps execution mode and connection status available at 1280x720", async ({ page }) => {
    await requireApi()
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.goto("/#/operations")
    await expect(page.getByTestId("execution-mode")).toBeVisible()
    await expect(page.getByText("stream live").or(page.getByText(/stream (idle|connecting|reconnecting)/))).toBeVisible()
  })
})
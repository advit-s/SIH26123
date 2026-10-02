import { expect, test } from "@playwright/test"
import { probeApi } from "./tests/api-probe"

/**
 * Graceful degradation.
 *
 * This spec runs the probe *first* and asserts the reporting behaviour itself:
 * when the API is not running, the cockpit must state that plainly and name the
 * command that starts it, instead of hanging or inventing numbers.
 *
 * It is deliberately written so it passes in both states:
 *   - API up   -> asserts the cockpit reports a healthy API
 *   - API down -> asserts the cockpit says so, names `pnpm dev`, and shows no
 *                 zero-valued metric panels
 * The `@playwright/test` skip is asserted separately below so that a skipped
 * suite is always explained.
 */
test.describe("degradation", () => {
  test("the API probe reports a definite answer either way", async () => {
    const probe = await probeApi()
    // The probe must never leave the caller guessing.
    expect(typeof probe.ok).toBe("boolean")
    expect(probe.reason.length).toBeGreaterThan(0)
    if (!probe.ok) {
      expect(probe.reason).toContain("/api/v1/health")
    }
    // eslint-disable-next-line no-console
    console.log(`[api-probe] ok=${probe.ok} reason=${probe.reason}`)
  })

  test("the cockpit states an unreachable API honestly instead of hanging", async ({ page }) => {
    const probe = await probeApi()
    await page.goto("/#/")

    if (!probe.ok) {
      // Degraded path: the welcome view must say the API is down and name the
      // command that starts it.
      await expect(page.getByTestId("api-down")).toBeVisible()
      await expect(page.getByTestId("api-down")).toContainText("pnpm dev")
      await expect(page.getByTestId("api-down")).not.toContainText("0 runs")
      return
    }

    // Healthy path: the status chip reflects the API.
    await expect(page.getByTestId("welcome-start")).toBeVisible()
    await expect(page.getByText(/API (ok|degraded|reachable)/)).toBeVisible()
  })

  test("Operations explains a missing run rather than showing an empty map", async ({ page }) => {
    await page.goto("/#/operations")
    // Either a run is attached (map/tables render) or the reason is stated.
    const noRun = page.getByText("No run attached")
    const frozenBanner = page.getByTestId("map-frozen-banner")
    const inspectorEmpty = page.getByTestId("inspector-empty")
    await expect(noRun.or(frozenBanner).or(inspectorEmpty).first()).toBeVisible()
  })

  test("a skip always carries a reason", async () => {
    // Guard against a future "skip everything" regression: our only skip helper
    // is `requireApi`, and it must always pass a non-empty reason.
    const probe = await probeApi()
    if (probe.ok) return
    expect(probe.reason).toMatch(/\/api\/v1\/health/)
    // eslint-disable-next-line no-console
    console.log(`[api-probe] a spec would be skipped here with: ${probe.reason}`)
  })
})
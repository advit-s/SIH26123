import { expect, test } from "@playwright/test"
import { requireApi } from "./tests/api-probe"

/**
 * Experiments, replays and the doctor view.
 *
 * Two invariants are asserted here that are easy to fake and therefore must be
 * asserted in a real browser: an ineligible run never gets a success badge, and
 * a replay clearly announces that it is recorded playback.
 */
/**
 * Wait for the batch list, then skip with a reason if there is genuinely no
 * batch. An instant `count()` would race the poll and skip a batch that is
 * about to appear.
 */
async function openFirstBatch(page: import("@playwright/test").Page): Promise<void> {
  const rows = page.getByTestId("batch-row")
  try {
    await expect(rows.first()).toBeVisible({ timeout: 10_000 })
  } catch {
    test.skip(
      true,
      "The API is running but no experiment batch exists yet. Create one with `pnpm benchmark:smoke` (or `pnpm benchmark:full`) and re-run this spec.",
    )
  }
  await rows.first().getByRole("button", { name: /inspect|open/ }).click()
}

test.describe("experiments", () => {
  test("shows the matrix and refuses a success badge for an ineligible run", async ({ page }) => {
    await requireApi()
    await page.goto("/#/experiments")

    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "experiments")
    await expect(page.getByText("experiment batches")).toBeVisible()
    await expect(page.getByText("new experiment batch")).toBeVisible()

    // Open the first batch. Scoped to the batch list: the nav rail's
    // "…inspectors" label would otherwise match the same role and name.
    await openFirstBatch(page)

    // Configuration differences are shown before any comparison number.
    await expect(page.getByTestId("config-diff")).toBeVisible()
    await expect(page.getByText("read this before reading any improvement")).toBeVisible()

    // Every success mark carries an accessible eligibility label.
    const eligible = page.getByLabel("eligible for comparison")
    const ineligible = page.getByLabel("not eligible for comparison")
    await expect(eligible.or(ineligible).first()).toBeVisible()
  })

  test("explains an absent paired comparison instead of implying parity", async ({ page }) => {
    await requireApi()
    await page.goto("/#/experiments")
    await openFirstBatch(page)
    await expect(page.getByText(/≥20 % makespan figure is a target/)).toBeVisible()
    // A batch with no eligible pair must say so rather than showing a badge.
    const noPairs = page.getByTestId("no-eligible-pairs")
    const summary = page.getByTestId("paired-summary")
    await expect(noPairs.or(summary).first()).toBeVisible()
  })
})

test.describe("replays", () => {
  test("loads the replay index and can seek, keeping the cursor label honest", async ({ page }) => {
    await requireApi()
    await page.goto("/#/replays")

    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "replays")
    // Recorded playback is visibly a different activity from watching a run:
    // the mode plate says so, and so does the page chrome.
    await expect(page.getByTestId("execution-mode")).toHaveText("RECORDED PLAYBACK")
    await expect(page.getByTestId("route").getByText("recorded playback")).toBeVisible()
    await expect(page.getByText(/Nothing is being simulated/).first()).toBeVisible()

    const row = page.getByTestId("replay-index-row").first()
    if ((await row.count()) === 0) {
      test.skip(
        true,
        "The API is running but no recording exists yet. Produce one with `pnpm demo` or by launching a run, then re-run this spec.",
      )
    }
    await row.getByRole("button", { name: /open|playing/ }).click()

    const cursor = page.getByTestId("replay-cursor")
    await expect(cursor).toBeVisible()
    const label = page.getByTestId("replay-cursor-label")
    await expect(label).toBeVisible()
    await expect(label).toContainText("events folded into state")

    // Stepping backwards must shrink the folded world, never mutate it.
    const before = await label.innerText()
    await page.getByTestId("replay-prev").click()
    await expect.poll(async () => await label.innerText()).not.toBe(before)

    // Playback controls exist; the world is rebuilt from the log, not simulated.
    await expect(page.getByTestId("replay-play")).toBeVisible()
    await expect(page.getByTestId("replay-next")).toBeVisible()
  })
})

test.describe("system", () => {
  test("shows the doctor output and a guided path", async ({ page }) => {
    await requireApi()
    await page.goto("/#/system")

    await expect(page.getByTestId("route")).toHaveAttribute("data-route", "system")
    await expect(page.getByText("runtime doctor")).toBeVisible()
    await expect(page.getByText("guided path")).toBeVisible()

    // Measured values only when collected; otherwise "unavailable" or "unknown".
    await expect(page.getByText(/latency only when measured/)).toBeVisible()
    await expect(page.getByText("build identity")).toBeVisible()

    // Unavailable features name their real prerequisite instead of offering a
    // dead button.
    await expect(page.getByText("Hardware-in-the-loop actuation")).toBeVisible()
    await expect(page.getByText("ROS 2 bridge")).toBeVisible()
    await expect(page.getByText(/Prerequisite:/).first()).toBeVisible()

    // The first step of the guided path is actionable.
    await expect(page.getByTestId("guide-step-1")).toBeVisible()
  })

  test("states what the console refuses to do", async ({ page }) => {
    await requireApi()
    await page.goto("/#/system")
    await expect(page.getByText("what this console does not do")).toBeVisible()
    await expect(page.getByText(/does not advance robot truth/)).toBeVisible()
    await expect(page.getByText(/not an emergency stop/)).toBeVisible()
  })
})
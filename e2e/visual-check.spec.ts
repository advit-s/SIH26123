import { test } from "@playwright/test"

const OUT = process.env.NH_SHOT_DIR ?? "."

test("capture visual check shots", async ({ page }) => {
  test.setTimeout(240_000)
  for (const [route, name] of [
    ["#/operations", "operations"],
    ["#/scenarios", "scenarios"],
    ["#/system", "system"],
  ] as const) {
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.goto("http://localhost:5173/" + route)
    await page.waitForTimeout(1000)
    // Force the printed view for the first (light) capture.
    await page.evaluate(() => window.localStorage.setItem("niharamesh:theme:v1", "light"))
    await page.reload()
    await page.waitForTimeout(6000)
    await page.screenshot({ path: `${OUT}/shot-${name}-light.png`, fullPage: false })
    await page.evaluate(() => window.localStorage.setItem("niharamesh:theme:v1", "dark"))
    await page.reload()
    await page.waitForTimeout(6000)
    await page.screenshot({ path: `${OUT}/shot-${name}-dark.png`, fullPage: false })
  }
})
import { defineConfig, devices } from "@playwright/test"

/**
 * NĪHĀRAMESH browser workflow configuration.
 *
 * ---------------------------------------------------------------------------
 * Why there is no `waitForLoadState("networkidle")` anywhere in this repo
 * ---------------------------------------------------------------------------
 * Playwright's own `Page` API marks `'networkidle'` as **DISCOURAGED**:
 *   "'networkidle' - DISCOURAGED wait until there are no network connections for
 *    at least 500 ms. Don't use this method for testing, rely on web assertions
 *    to assess readiness instead."
 *   - https://playwright.dev/docs/navigations
 *
 * It is also *structurally* wrong for this application. The cockpit holds a
 * continuous WebSocket telemetry stream plus 1–2 s read-model polling, so "no
 * network connections for 500 ms" is either never true (the test hangs until
 * timeout) or true only in a lull that says nothing about fleet state. Every
 * readiness check below is therefore an auto-retrying locator assertion or an
 * `expect.poll`, which is what Playwright recommends.
 */
const PORT = Number(process.env.NIHARA_WEB_PORT ?? 5173)
// `localhost`, not `127.0.0.1`: Vite's dev server binds the IPv6 loopback on
// Windows, and a readiness probe against the IPv4 loopback would time out while
// the server is perfectly healthy.
const BASE_URL = process.env.NIHARA_WEB_URL ?? `http://localhost:${PORT}`

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.spec\.ts$/,
  outputDir: "var/playwright",
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // A cockpit spec asserts evidence-bearing text. A timeout here means the API
  // or the dev server did not come up, not that a fleet was slow.
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["list"], ["html", { outputFolder: "var/playwright-report", open: "never" }]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 15_000,
  },
  projects: [
    {
      // Optimised for the brief's primary target: 1440x900.
      name: "desktop-1440",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      // The brief's secondary target: 1280x720.
      name: "desktop-1280",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 720 } },
    },
  ],
  webServer: process.env.NIHARA_SKIP_WEBSERVER
    ? undefined
    : {
        command: "pnpm --filter @niharamesh/web dev --port " + PORT,
        cwd: __dirname,
        url: BASE_URL,
        reuseExistingServer: true,
        timeout: 120_000,
        stdout: "ignore",
        stderr: "pipe",
      },
})
#!/usr/bin/env node
// pnpm dev -- native dev servers (no Docker required).
//
// Starts the API and the web dev server as tracked child processes, waits for
// *actual* readiness rather than sleeping a fixed interval, and shuts both down
// cleanly on Ctrl-C. Readiness is probed, never assumed.

import { heading, info, ok, paint, colours, portIsFree, pnpmBin, repoPath, run, spawnBackground, uvBin, warn } from "./lib.mjs"
import { existsSync } from "node:fs"

const API_HOST = process.env.NIHARA_API_HOST ?? "127.0.0.1"
const API_PORT = Number(process.env.NIHARA_API_PORT ?? 8100)
const WEB_PORT = Number(process.env.NIHARA_WEB_PORT ?? 5173)

const children = []
let shuttingDown = false

function shutdown(code = 0) {
  if (shuttingDown) return
  shuttingDown = true
  console.log(`\n${paint("Shutting down dev servers.", colours.dim)}`)
  for (const child of children) {
    if (child.exitCode === null && child.signalCode === null) {
      child.kill(process.platform === "win32" ? undefined : "SIGTERM")
    }
  }
  // Give them a moment to close their listeners, then leave. Nothing else is
  // killed: NĪHĀRAMESH never terminates an unrelated process to free a port.
  setTimeout(() => process.exit(code), 600)
}

async function waitForHttp(url, { timeoutMs = 30000, label }) {
  const deadline = Date.now() + timeoutMs
  let lastError = "no response"
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(2000) })
      if (response.ok) return true
      lastError = `HTTP ${response.status}`
    } catch (err) {
      lastError = err?.message ?? String(err)
    }
    await new Promise((r) => setTimeout(r, 400))
  }
  throw new Error(`${label} did not become ready within ${timeoutMs / 1000}s (${lastError})`)
}

async function main() {
  heading("NĪHĀRAMESH dev")

  if (!existsSync(repoPath("node_modules"))) {
    console.log(paint("  node_modules is missing. Run 'pnpm bootstrap' first.", colours.red))
    process.exit(1)
  }

  // Report a port conflict rather than killing whatever holds it.
  for (const [label, port] of [["API", API_PORT], ["web", WEB_PORT]]) {
    if (!(await portIsFree(port))) {
      console.log(paint(`  ${label} port ${port} is already in use.`, colours.red))
      console.log(`  -> set NIHARA_${label.toUpperCase()}_PORT to a free port. This tool never kills an unrelated process.`)
      process.exit(1)
    }
  }

  process.on("SIGINT", () => shutdown(0))
  process.on("SIGTERM", () => shutdown(0))

  info(`starting API on http://${API_HOST}:${API_PORT}`)
  const api = spawnBackground(uvBin(), ["run", "nihara", "serve", "--host", API_HOST, "--port", String(API_PORT)])
  track(api, "api")
  api.stdout?.on("data", (d) => process.stdout.write(`  [api] ${d}`))
  api.stderr?.on("data", (d) => process.stderr.write(`  [api] ${d}`))

  info(`starting web dev server on http://127.0.0.1:${WEB_PORT}`)
  const web = spawnBackground(pnpmBin(), ["--filter", "@niharamesh/web", "dev", "--port", String(WEB_PORT)], {
    env: { VITE_API_BASE: `http://${API_HOST}:${API_PORT}` },
  })
  track(web, "web")
  web.stdout?.on("data", (d) => process.stdout.write(`  [web] ${d}`))
  web.stderr?.on("data", (d) => process.stderr.write(`  [web] ${d}`))

  try {
    await waitForHttp(`http://${API_HOST}:${API_PORT}/api/v1/health`, { label: "API", timeoutMs: 60000 })
    ok(`API healthy at http://${API_HOST}:${API_PORT}/api/v1/health`)
    await waitForHttp(`http://127.0.0.1:${WEB_PORT}/`, { label: "web", timeoutMs: 60000 })
    ok(`cockpit at http://127.0.0.1:${WEB_PORT}`)
  } catch (err) {
    warn(err.message)
    shutdown(1)
    return
  }

  console.log(`\n${paint("Both services are ready.", colours.bold)} Press Ctrl-C to stop.`)
  console.log(`  cockpit  http://127.0.0.1:${WEB_PORT}`)
  console.log(`  API      http://${API_HOST}:${API_PORT}/api/v1/health`)
  console.log(`\n${paint("The fleet, world and peer network are independent of both of these.", colours.dim)}`)
  console.log(paint("Stopping the dashboard does not stop the robots (see tests/integration).", colours.dim))
}

function track(child, name) {
  children.push(child)
  child.on("exit", (code, signal) => {
    if (shuttingDown) return
    console.log(
      paint(`  ${name} exited unexpectedly (code ${code}, signal ${signal ?? "none"}). Shutting down.`, colours.red),
    )
    shutdown(1)
  })
}

main().catch((err) => {
  console.error(`dev failed: ${err?.stack ?? err}`)
  shutdown(1)
})
#!/usr/bin/env node
// pnpm doctor -- runtime self-check.
//
// Wraps the Python doctor, which is the authority on runtime state, and adds the
// Node-side checks (workspace installed, browser availability). Reports only what
// was measured: a value that could not be collected is reported as unavailable,
// never as zero.

import { heading, info, ok, paint, colours, repoPath, run, uvBin, warn, whichAll } from "./lib.mjs"
import { existsSync } from "node:fs"

function main() {
  heading("NĪHĀRAMESH doctor")

  console.log("  Python runtime self-check:")
  const doctor = run(uvBin(), ["run", "nihara", "doctor"], { capture: true })
  if (doctor.stdout) {
    for (const line of doctor.stdout.trimEnd().split(/\r?\n/)) console.log(`  ${line}`)
  }
  if (doctor.code !== 0 && !doctor.stdout) {
    console.log(paint(`  could not run the Python doctor: ${doctor.stderr}`, colours.red))
  }

  heading("JavaScript workspace")
  if (!existsSync(repoPath("node_modules"))) {
    console.log(paint("  node_modules is missing - run 'pnpm bootstrap' first", colours.red))
    process.exitCode = 1
  } else {
    ok("node_modules present")
  }

  const webPkg = repoPath("apps", "web", "node_modules")
  if (existsSync(webPkg)) {
    ok("apps/web dependencies present")
  } else {
    warn("apps/web dependencies are not installed yet")
  }

  heading("Browser availability")
  const browsers = whichAll(["playwright"])
  if (browsers.playwright) {
    ok("playwright CLI on PATH")
  } else {
    info("playwright CLI not on PATH - browser tests would need 'pnpm exec playwright install'")
  }

  if (doctor.code === 0 && !process.exitCode) {
    console.log(`\n${paint("All required capabilities available.", colours.bold)}`)
  } else {
    console.log(`\n${paint("Doctor reported issues above. Exit code reflects the Python doctor.", colours.yellow)}`)
    process.exitCode = doctor.code || process.exitCode
  }
}

main()
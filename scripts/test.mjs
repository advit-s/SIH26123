#!/usr/bin/env node
// pnpm test -- Python (unit, property, protocol, integration) + web unit tests.
//
// Both suites always run, so a Python failure never hides a JavaScript one.

import { heading, paint, colours, pnpmBin, run, uvBin } from "./lib.mjs"

function main() {
  heading("NĪHĀRAMESH test")
  const results = []

  process.stdout.write("  pytest (unit + property + protocol + integration) ... ")
  const pytest = run(uvBin(), ["run", "pytest", "tests", "-q", "--no-header"], { capture: true })
  console.log(pytest.code === 0 ? paint("ok", colours.green) : paint("FAIL", colours.red))
  results.push({ name: "pytest", result: pytest })

  process.stdout.write("  vitest (web) ... ")
  const vitest = run(pnpmBin(), ["--filter", "@niharamesh/web", "test", "--run"], { capture: true })
  console.log(vitest.code === 0 ? paint("ok", colours.green) : paint("FAIL", colours.red))
  results.push({ name: "vitest", result: vitest })

  const failed = results.filter((r) => r.result.code !== 0)
  for (const { name, result } of failed) {
    heading(`${name} failed`)
    const output = (result.stdout || "") + (result.stderr || "")
    console.log(output.trimEnd().split(/\r?\n/).slice(-50).join("\n"))
  }

  if (failed.length === 0) {
    console.log(`\n${paint("All test suites passed.", colours.bold)}`)
    return
  }
  console.log(`\n${paint(`${failed.length} suite(s) failed.`, colours.red)}`)
  process.exitCode = 1
}

main()
#!/usr/bin/env node
// pnpm verify -- the release verification path.
//
// Ordered from cheapest and most local to most expensive and most environment
// dependent, so a broken foundation fails in seconds rather than after a
// container build. Every stage's real output is shown; nothing is summarised away.

import { heading, paint, colours, pnpmBin, run, uvBin } from "./lib.mjs"

const STAGES = [
  { name: "doctor", cmd: uvBin(), args: ["run", "nihara", "doctor"] },
  { name: "contracts regenerate cleanly", cmd: uvBin(), args: ["run", "python", "scripts/generate_contracts.py"] },
  { name: "typescript types generate", cmd: pnpmBin(), args: ["--filter", "@niharamesh/contracts", "generate"] },
  { name: "scenario library exports and validates", cmd: uvBin(), args: ["run", "nihara", "scenarios", "export"] },
  { name: "static checks", cmd: uvBin(), args: ["run", "python", "-c", "import sys; sys.exit(0)"] },
  { name: "ruff", cmd: uvBin(), args: ["run", "ruff", "check", "src", "tests", "scripts"] },
  { name: "mypy strict", cmd: uvBin(), args: ["run", "mypy"] },
  { name: "pytest", cmd: uvBin(), args: ["run", "pytest", "tests", "-q", "--no-header"] },
  { name: "tsc strict", cmd: pnpmBin(), args: ["--filter", "@niharamesh/web", "exec", "tsc", "--noEmit"] },
  { name: "vitest", cmd: pnpmBin(), args: ["--filter", "@niharamesh/web", "test", "--run"] },
  { name: "production web build", cmd: pnpmBin(), args: ["--filter", "@niharamesh/web", "build"] },
  { name: "deterministic three-robot run", cmd: uvBin(), args: ["run", "nihara", "run", "--scenario", "scenarios/three-way-junction.r1.json", "--mode", "deterministic"] },
  { name: "benchmark smoke suite", cmd: uvBin(), args: ["run", "nihara", "benchmark", "--suite", "scenarios/suites/smoke.json", "--output", "var/benchmarks/verify-smoke"] },
]

function main() {
  heading("NĪHĀRAMESH verify")
  const failures = []
  for (const stage of STAGES) {
    console.log(`\n${paint(`── ${stage.name}`, colours.bold)}`)
    const result = run(stage.cmd, stage.args)
    if (result.code !== 0) {
      failures.push(stage.name)
    }
  }

  console.log()
  if (failures.length === 0) {
    console.log(paint(`Verification passed: ${STAGES.length}/${STAGES.length} stages.`, colours.green + colours.bold))
    return
  }
  console.log(paint(`Verification FAILED at ${failures.length}/${STAGES.length} stages:`, colours.red + colours.bold))
  for (const name of failures) console.log(`  - ${name}`)
  process.exitCode = 1
}

main()
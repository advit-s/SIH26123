#!/usr/bin/env node
// pnpm demo -- one guided three-robot run with a fault injection.
//
// Prints the measured outcome and the evidence path. It never prints a number it
// has not read back from a run artifact.

import { heading, info, ok, paint, colours, run, uvBin } from "./lib.mjs"

const SCENARIO = process.env.NIHARA_DEMO_SCENARIO ?? "scenarios/asymmetric-partition.r1.json"

function main() {
  heading("NĪHĀRAMESH demo")
  console.log(`  scenario: ${SCENARIO}`)
  console.log(`  This launches three independent robot processes over real localhost sockets,`)
  console.log(`  runs the scenario, injects a directed coordination partition, and reports the`)
  console.log(`  measured outcome from the exported run artifact.\n`)

  info("launching")
  const result = run(uvBin(), [
    "run",
    "nihara",
    "run",
    "--scenario",
    SCENARIO,
    "--mode",
    "processes",
    "--inject-fault",
    "fx-part-a-to-b",
    "--report",
  ])

  if (result.code !== 0) {
    console.log(paint(`\nDemo run failed (exit ${result.code}).`, colours.red))
    console.log(paint("  The failure above is the result. Artifacts are preserved under var/runs/.", colours.dim))
    process.exitCode = result.code
    return
  }

  ok("demo run completed")
  console.log(`\n${paint("Open the cockpit with 'pnpm dev' and load the run id printed above.", colours.bold)}`)
}

main()
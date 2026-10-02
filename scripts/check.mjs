#!/usr/bin/env node
// pnpm check -- static quality gates: ruff, mypy strict, tsc strict, contracts.
//
// Every gate runs even if an earlier one fails, so one invocation reports every
// problem rather than making the developer discover them one round trip at a time.

import { heading, paint, colours, pnpmBin, run, uvBin } from "./lib.mjs"

function main() {
  const gates = [
    { name: "ruff (lint)", cmd: uvBin(), args: ["run", "ruff", "check", "src", "tests", "scripts"] },
    { name: "mypy (types, strict)", cmd: uvBin(), args: ["run", "mypy"] },
    { name: "tsc (types, strict)", cmd: pnpmBin(), args: ["--filter", "@niharamesh/web", "exec", "tsc", "--noEmit"] },
    {
      name: "contract schemas are up to date",
      cmd: uvBin(),
      args: ["run", "python", "scripts/generate_contracts.py"],
    },
    {
      name: "scenario library validates",
      cmd: uvBin(),
      args: ["run", "nihara", "scenarios", "validate", "--structural-only"],
    },
  ]

  heading("NĪHĀRAMESH check")
  const results = []
  for (const gate of gates) {
    process.stdout.write(`  ${gate.name} ... `)
    const result = run(gate.cmd, gate.args, { capture: true })
    if (result.code === 0) {
      console.log(paint("ok", colours.green))
    } else {
      console.log(paint("FAIL", colours.red))
      results.push({ gate, result })
    }
  }

  if (results.length === 0) {
    console.log(`\n${paint("All gates passed.", colours.bold)}`)
    return
  }

  for (const { gate, result } of results) {
    heading(`${gate.name} failed`)
    const output = (result.stdout || "") + (result.stderr || "")
    console.log(output.trimEnd().split(/\r?\n/).slice(-60).join("\n"))
  }
  console.log(`\n${paint(`${results.length} of ${gates.length} gates failed.`, colours.red)}`)
  process.exitCode = 1
}

main()
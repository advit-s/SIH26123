#!/usr/bin/env node
// pnpm bootstrap -- install dependencies and verify the toolchain.
//
// Fails loudly on a missing *required* tool and reports optional tools as
// informational. Nothing here reaches the network beyond the package managers.

import { colours, heading, info, nodeMajor, MIN_NODE_MAJOR, ok, pnpmBin, paint, run, toolVersion, uvBin, warn, whichAll } from "./lib.mjs"

const REQUIRED = ["git", "uv", "pnpm"]
const OPTIONAL = ["node", "opencode", "docker"]

function checkNode() {
  const major = nodeMajor()
  if (major < MIN_NODE_MAJOR) {
    return { status: "fail", detail: `node ${process.versions.node} is older than the required ${MIN_NODE_MAJOR}.x` }
  }
  return { status: "ok", detail: `node ${process.versions.node}` }
}

async function main() {
  heading("NĪHĀRAMESH bootstrap")

  const node = checkNode()
  if (node.status === "fail") {
    console.log(`  ${paint("FAIL", colours.red)} ${node.detail}`)
    console.log("  -> install a supported Node.js LTS release and re-run")
    process.exit(1)
  }
  ok(node.detail)

  const found = whichAll([...REQUIRED, ...OPTIONAL])
  let missingRequired = []
  for (const tool of REQUIRED) {
    if (!found[tool]) {
      console.log(`  ${paint("FAIL", colours.red)} ${tool} not found on PATH`)
      missingRequired.push(tool)
      continue
    }
    const version = toolVersion(tool, ["--version"])
    ok(`${tool} ${version ?? "version unavailable"}`)
  }
  for (const tool of OPTIONAL) {
    if (!found[tool]) {
      // Optional, and the message says what is lost rather than pretending it is fine.
      info(`${tool} not on PATH - ${optionalCost(tool)}`)
      continue
    }
    ok(`${tool} ${toolVersion(tool, ["--version"]) ?? "version unavailable"}`)
  }
  if (missingRequired.length > 0) {
    console.log(`\n${paint("Missing required tool(s): " + missingRequired.join(", "), colours.red)}`)
    console.log("  -> Node.js 22.12+ and pnpm 11: https://pnpm.io/installation")
    console.log("  -> uv: https://docs.astral.sh/uv/getting-started/installation/")
    process.exit(1)
  }

  heading("Installing Python dependencies")
  info("uv sync --extra dev")
  const uv = run(uvBin(), ["sync", "--extra", "dev"], { capture: true })
  if (uv.code !== 0) {
    console.log(paint("  uv sync failed", colours.red))
    console.log(uv.stderr || uv.stdout)
    console.log("  -> check the uv version and that .python-version (3.12) is installed")
    process.exit(1)
  }
  ok("Python environment resolved")

  heading("Installing JavaScript dependencies")
  info(`${pnpmBin()} install`)
  const pnpm = run(pnpmBin(), ["install"], { capture: true })
  if (pnpm.code !== 0) {
    console.log(paint("  pnpm install failed", colours.red))
    console.log(pnpm.stderr || pnpm.stdout)
    process.exit(1)
  }
  ok("Node workspace linked")

  heading("Generating contracts")
  const contracts = run(pnpmBin(), ["--filter", "@niharamesh/contracts", "generate"], { capture: true })
  if (contracts.code !== 0) {
    // Contracts are generated from the Python models; a failure here is a real
    // problem, but it is reported as a failure rather than silently skipped.
    console.log(paint("  contract generation failed", colours.red))
    console.log(contracts.stderr || contracts.stdout)
    process.exit(1)
  }
  ok("TypeScript types generated from the Python domain models")

  heading("Exporting the scenario library")
  const scenarios = run(uvBin(), ["run", "nihara", "scenarios", "export"], { capture: true })
  if (scenarios.code !== 0) {
    warn("scenario export failed")
    console.log(scenarios.stderr || scenarios.stdout)
  } else {
    ok("7 built-in scenarios exported")
  }

  console.log(`\n${paint("Bootstrap complete.", colours.bold)} Next: ${paint("pnpm doctor", colours.green)}`)
}

function optionalCost(tool) {
  switch (tool) {
    case "node":
      return "required; JavaScript tooling will not run without it"
    case "opencode":
      return "only needed to run coding agents against this repository"
    case "docker":
      return "the native launcher works without it; see docs/DEPLOYMENT.md"
    default:
      return "optional"
  }
}

main().catch((err) => {
  console.error(`bootstrap failed: ${err?.stack ?? err}`)
  process.exit(1)
})
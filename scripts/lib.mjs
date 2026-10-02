#!/usr/bin/env node
// Shared helpers for the pnpm command surface.
//
// These scripts are plain Node ESM so the same commands work on PowerShell,
// bash and anything else without a bash-only chain hidden behind a
// cross-platform entry point.

import { spawn, spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..")

const IS_WINDOWS = process.platform === "win32"

export const colours = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  cyan: "\x1b[36m",
}

export function paint(text, colour) {
  if (!colour || process.env.NO_COLOR) return text
  return `${colour}${text}${colours.reset}`
}

export function heading(text) {
  console.log(`\n${paint(text, colours.bold + colours.cyan)}`)
}

export function ok(text) {
  console.log(`  ${paint("ok  ", colours.green)} ${text}`)
}

export function warn(text) {
  console.log(`  ${paint("WARN", colours.yellow)} ${text}`)
}

export function fail(text) {
  console.log(`  ${paint("FAIL", colours.red)} ${text}`)
}

export function info(text) {
  console.log(`  ${paint("..  ", colours.dim)} ${text}`)
}

/**
 * Run a command, streaming or capturing its output. Returns the exit code.
 * Never throws on a non-zero exit: callers decide what that means.
 */
export function run(cmd, args, options = {}) {
  const { cwd = REPO_ROOT, env = {}, capture = false, stdio = capture ? "pipe" : "inherit" } = options
  const result = spawnSync(cmd, args, {
    cwd,
    env: { ...process.env, ...env },
    encoding: "utf8",
    shell: IS_WINDOWS,
    stdio,
  })
  if (result.error) {
    return { code: 127, stdout: "", stderr: String(result.error.message) }
  }
  return {
    code: result.status ?? 1,
    stdout: result.stdout ?? "",
    stderr: result.stderr ?? "",
  }
}

/** Run a command in the background, returning the child process. */
export function spawnBackground(cmd, args, options = {}) {
  const { cwd = REPO_ROOT, env = {} } = options
  return spawn(cmd, args, {
    cwd,
    env: { ...process.env, ...env },
    shell: IS_WINDOWS,
    stdio: ["ignore", "pipe", "pipe"],
  })
}

/** The right command name for a package manager binary on this platform. */
export function pnpmBin() {
  return IS_WINDOWS ? "pnpm.cmd" : "pnpm"
}

export function uvBin() {
  return IS_WINDOWS ? "uv.exe" : "uv"
}

export function pythonBin() {
  return IS_WINDOWS ? "python.exe" : "python"
}

/** Which of the given tools are actually on PATH right now. */
export function whichAll(names) {
  const out = {}
  for (const name of names) {
    const probe = IS_WINDOWS ? "where" : "which"
    const result = spawnSync(probe, [name], { encoding: "utf8", shell: IS_WINDOWS })
    out[name] = result.status === 0 && String(result.stdout || "").trim().length > 0
  }
  return out
}

export function toolVersion(cmd, args) {
  const result = spawnSync(cmd, args, { encoding: "utf8", shell: IS_WINDOWS })
  if (result.status !== 0) return null
  const first = String(result.stdout || result.stderr || "").trim().split(/\r?\n/)[0]
  return first || null
}

export function repoPath(...parts) {
  return join(REPO_ROOT, ...parts)
}

export function hasModule(pathParts) {
  return existsSync(repoPath(...pathParts))
}

/** Minimum Node version this project's toolchain needs. */
export const MIN_NODE_MAJOR = 22

export function nodeMajor() {
  return Number.parseInt(process.versions.node.split(".")[0] ?? "0", 10)
}

/** True when a TCP port can be bound on the loopback interface. */
export async function portIsFree(port, host = "127.0.0.1") {
  const { createServer } = await import("node:net")
  return new Promise((settle) => {
    const server = createServer()
    server.once("error", () => settle(false))
    server.once("listening", () => server.close(() => settle(true)))
    server.listen(port, host)
  })
}
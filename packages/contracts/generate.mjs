// Generate TypeScript types from the authoritative JSON Schemas.
//
// The Python Pydantic domain models are the single source of truth. They emit
// JSON Schema via `uv run python scripts/generate_contracts.py`; this script
// then emits TypeScript from that JSON Schema. No type is ever handwritten in
// two places.
import { execFileSync } from "node:child_process"
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync, rmSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const here = dirname(fileURLToPath(import.meta.url))
const repoRoot = resolve(here, "..", "..")
// The JSON Schemas are generated from the Python domain models into the Python
// package so they ship with the wheel. This script derives TypeScript from them.
const schemaDir = join(repoRoot, "src", "niharamesh", "contracts", "schemas")
const outDir = join(here, "generated")

function fail(msg) {
  console.error(`[contracts] ${msg}`)
  process.exit(1)
}

if (!existsSync(schemaDir)) {
  fail("schemas/ is missing. Run: uv run python scripts/generate_contracts.py")
}

// 1. Regenerate the JSON Schemas from the Python models.
try {
  execFileSync("uv", ["run", "python", join(repoRoot, "scripts", "generate_contracts.py")], {
    cwd: repoRoot,
    stdio: "inherit",
  })
} catch {
  fail("failed to regenerate JSON Schemas from the Python domain models")
}

// 2. Emit TypeScript from each schema.
const { compile } = await import("json-schema-to-typescript")
const files = readdirSync(schemaDir).filter((f) => f.endsWith(".json") && f !== "index.json")
if (files.length === 0) fail("no schemas found")

rmSync(outDir, { recursive: true, force: true })
mkdirSync(outDir, { recursive: true })

const index = JSON.parse(readFileSync(join(schemaDir, "index.json"), "utf8"))
const exports = []

for (const file of files.sort()) {
  const name = file.replace(/\.json$/, "")
  const schema = JSON.parse(readFileSync(join(schemaDir, file), "utf8"))
  const banner = `// GENERATED FILE - DO NOT EDIT BY HAND.\n// Source: src/niharamesh/domain/**  ->  packages/contracts/schemas/${file}\n// Regenerate: pnpm --filter @niharamesh/contracts generate\n`
  try {
    const ts = await compile(schema, name, { bannerComment: "", additionalProperties: false })
    writeFileSync(join(outDir, `${name}.ts`), banner + ts, "utf8")
    exports.push(`export type { ${name} } from "./${name}.js"`)
  } catch (err) {
    fail(`failed to compile ${file}: ${err.message}`)
  }
}

const indexBanner = `// GENERATED FILE - DO NOT EDIT BY HAND.\n// Source: packages/contracts/schemas/index.json\n\n`
writeFileSync(
  join(outDir, "index.ts"),
  indexBanner +
    `export const SCHEMA_VERSION = ${JSON.stringify(index.version)}\n` +
    `export const PROTOCOL_VERSION = ${JSON.stringify(index.protocol_version)}\n` +
    `export const SCHEMA_COUNT = ${index.count}\n\n` +
    exports.join("\n") +
    "\n",
  "utf8",
)

console.log(`[contracts] generated ${files.length} TypeScript type modules`)
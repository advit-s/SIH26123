/**
 * Read-only fields.
 *
 * `SourcedValue` is the important one: it renders a number *together with its
 * provenance* (`measured` / `simulated` / `estimated` / `unavailable`). A bare
 * number with no provenance is exactly the "invented measurement" the project
 * forbids, so this component refuses to render one.
 */
import type { ReactNode } from "react"
import type { Sourced } from "../../lib/api/types"
import { UNAVAILABLE, age as fmtAge } from "../../lib/format"
import { Chip } from "./Chip"
import type { Tone } from "./tone"

export function Field({
  label,
  children,
  mono = false,
  hint,
  className = "",
}: {
  label: string
  children: ReactNode
  mono?: boolean
  hint?: string
  className?: string
}) {
  return (
    <div className={`min-w-0 ${className}`}>
      <dt className="stencil text-[9px] text-ink-3" title={hint}>
        {label}
      </dt>
      <dd className={`min-w-0 break-words text-[12px] text-ink ${mono ? "num" : ""}`}>{children}</dd>
    </div>
  )
}

export function FieldGrid({ children, cols = 2 }: { children: ReactNode; cols?: 2 | 3 }) {
  return (
    <dl className={`grid gap-x-3 gap-y-2.5 px-3 py-2.5 ${cols === 2 ? "grid-cols-2" : "grid-cols-3"}`}>
      {children}
    </dl>
  )
}

const SOURCE_TONE: Record<Sourced["source"], Tone> = {
  measured: "teal",
  simulated: "steel",
  estimated: "amber",
  unavailable: "muted",
}

/**
 * A number with its source. `null` value renders as "unavailable" — never 0.
 */
export function SourcedValue({
  sourced,
  format,
  unit,
}: {
  sourced: Sourced | null | undefined
  format?: (value: number) => string
  unit?: string
}) {
  if (sourced === null || sourced === undefined) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="text-ink-3">{UNAVAILABLE}</span>
        <Chip tone="muted">no source</Chip>
      </span>
    )
  }
  if (sourced.source === "unavailable" || sourced.value === null) {
    return (
      <span className="inline-flex flex-wrap items-center gap-1.5">
        <span className="text-ink-3">{UNAVAILABLE}</span>
        <Chip tone="muted" title="No value was published for this metric.">
          unavailable
        </Chip>
        {sourced.note !== undefined ? <span className="text-[11px] text-ink-3">{sourced.note}</span> : null}
      </span>
    )
  }
  const text = format !== undefined ? format(sourced.value) : String(sourced.value)
  return (
    <span className="inline-flex flex-wrap items-baseline gap-1.5">
      <span className="num text-[12px] text-ink">{text}</span>
      {unit !== undefined ? <span className="text-[11px] text-ink-3">{unit}</span> : null}
      <Chip tone={SOURCE_TONE[sourced.source]} title={`Provenance: ${sourced.source}`}>
        {sourced.source}
      </Chip>
      {sourced.age_s !== null ? <span className="num text-[10px] text-ink-3">{fmtAge(sourced.age_s)} old</span> : null}
    </span>
  )
}

/** Battery with its declared source. Never a bare percentage. */
export function BatteryReadout({
  fraction,
  source,
  drainModel,
}: {
  fraction: number | null | undefined
  source: "measured" | "simulated" | "estimated" | "unavailable" | undefined
  drainModel?: string | null
}) {
  const src: Sourced["source"] =
    source === "measured" || source === "simulated" || source === "estimated" ? source : "unavailable"
  if (fraction === null || fraction === undefined || src === "unavailable") {
    return (
      <span className="inline-flex items-center gap-1.5">
        <span className="text-ink-3">{UNAVAILABLE}</span>
        <Chip tone="muted">{src === "unavailable" ? "unavailable" : "no reading"}</Chip>
      </span>
    )
  }
  const pct = Math.round(Math.min(1, Math.max(0, fraction)) * 100)
  const tone: Tone = pct <= 15 ? "red" : pct <= 35 ? "amber" : "teal"
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden="true"
        className={`inline-block h-[6px] w-[52px] border ${tone === "red" ? "border-red" : tone === "amber" ? "border-amber" : "border-teal"}`}
      >
        <span
          className={`block h-full ${tone === "red" ? "bg-red" : tone === "amber" ? "bg-amber" : "bg-teal"}`}
          style={{ width: `${pct}%` }}
        />
      </span>
      <span className="num text-[12px] text-ink">{pct}%</span>
      <Chip tone={SOURCE_TONE[src]}>{src}</Chip>
      {drainModel != null && drainModel.length > 0 ? (
        <span className="num text-[10px] text-ink-3">{drainModel}</span>
      ) : null}
    </span>
  )
}

/** Key/value row used inside inspectors. */
export function Row({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-rule/60 px-3 py-1.5 last:border-b-0">
      <span className="stencil shrink-0 text-[9px] text-ink-3">{label}</span>
      <span className={`min-w-0 text-right text-[12px] text-ink ${mono ? "num break-all" : ""}`}>{children}</span>
    </div>
  )
}
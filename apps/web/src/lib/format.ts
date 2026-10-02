/**
 * Honest formatting.
 *
 * Every helper here has to answer "what do we print when the number is not
 * there?" and the answer is always `unavailable` — never `0`, never `-`, never
 * a blank cell that a reader would mistake for "nothing to report".
 */

export const UNAVAILABLE = "unavailable" as const

/** Metres, 2 dp, with an explicit unit. `null` -> "unavailable". */
export function metres(value: number | null | undefined, dp = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE
  return `${value.toFixed(dp)} m`
}

export function radians(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE
  return `${value.toFixed(3)} rad`
}

/** Heading as a compass bearing — what an operator reads off a floor plan. */
export function heading(theta: number | null | undefined): string {
  if (theta === null || theta === undefined || !Number.isFinite(theta)) return UNAVAILABLE
  const deg = ((theta * 180) / Math.PI) % 360
  const normalised = deg < 0 ? deg + 360 : deg
  return `${normalised.toFixed(0)}°`
}

/** Simulation seconds -> `m:ss.d`. Simulation seconds are their own domain. */
export function simClock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return UNAVAILABLE
  const sign = seconds < 0 ? "-" : ""
  const s = Math.abs(seconds)
  const m = Math.floor(s / 60)
  const rem = s - m * 60
  return `${sign}${m}:${rem.toFixed(1).padStart(4, "0")}`
}

/** An age. Ages are the whole product, so they get 1 dp and an explicit unit. */
export function age(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return UNAVAILABLE
  if (seconds < 0.001) return "< 1 ms"
  if (seconds < 1) return `${(seconds * 1000).toFixed(0)} ms`
  if (seconds < 90) return `${seconds.toFixed(1)} s`
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds - m * 60)
  if (m < 90) return `${m}m ${String(s).padStart(2, "0")}s`
  const h = Math.floor(m / 60)
  return `${h}h ${String(m - h * 60).padStart(2, "0")}m`
}

export function percent(value: number | null | undefined, dp = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE
  return `${value.toFixed(dp)}%`
}

export function ratio(fraction: number | null | undefined, dp = 0): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return UNAVAILABLE
  return `${(fraction * 100).toFixed(dp)}%`
}

export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE
  return String(value)
}

/** Display UTC. Wall-clock is for humans only and is never used for expiry. */
export function utc(iso: string | null | undefined): string {
  if (!iso) return UNAVAILABLE
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  // Seconds resolution: millisecond precision is noise in an operator readout.
  const iso6 = d.toISOString()
  const withoutMillis = iso6.slice(0, 19)
  return `${withoutMillis.replace("T", " ")} UTC`
}

/** Nanosecond clocks are exact integers; render without float drift. */
export function nanos(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return UNAVAILABLE
  return `${Math.trunc(value).toLocaleString("en-US")} ns`
}

export function speed(multiplier: number | null | undefined): string {
  if (multiplier === null || multiplier === undefined || !Number.isFinite(multiplier)) return UNAVAILABLE
  return `${multiplier.toFixed(2)}×`
}

export function speedLong(multiplier: number | null | undefined): string {
  if (multiplier === null || multiplier === undefined || !Number.isFinite(multiplier)) return UNAVAILABLE
  if (multiplier === 1) return "1.00× real time"
  return `${multiplier.toFixed(2)}× real time`
}

/**
 * Wall clock as a time-of-day for a dense context bar. The date is not dropped —
 * it moves into the cell's `title`, so nothing is hidden, only condensed.
 */
export function utcTime(iso: string | null | undefined): string {
  const full = utc(iso)
  if (full === UNAVAILABLE) return UNAVAILABLE
  return full.slice(11, 19)
}

/**
 * Run states that must never be rendered with a success treatment.
 * `success` styling is reserved for `completed` + `outcome: success` +
 * complete evidence.
 */
export const FAILED_RUN_STATES = new Set(["unsafe", "failed", "timed_out", "cancelled", "queued", "running", "paused"])

export type OutcomeClass = "good" | "attention" | "fault" | "muted" | "running"

export function outcomeClass(state: string | null | undefined, outcome: string | null | undefined): OutcomeClass {
  const s = (state ?? "").toLowerCase()
  const o = (outcome ?? "").toLowerCase()
  if (s === "unsafe") return "fault"
  if (s === "failed" || s === "timed_out") return "fault"
  if (s === "cancelled") return "muted"
  if (s === "running") return "running"
  if (s === "queued" || s === "paused") return "attention"
  if (o === "unsafe") return "fault"
  if (o === "failed" || o === "timed_out") return "fault"
  if (o === "degraded") return "attention"
  if (o === "incomplete_evidence") return "attention"
  if (o === "expected_safe_stop") return "attention"
  if (o === "success") return "good"
  return "muted"
}

export function outcomeLabel(state: string | null | undefined, outcome: string | null | undefined): string {
  if (state === "unsafe") return "unsafe"
  if (outcome) return outcome.replace(/_/g, " ")
  return (state ?? "unknown").replace(/_/g, " ")
}

/** Long identifiers must wrap, not overflow. Used by every ID cell. */
export function truncateId(id: string, head = 10, tail = 4): string {
  if (id.length <= head + tail + 1) return id
  return `${id.slice(0, head)}…${id.slice(-tail)}`
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, " ")
    .replace(/^./, (c) => c.toUpperCase())
}

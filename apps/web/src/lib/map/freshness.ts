/**
 * Telemetry freshness.
 *
 * Invariant 10 in AGENTS.md is "honest states", and the cockpit rule that
 * follows from it is: **a stale pose is frozen and labelled with its age**. We
 * never keep animating a robot along a presumed path after evidence stops
 * arriving, and we never replace a missing pose with the origin.
 *
 * This module is pure so the rule can be tested without a canvas.
 */

export type FreshnessTone = "live" | "aging" | "stale" | "absent" | "never"

export interface PoseFreshness {
  /** True when the renderer must hold the last known pose and stop motion. */
  frozen: boolean
  tone: FreshnessTone
  /** Age of the newest evidence, in seconds. `null` when nothing arrived. */
  age_s: number | null
  /** Text an operator can act on. Never just "stale". */
  label: string
  /** The single word used in compact chips and on the map badge. */
  short: string
}

export const DEFAULT_FRESHNESS_HORIZON_S = 2.5

export function describePoseFreshness(
  ageSeconds: number | null | undefined,
  freshnessHorizonS: number = DEFAULT_FRESHNESS_HORIZON_S,
): PoseFreshness {
  if (ageSeconds === null || ageSeconds === undefined || !Number.isFinite(ageSeconds)) {
    return {
      frozen: true,
      tone: "absent",
      age_s: null,
      label: "No pose evidence has been received for this robot.",
      short: "no evidence",
    }
  }
  const horizon = Math.max(0.25, freshnessHorizonS)
  const label = `${ageSeconds < 1 ? `${Math.round(ageSeconds * 1000)} ms` : `${ageSeconds.toFixed(1)} s`} old`
  if (ageSeconds > horizon) {
    return {
      frozen: true,
      tone: "stale",
      age_s: ageSeconds,
      label: `Frozen at the last known pose — ${label}, past the ${horizon.toFixed(1)} s freshness horizon. This robot's position is not confirmed.`,
      short: `frozen · ${label}`,
    }
  }
  if (ageSeconds > horizon * 0.6) {
    return {
      frozen: false,
      tone: "aging",
      age_s: ageSeconds,
      label: `Pose evidence is ${label}, approaching the ${horizon.toFixed(1)} s freshness horizon.`,
      short: label,
    }
  }
  return { frozen: false, tone: "live", age_s: ageSeconds, label: `Pose evidence is ${label}.`, short: label }
}

/** Freshness class for a peer communication channel. */
export function describeChannelFreshness(
  lastRxAgeS: number | null | undefined,
  dropped: number | null | undefined,
): { tone: FreshnessTone; label: string } {
  const droppedCount = dropped ?? 0
  if (lastRxAgeS === null || lastRxAgeS === undefined) {
    return { tone: "never", label: droppedCount > 0 ? `dropped ${droppedCount} · never heard` : "never heard" }
  }
  if (lastRxAgeS > 5) return { tone: "stale", label: `${lastRxAgeS.toFixed(1)} s old · ${droppedCount} dropped` }
  if (lastRxAgeS > 1) return { tone: "aging", label: `${lastRxAgeS.toFixed(1)} s old · ${droppedCount} dropped` }
  return { tone: "live", label: `${lastRxAgeS.toFixed(2)} s old · ${droppedCount} dropped` }
}

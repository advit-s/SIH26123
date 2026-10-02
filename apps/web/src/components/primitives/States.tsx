/**
 * Real state components.
 *
 * Every one of these exists because the product promises honest states: loading,
 * empty, error, reconnecting, stale, partial, unavailable. There is no
 * "spinner while showing zeros" path anywhere in the cockpit.
 */
import type { ReactNode } from "react"
import { ApiError } from "../../lib/api/types"
import { Button } from "./Button"
import { HatchStrip, Strip } from "./Panel"
import { TONE_GLYPH, type Tone } from "./tone"

export function LoadingState({ what, rows = 4 }: { what: string; rows?: number }) {
  return (
    <div className="p-3" role="status" aria-live="polite">
      <p className="stencil text-[10px] text-ink-3">{`loading ${what}…`}</p>
      <div className="mt-2 space-y-1.5" aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="h-[11px] w-full bg-raised" style={{ width: `${100 - i * 11}%` }} />
        ))}
      </div>
    </div>
  )
}

/**
 * Error state. Never silently degraded, never filled with zeros. When the API
 * is simply not running we say exactly that and name the command that starts it.
 */
export function ErrorState({
  error,
  what,
  onRetry,
}: {
  error: unknown
  what: string
  onRetry?: () => void
}) {
  const api = error instanceof ApiError ? error : null
  const unreachable = api?.unreachable === true
  const message = api?.message ?? (error instanceof Error ? error.message : String(error))
  return (
    <div className="p-3" role="alert">
      <HatchStrip tone={unreachable ? "amber" : "red"}>
        <strong className="font-semibold">{unreachable ? "The API is not reachable." : `${what} could not be loaded.`}</strong>
      </HatchStrip>
      <p className="mt-2 text-[12px] leading-relaxed text-ink-2">{message}</p>
      <dl className="num mt-2 space-y-0.5 text-[11px] text-ink-3">
        <div className="flex gap-2">
          <dt>code</dt>
          <dd className="text-ink-2">{api?.code ?? "unknown_error"}</dd>
        </div>
        {api?.requestId != null ? (
          <div className="flex gap-2">
            <dt>request</dt>
            <dd className="break-all text-ink-2">{api.requestId}</dd>
          </div>
        ) : null}
      </dl>
      {unreachable ? (
        <p className="mt-2 text-[12px] text-ink-2">
          Start the API and cockpit with <code className="num text-amber">pnpm dev</code>, then retry. Nothing on this
          page is being guessed in the meantime.
        </p>
      ) : null}
      {onRetry !== undefined ? (
        <div className="mt-2.5">
          <Button onClick={onRetry}>Retry</Button>
        </div>
      ) : null}
    </div>
  )
}

/**
 * Empty state. An invitation to act, not an apology: it names what would make
 * this view non-empty.
 */
export function EmptyState({
  title,
  body,
  action,
}: {
  title: string
  body: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-start gap-2 p-4">
      <span aria-hidden="true" className="text-[16px] text-ink-4">
        {TONE_GLYPH.muted}
      </span>
      <h3 className="text-[13px] font-semibold text-ink">{title}</h3>
      <p className="max-w-[52ch] text-[12px] leading-relaxed text-ink-2">{body}</p>
      {action !== undefined ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}

/** Stale banner: what we are showing, and how old it is. */
export function StaleBanner({
  ageLabel,
  detail,
  onRefresh,
}: {
  ageLabel: string
  detail: string
  onRefresh?: () => void
}) {
  return (
    <Strip tone="amber">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <strong className="font-semibold">Stale data.</strong>
        <span>{detail}</span>
        <span className="num">{ageLabel}</span>
        {onRefresh !== undefined ? (
          <button type="button" onClick={onRefresh} className="underline underline-offset-2 hover:text-ink">
            Refresh now
          </button>
        ) : null}
      </div>
    </Strip>
  )
}

/**
 * Partial result. Used when some sub-resources loaded and others did not; the
 * gaps are named so they can be counted rather than glossed over.
 */
export function PartialResultBanner({
  loaded,
  missing,
  missingDetail,
}: {
  loaded: string
  missing: string[]
  missingDetail?: string
}) {
  if (missing.length === 0) return null
  return (
    <Strip tone="amber">
      <div>
        <strong className="font-semibold">Partial result.</strong> Loaded: {loaded}. Missing: {missing.join(", ")}.
        {missingDetail !== undefined ? ` ${missingDetail}` : ""}
      </div>
    </Strip>
  )
}

/**
 * Unavailable feature. Names its real prerequisite instead of presenting a dead
 * button. Used for hardware-in-the-loop actuation, ROS 2 bridges and anything
 * else this deployment genuinely cannot do.
 *
 * The hatching is a *left rail*, not a full-panel wash: hatching is a warning
 * signal, but a wash behind body text costs contrast and the text is the part
 * an operator actually needs to read.
 */
export function UnavailableFeature({
  title,
  prerequisite,
  detail,
}: {
  title: string
  prerequisite: string
  detail: string
}) {
  return (
    <div className="panel-ticks panel flex p-0">
      <div aria-hidden="true" className="hatch-amber w-[10px] shrink-0 border-r border-amber" />
      <div className="min-w-0 flex-1 px-3 py-2.5">
        <div className="flex items-center gap-2">
          <span aria-hidden="true" className="text-[12px] text-amber">
            {TONE_GLYPH.amber}
          </span>
          <h3 className="text-[12px] font-semibold text-amber">{title}</h3>
        </div>
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">{detail}</p>
        <p className="num mt-1.5 text-[11px] leading-relaxed text-ink-3">
          Prerequisite: <span className="text-ink-2">{prerequisite}</span>
        </p>
      </div>
    </div>
  )
}

/** Reconnecting / degraded connection strip. */
export function ConnectionBanner({
  status,
  since,
  detail,
}: {
  status: string
  since?: string
  detail?: string
}) {
  const tone: Tone = status === "live" ? "teal" : status === "error" ? "red" : "amber"
  return (
    <Strip tone={tone}>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span
          aria-hidden="true"
          className={`inline-block h-[7px] w-[7px] rounded-full ${
            status === "live" ? "bg-teal" : status === "error" ? "bg-red" : "bg-amber"
          } ${status === "live" ? "" : "breathe"}`}
        />
        <strong className="font-semibold capitalize">{status.replace(/_/g, " ")}</strong>
        {detail !== undefined ? <span>{detail}</span> : null}
        {since !== undefined ? <span className="num text-[10px]">since {since}</span> : null}
      </div>
    </Strip>
  )
}
/**
 * Machine panels. Flat faces, hairline rules, corner ticks, 2 px radius.
 * Deliberately *not* cards: the cockpit is a single instrument panel, and a
 * field of identical rounded cards would read as a generic dashboard.
 */
import type { ReactNode } from "react"
import { TONE_BG, TONE_BORDER, TONE_GLYPH, TONE_TEXT, type Tone } from "./tone"

export function Panel({
  children,
  className = "",
  ticks = false,
  as: Tag = "section",
}: {
  children: ReactNode
  className?: string
  ticks?: boolean
  as?: "section" | "div" | "aside"
}) {
  return <Tag className={`panel flex min-h-0 flex-col ${ticks ? "panel-ticks" : ""} ${className}`}>{children}</Tag>
}

export function PanelHeader({
  title,
  subtitle,
  right,
  tone = "info",
  id,
}: {
  title: ReactNode
  subtitle?: ReactNode
  right?: ReactNode
  tone?: Tone
  id?: string
}) {
  return (
    <header className="flex items-center justify-between gap-2 border-b border-rule px-3 py-1.5">
      <div className="min-w-0">
        <h2 id={id} className="stencil truncate text-[10px] text-ink-2">
          <span aria-hidden="true" className={`mr-1.5 ${TONE_TEXT[tone]}`}>
            {TONE_GLYPH[tone]}
          </span>
          {title}
        </h2>
        {subtitle !== undefined ? <p className="truncate text-[11px] text-ink-3">{subtitle}</p> : null}
      </div>
      {right !== undefined ? <div className="flex shrink-0 items-center gap-1.5">{right}</div> : null}
    </header>
  )
}

export function PanelBody({
  children,
  className = "",
  scroll = true,
}: {
  children: ReactNode
  className?: string
  scroll?: boolean
}) {
  return <div className={`min-h-0 flex-1 ${scroll ? "scroll-y" : ""} ${className}`}>{children}</div>
}

export function Strip({
  children,
  tone = "info",
  className = "",
}: {
  children: ReactNode
  tone?: Tone
  className?: string
}) {
  return (
    <div
      className={`flex items-center gap-2 border px-3 py-1.5 text-[11px] ${TONE_BORDER[tone]} ${TONE_BG[tone]} ${TONE_TEXT[tone]} ${className}`}
    >
      <span aria-hidden="true">{TONE_GLYPH[tone]}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

/**
 * Hatched strip. Used for "withheld", "no evidence" and "recorded playback" —
 * states where the operator must feel a difference before reading a word.
 */
export function HatchStrip({
  children,
  tone = "amber",
  className = "",
}: {
  children: ReactNode
  tone?: "amber" | "red" | "steel"
  className?: string
}) {
  const hatch = tone === "amber" ? "hatch-amber" : tone === "red" ? "hatch-red" : "hatch-steel"
  return (
    <div
      className={`flex items-center gap-2 border px-3 py-1.5 text-[11px] ${TONE_BORDER[tone]} ${TONE_TEXT[tone]} ${hatch} ${className}`}
    >
      <span aria-hidden="true">{TONE_GLYPH[tone]}</span>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}
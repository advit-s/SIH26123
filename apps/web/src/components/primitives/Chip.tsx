/**
 * Chips and status indicators. Every chip carries a glyph and a word as well as
 * a colour, so the meaning survives a monochrome print-out and a colour-vision
 * deficiency.
 */
import type { ReactNode } from "react"
import { TONE_BG, TONE_BORDER, TONE_GLYPH, TONE_TEXT, type Tone } from "./tone"

export function Chip({
  children,
  tone = "info",
  glyph = true,
  title,
  className = "",
}: {
  children: ReactNode
  tone?: Tone
  glyph?: boolean
  title?: string
  className?: string
}) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap border px-1.5 py-[1px] text-[10px] leading-4 ${TONE_BORDER[tone]} ${TONE_BG[tone]} ${TONE_TEXT[tone]} ${className}`}
    >
      {glyph ? (
        <span aria-hidden="true" className="text-[8px]">
          {TONE_GLYPH[tone]}
        </span>
      ) : null}
      {children}
    </span>
  )
}

export function StatusDot({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px]">
      <span
        aria-hidden="true"
        className={`inline-block h-[7px] w-[7px] rounded-full ${
          tone === "teal"
            ? "bg-teal"
            : tone === "amber"
              ? "bg-amber"
              : tone === "red"
                ? "bg-red"
                : tone === "steel"
                  ? "bg-steel"
                  : "bg-ink-4"
        }`}
      />
      <span className="text-ink-2">{label}</span>
    </span>
  )
}

/** Monospace identifier chip. Long IDs wrap rather than overflow. */
export function IdChip({ children, tone = "muted", title }: { children: ReactNode; tone?: Tone; title?: string }) {
  return (
    <span
      title={title}
      className={`num inline-block max-w-full break-all border px-1 py-[1px] text-[10px] ${TONE_BORDER[tone]} ${TONE_TEXT[tone]}`}
    >
      {children}
    </span>
  )
}
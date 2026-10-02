/**
 * Bottom status strip.
 *
 * Two jobs: state the evidence legend once so colour is learnable, and carry the
 * one sentence that keeps the whole product honest — the browser observes; it
 * never advances robot truth.
 */
import { TONE_GLYPH, type Tone } from "../primitives/tone"

export function StatusStrip({
  artifactPath,
  manifestDigest,
  reduceMotion,
  keyboardHint = "Tab moves between controls · arrow keys pan the map · +/− zoom · F fits",
}: {
  artifactPath: string | null
  manifestDigest: string | null
  reduceMotion: boolean
  keyboardHint?: string
}) {
  const legend: { tone: Tone; label: string }[] = [
    { tone: "teal", label: "normal coordination" },
    { tone: "amber", label: "attention / withheld" },
    { tone: "red", label: "confirmed fault" },
    { tone: "steel", label: "evaluator truth" },
  ]
  return (
    <footer className="flex shrink-0 items-center gap-3 border-t border-rule bg-panel px-3 py-1">
      <ul className="flex shrink-0 items-center gap-3" aria-label="Colour legend">
        {legend.map((item) => (
          <li key={item.tone} className="flex items-center gap-1 text-[10px] text-ink-3">
            <span aria-hidden="true" className={toneClass(item.tone)}>
              {TONE_GLYPH[item.tone]}
            </span>
            {item.label}
          </li>
        ))}
      </ul>

      <p className="num hidden min-w-0 flex-1 truncate text-[10px] text-ink-3 @min-[1100px]:block" title={artifactPath ?? undefined}>
        {artifactPath !== null ? `evidence ${artifactPath}` : "evidence path unavailable"}
        {manifestDigest !== null ? ` · manifest ${manifestDigest.slice(0, 12)}` : ""}
      </p>

      {reduceMotion ? (
        <span className="shrink-0 text-[10px] text-ink-3">reduced motion on</span>
      ) : null}

      <p className="hidden shrink-0 text-[10px] text-ink-3 @min-[1280px]:block">{keyboardHint}</p>

      <p className="shrink-0 text-[10px] text-ink-3" data-testid="authority-reminder">
        This console observes runs. It never advances robot truth.
      </p>
    </footer>
  )
}

function toneClass(tone: Tone): string {
  switch (tone) {
    case "teal":
      return "text-teal"
    case "amber":
      return "text-amber"
    case "red":
      return "text-red"
    case "steel":
      return "text-steel"
    case "info":
      return "text-ink-2"
    default:
      return "text-ink-3"
  }
}
/**
 * Tone vocabulary.
 *
 * Four tones, and they mean the same thing everywhere in the product:
 *   teal   normal coordination — granted, moving, fresh, nominal
 *   amber  attention — stale, withheld, degraded, waiting, pending
 *   red    confirmed fault — violation, unsafe, crashed, dropped
 *   steel  EVALUATOR TRUTH — the recorder's independent verdict, never the
 *          agent's own knowledge
 *   muted  no signal / deliberately absent
 *   info   neutral structural chrome
 *
 * Every tone is *always* paired with a glyph or a word, so colour is never the
 * only carrier of meaning.
 */
export type Tone = "teal" | "amber" | "red" | "steel" | "muted" | "info"

export const TONE_GLYPH: Record<Tone, string> = {
  teal: "●",
  amber: "▲",
  red: "■",
  steel: "◇",
  muted: "○",
  info: "·",
}

export const TONE_TEXT: Record<Tone, string> = {
  teal: "text-teal",
  amber: "text-amber",
  red: "text-red",
  steel: "text-steel",
  muted: "text-ink-3",
  info: "text-ink-2",
}

export const TONE_BORDER: Record<Tone, string> = {
  teal: "border-teal",
  amber: "border-amber",
  red: "border-red",
  steel: "border-steel",
  muted: "border-rule",
  info: "border-rule-strong",
}

export const TONE_BG: Record<Tone, string> = {
  teal: "bg-teal-wash",
  amber: "bg-amber-wash",
  red: "bg-red-wash",
  steel: "bg-steel-wash",
  muted: "bg-raised",
  info: "bg-raised",
}

export function toneFromOutcome(outcome: string | null | undefined): Tone {
  switch ((outcome ?? "").toLowerCase()) {
    case "success":
      return "teal"
    case "degraded":
    case "incomplete_evidence":
    case "expected_safe_stop":
      return "amber"
    case "unsafe":
    case "failed":
    case "timed_out":
      return "red"
    case "cancelled":
      return "muted"
    case "running":
      return "teal"
    default:
      return "muted"
  }
}

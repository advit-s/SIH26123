/**
 * Stable per-robot colour.
 *
 * Requirement: a robot's colour must be the same for the whole run, in every
 * view (map, table row, event log, communication matrix, replay), and must not
 * shift when the fleet order changes or when a robot disappears and comes back.
 *
 * Mechanism: FNV-1a over the robot id, quantised to a hand-picked wheel of six
 * hues that all clear 4.5:1 against the floor. Colour is *never* the only
 * signal — every robot also carries its id and a distinct chassis glyph.
 */

export const ROBOT_GLYPHS = ["▣", "▤", "▥", "▦", "▧", "▨", "▩", "▬"] as const

/** Six hues, spaced far apart, chosen to stay legible on slate and on paper. */
const DARK_WHEEL = ["#3ec9b6", "#86abd2", "#e5ab3d", "#b995e0", "#ec5f51", "#7fc46b"] as const
const LIGHT_WHEEL = ["#0b6d62", "#2c5c8a", "#855200", "#6b3f9e", "#a52011", "#2f6b1f"] as const

export function hashId(id: string): number {
  let h = 0x811c9dc5
  for (let i = 0; i < id.length; i += 1) {
    h ^= id.charCodeAt(i)
    h = Math.imul(h, 0x01000193) >>> 0
  }
  return h >>> 0
}

/**
 * Colour by identity, not by position. Two different ids may collide on a hue
 * (six hues, many robots) which is exactly why the id and glyph carry the
 * primary signal.
 */
export function robotColor(robotId: string, theme: "dark" | "light"): string {
  const wheel = theme === "light" ? LIGHT_WHEEL : DARK_WHEEL
  return wheel[hashId(robotId) % wheel.length] ?? wheel[0]
}

export function robotGlyph(robotId: string): string {
  return ROBOT_GLYPHS[hashId(robotId) % ROBOT_GLYPHS.length] ?? "▣"
}

/** Accessible index number printed on the chassis. */
export function robotIndexLabel(robotId: string): string {
  return String((hashId(robotId) % 90) + 10)
}

/** CSS custom property pair for inline use on DOM elements. */
export function robotColorVars(robotId: string, theme: "dark" | "light"): { color: string } {
  return { color: robotColor(robotId, theme) }
}

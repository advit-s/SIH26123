/**
 * Canvas paint tokens.
 *
 * The map reads the same colour slots the DOM uses (via `getComputedStyle` on
 * the theme root), so the canvas can never drift out of sync with the panels —
 * and a theme switch repaints the map with no duplicated palette.
 *
 * Semantics are identical to the CSS layer:
 *   teal = normal coordination, amber = attention / withheld,
 *   red  = confirmed fault, steel = EVALUATOR TRUTH only.
 */
export interface MapPalette {
  slab: string
  grid: string
  paint: string
  rule: string
  ink: string
  inkDim: string
  teal: string
  tealDim: string
  amber: string
  amberDim: string
  red: string
  redDim: string
  steel: string
}

const FALLBACK: MapPalette = {
  slab: "#0d1216",
  grid: "#1a2229",
  paint: "#6f8896",
  rule: "#26313a",
  ink: "#e7eef2",
  inkDim: "#7b8b95",
  teal: "#3ec9b6",
  tealDim: "#1d7a71",
  amber: "#e5ab3d",
  amberDim: "#8a631b",
  red: "#ec5f51",
  redDim: "#93362c",
  steel: "#86abd2",
}

function readVar(styles: CSSStyleDeclaration, name: string, fallback: string): string {
  const value = styles.getPropertyValue(name).trim()
  return value.length > 0 ? value : fallback
}

/** Read the current theme's slots. Called on theme change, never per frame. */
export function readPalette(): MapPalette {
  if (typeof window === "undefined") return FALLBACK
  const styles = getComputedStyle(document.documentElement)
  return {
    slab: readVar(styles, "--nm-slab", FALLBACK.slab),
    grid: readVar(styles, "--nm-grid", FALLBACK.grid),
    paint: readVar(styles, "--nm-paint", FALLBACK.paint),
    rule: readVar(styles, "--nm-rule", FALLBACK.rule),
    ink: readVar(styles, "--nm-ink", FALLBACK.ink),
    inkDim: readVar(styles, "--nm-ink-3", FALLBACK.inkDim),
    teal: readVar(styles, "--nm-teal", FALLBACK.teal),
    tealDim: readVar(styles, "--nm-teal-dim", FALLBACK.tealDim),
    amber: readVar(styles, "--nm-amber", FALLBACK.amber),
    amberDim: readVar(styles, "--nm-amber-dim", FALLBACK.amberDim),
    red: readVar(styles, "--nm-red", FALLBACK.red),
    redDim: readVar(styles, "--nm-red-dim", FALLBACK.redDim),
    steel: readVar(styles, "--nm-steel", FALLBACK.steel),
  }
}

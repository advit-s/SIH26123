/**
 * Local *view* state only.
 *
 * Zustand holds: theme, camera, layer visibility, current selection, and the
 * route. It never holds robot truth, never holds API responses, and never
 * holds anything the server is authoritative for. Server state lives in
 * TanStack Query.
 *
 * Selection is keyed by stable entity *id*, so a refresh that reorders the
 * fleet cannot move the operator's selection — the cockpit must not jump
 * panels per tick.
 */
import { create } from "zustand"

export type Destination = "operations" | "scenarios" | "experiments" | "replays" | "system" | "welcome"
export type InspectorTab = "robot" | "zone" | "task" | "comms" | "events"

export interface Camera {
  /** Metres per pixel is derived; this is metres-per-unit at zoom 1. */
  zoom: number
  /** World coordinate (metres) at the viewport centre. */
  cx: number
  cy: number
}

export interface LayerFlags {
  routes: boolean
  reservations: boolean
  uncertainty: boolean
  observations: boolean
  conflicts: boolean
  /** Steel blue, and only steel blue. This is the evaluator's verdict layer. */
  evaluatorTruth: boolean
  zoneGeometry: boolean
  paint: boolean
}

const DEFAULT_CAMERA: Camera = { zoom: 26, cx: 0, cy: 0 }

export interface ViewState {
  theme: "dark" | "light"
  destination: Destination
  /** Sub-route, e.g. `operations` + `run_id`. */
  routeParam: string | null
  camera: Camera
  cameraDirty: boolean
  layers: LayerFlags
  selection: { kind: "robot" | "zone" | "task"; id: string } | null
  inspectorTab: InspectorTab
  /** Bounded client-side buffers. A multi-hour run must not exhaust memory. */
  eventCap: number
  telemetryCap: number
  reduceMotion: boolean

  setTheme: (theme: "dark" | "light") => void
  toggleTheme: () => void
  navigate: (destination: Destination, routeParam?: string | null) => void
  setCamera: (camera: Camera) => void
  markCameraClean: () => void
  toggleLayer: (layer: keyof LayerFlags) => void
  select: (kind: "robot" | "zone" | "task", id: string) => void
  clearSelection: () => void
  setInspectorTab: (tab: InspectorTab) => void
  setReduceMotion: (value: boolean) => void
}

const THEME_KEY = "niharamesh:theme:v1"
const LAYERS_KEY = "niharamesh:layers:v1"

function readStoredTheme(): "dark" | "light" {
  try {
    const stored = window.localStorage.getItem(THEME_KEY)
    if (stored === "dark" || stored === "light") return stored
  } catch {
    /* private mode / storage disabled — fall through to the default */
  }
  return "dark"
}

function readStoredLayers(): LayerFlags {
  const base: LayerFlags = {
    routes: false,
    reservations: true,
    uncertainty: true,
    observations: false,
    conflicts: true,
    evaluatorTruth: false,
    zoneGeometry: true,
    paint: true,
  }
  try {
    const raw = window.localStorage.getItem(LAYERS_KEY)
    if (!raw) return base
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== "object" || parsed === null) return base
    const merged = { ...base }
    for (const key of Object.keys(base) as (keyof LayerFlags)[]) {
      const v = (parsed as Record<string, unknown>)[key]
      if (typeof v === "boolean") merged[key] = v
    }
    return merged
  } catch {
    return base
  }
}

function persist(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    /* storage disabled — view state simply does not persist */
  }
}

export const useViewStore = create<ViewState>((set) => ({
  theme: readStoredTheme(),
  destination: "welcome",
  routeParam: null,
  camera: DEFAULT_CAMERA,
  cameraDirty: false,
  layers: readStoredLayers(),
  selection: null,
  inspectorTab: "robot",
  // Bounded buffers: 2000 durable events and 6000 telemetry samples is a lot
  // for a browser tab and still several minutes of dense operation.
  eventCap: 2000,
  telemetryCap: 6000,
  reduceMotion: false,

  setTheme: (theme) => {
    persist(THEME_KEY, theme)
    document.documentElement.dataset.theme = theme
    set({ theme })
  },
  toggleTheme: () => {
    const next = useViewStore.getState().theme === "dark" ? "light" : "dark"
    useViewStore.getState().setTheme(next)
  },
  navigate: (destination, routeParam = null) => {
    const hash = routeParam ? `#/${destination}/${routeParam}` : `#/${destination}`
    if (window.location.hash !== hash) window.history.pushState(null, "", hash)
    set({ destination, routeParam })
  },
  setCamera: (camera) => set({ camera, cameraDirty: true }),
  markCameraClean: () => set({ cameraDirty: false }),
  toggleLayer: (layer) =>
    set((state) => {
      const layers = { ...state.layers, [layer]: !state.layers[layer] }
      persist(LAYERS_KEY, JSON.stringify(layers))
      return { layers }
    }),
  select: (kind, id) => set({ selection: { kind, id }, inspectorTab: kind }),
  clearSelection: () => set({ selection: null }),
  setInspectorTab: (tab) => set({ inspectorTab: tab }),
  setReduceMotion: (value) => set({ reduceMotion: value }),
}))

export function parseHash(hash: string): { destination: Destination; param: string | null } {
  const clean = hash.replace(/^#\/?/, "")
  const [head, ...rest] = clean.split("/")
  const known: Destination[] = ["operations", "scenarios", "experiments", "replays", "system", "welcome"]
  const destination = known.includes(head as Destination) ? (head as Destination) : "welcome"
  const param = rest.length > 0 && rest[0] !== undefined ? rest.join("/") : null
  return { destination, param }
}

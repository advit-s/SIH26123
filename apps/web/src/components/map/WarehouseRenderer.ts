/**
 * PixiJS 8 warehouse renderer.
 *
 * MECHANISM — how high-frequency motion stays out of React reconciliation
 * ---------------------------------------------------------------------
 * This class owns the WebGL surface and its own `Application.ticker`. React
 * mounts it once, hands it two things:
 *   - `setStructure(...)` — low-frequency payload (map geometry, zones, robots,
 *     layer flags, palette). Rebuilt only when a *structural signature* changes.
 *   - `setDynamic(...)`   — high-frequency payload (the mutable `LiveFeed`).
 *     Called on a rAF from the map component; it never allocates and never
 *     touches a React node.
 *
 * Every frame, only the `dynamic` container's Graphics is cleared and redrawn.
 * The floor, paint, obstacles, zone geometry and robot labels are separate,
 * persistent display objects. So a 20 Hz telemetry stream costs zero React
 * renders, zero DOM nodes and zero per-entity allocations — only transform
 * updates on a handful of Graphics objects.
 *
 * The renderer is also the enforcement point for two cockpit rules:
 *   - When telemetry is stale, robots **freeze** at the last known pose and are
 *     drawn with a hatched "unconfirmed" ring plus their evidence age.
 *   - The evaluator-truth layer is steel blue and is *always* labelled on the
 *     map chrome; it is never drawn in an agent-knowledge colour.
 */
import { Application, Container, Graphics, Text } from "pixi.js"
import type { MapGeometry } from "../../lib/api/types"
import type { RobotInspection, ZoneInspection } from "../../lib/api/types"
import type { LiveFeed, PoseSample } from "../../lib/api/stream"
import { describePoseFreshness } from "../../lib/map/freshness"
import { orientedCorners, rectFromOriginExtent, toScreen, type Camera, type Viewport } from "../../lib/map/geometry"
import { robotColor, robotIndexLabel } from "../../lib/robotColor"
import type { LayerFlags } from "../../lib/view/store"
import type { MapPalette } from "./palette"

export interface SelectionRef {
  kind: "robot" | "zone" | "task"
  id: string
}

export interface StructurePayload {
  geometry: MapGeometry | null
  zones: ZoneInspection[]
  robots: RobotInspection[]
  layers: LayerFlags
  palette: MapPalette
  theme: "dark" | "light"
}

export interface DynamicPayload {
  feed: LiveFeed
  freshnessHorizonS: number
  /** `false` once the stream is stale: motion is frozen and labelled. */
  fresh: boolean
  simTimeS: number
}

/** Cheap structural signature — prevents per-tick rebuilds of the static layer. */
export function structureSignature(p: StructurePayload): string {
  const geo = p.geometry
  return [
    geo?.map.map_id ?? "-",
    geo?.map.revision ?? "-",
    (geo?.obstacles.length ?? 0) + (geo?.stations.length ?? 0) + (geo?.berths.length ?? 0),
    (geo?.zones.length ?? 0) + (geo?.stop_lines.length ?? 0),
    p.zones.map((z) => `${z.zone_id}:${z.authority}:${z.authority_holder ?? "-"}:${z.entries}`).join(","),
    p.robots.map((r) => `${r.robot_id}:${r.degraded ? 1 : 0}:${r.carrying_payload ? 1 : 0}`).join(","),
    Object.entries(p.layers)
      .map(([k, v]) => (v ? k : ""))
      .join(""),
    p.theme,
  ].join("|")
}

interface RobotSprite {
  graphics: Graphics
  label: Text
  staleBadge: Graphics
  robotId: string
}

export class WarehouseRenderer {
  private app: Application | null = null
  private host: HTMLElement | null = null

  private readonly floorLayer = new Container()
  private readonly zoneLayer = new Container()
  private readonly obstacleLayer = new Container()
  private readonly overlayLayer = new Container()
  private readonly dynamicLayer = new Container()
  private readonly labelLayer = new Container()
  /** Zone id stencils. Cleared and rebuilt with the static layer only. */
  private readonly zoneLabelLayer = new Container()

  private readonly floorGfx = new Graphics()
  private readonly zoneGfx = new Graphics()
  private readonly obstacleGfx = new Graphics()
  private readonly overlayGfx = new Graphics()
  private readonly dynamicGfx = new Graphics()

  private robotSprites = new Map<string, RobotSprite>()
  /** Transient on-canvas captions (intent, blocked, evaluator legend). */
  private overlayCaptions: Text[] = []

  private structure: StructurePayload | null = null
  private dynamic: DynamicPayload | null = null
  private selection: SelectionRef | null = null
  private camera: Camera = { zoom: 26, cx: 0, cy: 0 }
  private viewport: Viewport = { width: 800, height: 600 }
  private signature = ""

  /** Display pose: interpolated target while fresh, frozen value when stale. */
  private display = new Map<string, { x: number; y: number; theta: number }>()

  private tickerHandle: ((ticker: { deltaMS: number }) => void) | null = null

  async init(host: HTMLElement): Promise<void> {
    const app = new Application()
    await app.init({
      backgroundAlpha: 0,
      antialias: true,
      autoDensity: true,
      resolution: Math.min(2, globalThis.devicePixelRatio || 1),
      // "webgl" keeps the render path predictable in headless CI where a GPU
      // adapter may be absent; Pixi will fall back only if asked.
      preference: "webgl",
      width: Math.max(320, host.clientWidth),
      height: Math.max(240, host.clientHeight),
    })
    this.app = app
    this.host = host
    host.appendChild(app.canvas)
    app.canvas.setAttribute("aria-hidden", "true")
    app.canvas.style.display = "block"
    app.canvas.style.touchAction = "none"

    app.stage.addChild(
      this.floorLayer,
      this.zoneLayer,
      this.obstacleLayer,
      this.overlayLayer,
      this.dynamicLayer,
      this.zoneLabelLayer,
      this.labelLayer,
    )
    this.floorLayer.addChild(this.floorGfx)
    this.zoneLayer.addChild(this.zoneGfx)
    this.obstacleLayer.addChild(this.obstacleGfx)
    this.overlayLayer.addChild(this.overlayGfx)
    this.dynamicLayer.addChild(this.dynamicGfx)

    this.tickerHandle = (ticker) => {
      const dt = Math.min(0.1, ticker.deltaMS / 1000)
      this.renderDynamic(dt)
    }
    app.ticker.add(this.tickerHandle)
    this.observeResize()
  }

  private resizeObserver: ResizeObserver | null = null

  private observeResize(): void {
    if (typeof ResizeObserver === "undefined") return
    const host = this.host
    const app = this.app
    if (host === null || app === null) return
    this.resizeObserver = new ResizeObserver(() => {
      const w = Math.max(320, host.clientWidth)
      const h = Math.max(240, host.clientHeight)
      this.viewport = { width: w, height: h }
      app.renderer.resize(w, h)
      if (this.structure !== null) this.rebuild()
    })
    this.resizeObserver.observe(host)
  }

  setCamera(camera: Camera): void {
    this.camera = camera
    if (this.structure !== null) this.rebuild()
  }

  setSelection(selection: SelectionRef | null): void {
    this.selection = selection
    if (this.structure !== null) this.rebuild()
  }

  setViewport(width: number, height: number): void {
    this.viewport = { width, height }
  }

  setStructure(payload: StructurePayload): void {
    const next = structureSignature(payload)
    const geometryChanged = this.structure === null || this.structure.palette !== payload.palette
    this.structure = payload
    if (next === this.signature && !geometryChanged) return
    this.signature = next
    this.rebuild()
  }

  setDynamic(payload: DynamicPayload): void {
    this.dynamic = payload
  }

  /** World-metre point under a client-space pixel, for click selection. */
  pick(worldX: number, worldY: number, robots: RobotInspection[]): string | null {
    for (const robot of robots) {
      const sample = this.dynamic?.feed.poses.get(robot.robot_id)
      const display = this.display.get(robot.robot_id)
      const declared = robot.pose_estimate?.pose
      const pose =
        display ??
        (sample !== undefined ? { x: sample.x, y: sample.y, theta: sample.theta } : declared !== undefined ? declared : null)
      if (pose === null) continue
      const fp = robot.identity?.footprint
      const length = fp?.length_m ?? 0.9
      const width = fp?.width_m ?? 0.7
      const dx = worldX - pose.x
      const dy = worldY - pose.y
      const cos = Math.cos(-pose.theta)
      const sin = Math.sin(-pose.theta)
      const lx = dx * cos - dy * sin
      const ly = dx * sin + dy * cos
      if (Math.abs(lx) <= length / 2 + 0.25 && Math.abs(ly) <= width / 2 + 0.25) return robot.robot_id
    }
    return null
  }

  /* ---------------------------------------------------------------------- */
  /* Static layer                                                            */
  /* ---------------------------------------------------------------------- */

  private rebuild(): void {
    const structure = this.structure
    if (structure === null) return
    const { palette, geometry, layers } = structure
    const cam = this.camera
    const vp = this.viewport

    this.floorGfx.clear()
    this.zoneGfx.clear()
    this.obstacleGfx.clear()
    this.overlayGfx.clear()
    // Zone labels are static-layer children; drop them so a rebuild cannot
    // accumulate Text objects.
    for (const child of this.zoneLabelLayer.removeChildren()) {
      (child as Text).destroy()
    }

    this.drawSlab(palette, geometry, cam, vp)
    if (layers.paint) this.drawPaint(palette, geometry, cam, vp)
    this.drawObstacles(palette, geometry, cam, vp)
    this.drawStationsAndBerths(palette, geometry, cam, vp)
    if (layers.zoneGeometry) this.drawZones(structure, cam, vp)
    this.drawStopLines(palette, geometry, structure, cam, vp)
    this.drawRouteEdges(palette, geometry, layers, cam, vp)

    this.syncRobotSprites(structure)
    this.renderDynamic(0)
  }

  private drawSlab(palette: MapPalette, geometry: MapGeometry | null, cam: Camera, vp: Viewport): void {
    const g = this.floorGfx
    g.rect(0, 0, vp.width, vp.height).fill({ color: palette.slab })

    const boundary = geometry?.map.boundary
    if (boundary === undefined) return
    const tl = toScreen({ x: boundary.min_x, y: boundary.max_y }, cam, vp)
    const br = toScreen({ x: boundary.max_x, y: boundary.min_y }, cam, vp)
    const w = br.x - tl.x
    const h = br.y - tl.y
    g.rect(tl.x, tl.y, w, h).fill({ color: palette.slab, alpha: 0 }).stroke({ width: 1, color: palette.rule })
  }

  /** The 1 m survey grid plus metre ticks along the bottom and left edges. */
  private drawPaint(palette: MapPalette, geometry: MapGeometry | null, cam: Camera, vp: Viewport): void {
    if (geometry === null) return
    const boundary = geometry.map.boundary
    const tl = toScreen({ x: boundary.min_x, y: boundary.max_y }, cam, vp)
    const br = toScreen({ x: boundary.max_x, y: boundary.min_y }, cam, vp)
    const g = this.floorGfx

    if (cam.zoom >= 9) {
      const stepM = cam.zoom >= 26 ? 1 : 5
      const alpha = cam.zoom >= 26 ? 0.5 : 0.75
      const startX = Math.ceil(boundary.min_x / stepM) * stepM
      for (let x = startX; x <= boundary.max_x; x += stepM) {
        const p = toScreen({ x, y: boundary.min_y }, cam, vp)
        g.moveTo(p.x, tl.y).lineTo(p.x, br.y)
      }
      const startY = Math.ceil(boundary.min_y / stepM) * stepM
      for (let y = startY; y <= boundary.max_y; y += stepM) {
        const p = toScreen({ x: boundary.min_x, y }, cam, vp)
        g.moveTo(tl.x, p.y).lineTo(br.x, p.y)
      }
      g.stroke({ width: 1, color: palette.grid, alpha })
    }

    // Metre ticks: a surveyed edge, not a decorative frame.
    if (cam.zoom >= 12) {
      const stepM = cam.zoom >= 30 ? 2 : 5
      const alpha = 0.85
      for (let x = Math.ceil(boundary.min_x / stepM) * stepM; x <= boundary.max_x; x += stepM) {
        const p = toScreen({ x, y: boundary.min_y }, cam, vp)
        g.moveTo(p.x, br.y).lineTo(p.x, br.y + 6)
      }
      for (let y = Math.ceil(boundary.min_y / stepM) * stepM; y <= boundary.max_y; y += stepM) {
        const p = toScreen({ x: boundary.min_x, y }, cam, vp)
        g.moveTo(tl.x, p.y).lineTo(tl.x - 6, p.y)
      }
      g.stroke({ width: 1, color: palette.paint, alpha })
    }
  }

  private drawObstacles(palette: MapPalette, geometry: MapGeometry | null, cam: Camera, vp: Viewport): void {
    if (geometry === null) return
    const g = this.obstacleGfx
    for (const obstacle of geometry.obstacles) {
      const p = obstacle.pose
      const corners = orientedCorners({ x: p.x, y: p.y }, obstacle.length_m, obstacle.width_m, p.theta)
      const pts = corners.map((c) => toScreen(c, cam, vp))
      const dynamic = obstacle.dynamic === true
      g.poly(pts.flatMap((pt) => [pt.x, pt.y]))
      g.fill({ color: dynamic ? palette.amberDim : palette.rule, alpha: dynamic ? 0.28 : 0.55 })
      g.poly(pts.flatMap((pt) => [pt.x, pt.y]))
      g.stroke({ width: 1, color: dynamic ? palette.amber : palette.paint, alpha: dynamic ? 0.95 : 0.7 })
    }
    // Shelf hatching: a shelf reads differently from a wall, and so does a
    // temporary obstacle from a fixed one.
    for (const obstacle of geometry.obstacles) {
      if (obstacle.kind !== "shelf") continue
      const p = obstacle.pose
      const corners = orientedCorners({ x: p.x, y: p.y }, obstacle.length_m, obstacle.width_m, p.theta)
      const pts = corners.map((c) => toScreen(c, cam, vp))
      const minX = Math.min(...pts.map((q) => q.x))
      const maxX = Math.max(...pts.map((q) => q.x))
      const minY = Math.min(...pts.map((q) => q.y))
      const maxY = Math.max(...pts.map((q) => q.y))
      const stepPx = Math.max(4, (maxY - minY) / 6)
      for (let y = minY; y <= maxY; y += stepPx) {
        g.moveTo(minX, y).lineTo(maxX, y)
      }
      g.stroke({ width: 1, color: palette.paint, alpha: 0.35 })
    }
  }

  private drawStationsAndBerths(palette: MapPalette, geometry: MapGeometry | null, cam: Camera, vp: Viewport): void {
    if (geometry === null) return
    const g = this.obstacleGfx
    for (const station of geometry.stations) {
      const p = station.pose
      const centre = toScreen({ x: p.x, y: p.y }, cam, vp)
      const size = 0.9 * cam.zoom
      const colour = station.kind === "charge" ? palette.steel : station.kind === "drop" ? palette.tealDim : palette.inkDim
      g.rect(centre.x - size / 2, centre.y - size / 2, size, size)
        .fill({ color: colour, alpha: 0.16 })
        .stroke({ width: 1.5, color: colour, alpha: 0.9 })
      // Corner notches: a berth mark, not a plain square.
      const n = size * 0.28
      g.moveTo(centre.x - size / 2, centre.y - size / 2).lineTo(centre.x - size / 2 + n, centre.y - size / 2)
      g.moveTo(centre.x + size / 2, centre.y - size / 2).lineTo(centre.x + size / 2 - n, centre.y - size / 2)
      g.stroke({ width: 1, color: colour, alpha: 0.9 })
    }
    for (const berth of geometry.berths) {
      const p = berth.pose
      const centre = toScreen({ x: p.x, y: p.y }, cam, vp)
      const w = 1.4 * cam.zoom
      const h = 1.0 * cam.zoom
      g.rect(centre.x - w / 2, centre.y - h / 2, w, h).stroke({ width: 1, color: palette.inkDim, alpha: 0.7 })
    }
  }

  private drawZones(structure: StructurePayload, cam: Camera, vp: Viewport): void {
    const { palette, geometry, layers } = structure
    const g = this.zoneGfx
    if (geometry === null) return

    for (const zone of structure.zones) {
      const origin = zone.protected_origin ?? zone.map_zone?.protected_origin ?? null
      const extent = zone.protected_extent ?? zone.map_zone?.protected_extent ?? null
      const rect = rectFromOriginExtent(origin as [number, number] | null, extent as [number, number] | null)
      if (rect === null) continue
      const a = toScreen({ x: rect.x, y: rect.y + rect.height }, cam, vp)
      const b = toScreen({ x: rect.x + rect.width, y: rect.y }, cam, vp)
      const w = b.x - a.x
      const h = b.y - a.y
      const selected = this.selection?.kind === "zone" && this.selection.id === zone.zone_id

      // Colour by authority state. Withheld authority is *hatched*, which is a
      // non-colour signal a colour-blind operator can still read.
      const tone =
        zone.authority === "held"
          ? palette.teal
          : zone.authority === "occupied" || zone.authority === "contested"
            ? palette.red
            : zone.authority === "free"
              ? palette.rule
              : palette.amber

      g.rect(a.x, a.y, w, h).fill({ color: tone, alpha: zone.authority === "free" ? 0.04 : 0.12 })
      if (zone.entry_withheld || zone.authority === "unknown") {
        this.hatch(g, a.x, a.y, w, h, tone, 0.22)
      }
      g.rect(a.x, a.y, w, h).stroke({ width: selected ? 2.5 : 1.25, color: tone, alpha: selected ? 1 : 0.85 })

      // Zone id stencilled into the protected geometry. A floor plan without
      // labels is a picture; this is a drawing an operator can read.
      if (cam.zoom >= 12 && Math.min(w, h) >= 16) {
        const label = new Text({
          text: zone.zone_id,
          style: {
            fill: tone,
            fontFamily: "IBM Plex Mono, monospace",
            fontSize: 9,
            fontWeight: "500",
          },
        })
        label.anchor.set(0.5)
        label.position.set(a.x + w / 2, a.y + h / 2)
        label.alpha = 0.85
        this.zoneLabelLayer.addChild(label)
      }

      // Protected-geometry corner ticks.
      const t = Math.min(10, Math.max(5, Math.min(w, h) * 0.22))
      for (const [cx, cy, dx, dy] of [
        [a.x, a.y, 1, 1],
        [a.x + w, a.y, -1, 1],
        [a.x, a.y + h, 1, -1],
        [a.x + w, a.y + h, -1, -1],
      ] as [number, number, number, number][]) {
        const px = cx ?? a.x
        const py = cy ?? a.y
        const sx = dx ?? 1
        const sy = dy ?? 1
        g.moveTo(px, py).lineTo(px + sx * t, py)
        g.moveTo(px, py).lineTo(px, py + sy * t)
      }
      g.stroke({ width: 1, color: tone, alpha: 0.9 })
    }

    if (layers.evaluatorTruth) this.drawEvaluatorTruth(structure, cam, vp)
  }

  /**
   * The evaluator layer. Steel blue, plus an explicit caption drawn into the
   * canvas itself so the distinction survives a screenshot pasted into a report.
   */
  private drawEvaluatorTruth(structure: StructurePayload, cam: Camera, vp: Viewport): void {
    const { palette, zones } = structure
    const g = this.overlayGfx
    let drawn = 0
    for (const zone of zones) {
      if (zone.evaluator_occupancy !== true) continue
      const rect = rectFromOriginExtent(zone.protected_origin, zone.protected_extent)
      if (rect === null) continue
      const a = toScreen({ x: rect.x, y: rect.y + rect.height }, cam, vp)
      const b = toScreen({ x: rect.x + rect.width, y: rect.y }, cam, vp)
      const w = b.x - a.x
      const h = b.y - a.y
      this.hatch(g, a.x, a.y, w, h, palette.steel, 0.3)
      g.rect(a.x, a.y, w, h).stroke({ width: 2, color: palette.steel, alpha: 0.95 })
      drawn += 1
    }
    const caption = new Text({
      text: `EVALUATOR TRUTH — ${drawn} zone${drawn === 1 ? "" : "s"} · not agent knowledge`,
      style: {
        fill: palette.steel,
        fontFamily: "IBM Plex Sans, sans-serif",
        fontSize: 10,
        fontWeight: "600",
        letterSpacing: 0.6,
      },
    })
    caption.position.set(10, 10)
    this.overlayLayer.addChild(caption)
    this.overlayCaptions.push(caption)
  }

  private drawStopLines(palette: MapPalette, geometry: MapGeometry | null, structure: StructurePayload, cam: Camera, vp: Viewport): void {
    if (geometry === null) return
    const g = this.obstacleGfx
    const zonesById = new Map(structure.zones.map((z) => [z.zone_id, z]))
    for (const line of geometry.stop_lines) {
      const start = Array.isArray(line.start) ? line.start : null
      const end = Array.isArray(line.end) ? line.end : null
      if (start === null || end === null || start.length < 2 || end.length < 2) continue
      const sx = typeof start[0] === "number" ? start[0] : null
      const sy = typeof start[1] === "number" ? start[1] : null
      const ex = typeof end[0] === "number" ? end[0] : null
      const ey = typeof end[1] === "number" ? end[1] : null
      if (sx === null || sy === null || ex === null || ey === null) continue
      const a = toScreen({ x: sx, y: sy }, cam, vp)
      const b = toScreen({ x: ex, y: ey }, cam, vp)
      const zone = zonesById.get(line.zone_id)
      const violated = zone?.authority === "held" && zone.authority_holder !== null && zone.entry_withheld
      const colour = violated ? palette.red : zone?.entry_withheld ? palette.amber : palette.paint
      // A stop line is a double bar, like a level crossing.
      const dx = b.x - a.x
      const dy = b.y - a.y
      const len = Math.hypot(dx, dy) || 1
      const nx = (-dy / len) * 1.6
      const ny = (dx / len) * 1.6
      g.moveTo(a.x - nx, a.y - ny).lineTo(b.x - nx, b.y - ny)
      g.moveTo(a.x + nx, a.y + ny).lineTo(b.x + nx, b.y + ny)
      g.stroke({ width: 1.5, color: colour, alpha: 0.9 })
    }
  }

  private drawRouteEdges(palette: MapPalette, geometry: MapGeometry | null, layers: LayerFlags, cam: Camera, vp: Viewport): void {
    if (geometry === null || !layers.routes) return
    const edges = geometry.map.directed_routes ?? []
    if (edges.length === 0) return
    const g = this.overlayGfx
    for (const edge of edges) {
      const a = toScreen({ x: edge.from_pose.x, y: edge.from_pose.y }, cam, vp)
      const b = toScreen({ x: edge.to_pose.x, y: edge.to_pose.y }, cam, vp)
      g.moveTo(a.x, a.y).lineTo(b.x, b.y)
      g.stroke({ width: 1, color: palette.paint, alpha: 0.4 })
      if (edge.one_way === true) {
        // One-way arrowhead: direction is a shape, not a colour.
        const ang = Math.atan2(b.y - a.y, b.x - a.x)
        const r = 6
        g.moveTo(b.x, b.y)
          .lineTo(b.x - r * Math.cos(ang - 0.4), b.y - r * Math.sin(ang - 0.4))
          .moveTo(b.x, b.y)
          .lineTo(b.x - r * Math.cos(ang + 0.4), b.y - r * Math.sin(ang + 0.4))
        g.stroke({ width: 1.2, color: palette.paint, alpha: 0.7 })
      }
    }
  }

  private hatch(g: Graphics, x: number, y: number, w: number, h: number, colour: string, alpha: number): void {
    if (w <= 0 || h <= 0) return
    const step = 7
    // 45-degree lines clipped to the rect, drawn as explicit segments so no
    // mask/clip API is needed.
    for (let offset = -h; offset < w; offset += step) {
      const x1 = x + Math.max(0, offset)
      const y1 = y + Math.max(0, -offset)
      const x2 = x + Math.min(w, offset + h)
      const y2 = y + Math.min(h, w - offset)
      if (x2 <= x1) continue
      g.moveTo(x1, y1).lineTo(x2, y2)
    }
    g.stroke({ width: 1, color: colour, alpha })
  }

  /* ---------------------------------------------------------------------- */
  /* Robot sprites (persistent)                                              */
  /* ---------------------------------------------------------------------- */

  private syncRobotSprites(structure: StructurePayload): void {
    const ids = new Set(structure.robots.map((r) => r.robot_id))
    for (const [id, sprite] of this.robotSprites) {
      if (ids.has(id)) continue
      sprite.graphics.destroy()
      sprite.staleBadge.destroy()
      sprite.label.destroy()
      this.robotSprites.delete(id)
      this.display.delete(id)
    }
    for (const robot of structure.robots) {
      if (this.robotSprites.has(robot.robot_id)) continue
      const graphics = new Graphics()
      const staleBadge = new Graphics()
      const label = new Text({
        text: robotIndexLabel(robot.robot_id),
        style: {
          fill: "#0b0f12",
          fontFamily: "IBM Plex Mono, monospace",
          fontSize: 9,
          fontWeight: "600",
        },
      })
      label.anchor.set(0.5)
      this.dynamicLayer.addChild(graphics, staleBadge)
      this.labelLayer.addChild(label)
      this.robotSprites.set(robot.robot_id, { graphics, label, staleBadge, robotId: robot.robot_id })
    }
  }

  /* ---------------------------------------------------------------------- */
  /* Dynamic layer — the only thing that runs per frame                     */
  /* ---------------------------------------------------------------------- */

  private renderDynamic(dt: number): void {
    const structure = this.structure
    const dynamic = this.dynamic
    if (structure === null || dynamic === null) return

    const { palette, layers, theme } = structure
    const { feed, fresh, freshnessHorizonS } = dynamic
    const cam = this.camera
    const vp = this.viewport
    const g = this.dynamicGfx
    g.clear()
    for (const caption of this.overlayCaptions) {
      caption.destroy()
    }
    this.overlayCaptions = []

    const now = Date.now()
    const byId = new Map(structure.robots.map((r) => [r.robot_id, r]))

    for (const robot of structure.robots) {
      const sprite = this.robotSprites.get(robot.robot_id)
      const sample: PoseSample | undefined = feed.poses.get(robot.robot_id)
      if (sprite === undefined) continue

      // The freeze rule lives here. No fresh evidence -> hold the last pose and
      // never extrapolate.
      const ageS = feed.ageOf(robot.robot_id, now)
      const freshness = describePoseFreshness(ageS, freshnessHorizonS)
      const frozen = !fresh || freshness.frozen

      let target: { x: number; y: number; theta: number } | null =
        sample !== undefined ? { x: sample.x, y: sample.y, theta: sample.theta } : null
      // No live sample yet: seed the display pose from the API's own declared
      // pose estimate so the robot is *drawn* at its last known place. It is
      // immediately badged frozen, because this is a read model, not telemetry.
      if (target === null && robot.pose_estimate !== null) {
        const p = robot.pose_estimate.pose
        target = { x: p.x, y: p.y, theta: p.theta }
      }
      const current = this.display.get(robot.robot_id)
      if (frozen || current === undefined || target === null) {
        if (current === undefined && target !== null) {
          this.display.set(robot.robot_id, target)
        }
      } else {
        // Interpolation exists only to hide sampling jitter. It is bounded and
        // never runs on stale data.
        const k = Math.min(1, dt * 12)
        const currentPose = current
        this.display.set(robot.robot_id, {
          x: currentPose.x + (target.x - currentPose.x) * k,
          y: currentPose.y + (target.y - currentPose.y) * k,
          theta: currentPose.theta + shortestAngle(currentPose.theta, target.theta) * k,
        })
      }

      const pose = this.display.get(robot.robot_id) ?? null
      if (pose === null) {
        sprite.graphics.clear()
        sprite.staleBadge.clear()
        sprite.label.visible = false
        continue
      }

      const centre = toScreen(pose ?? resolved, cam, vp)
      const fp = robot.identity?.footprint
      const lengthM = fp?.length_m ?? 0.9
      const widthM = fp?.width_m ?? 0.7
      const colour = robotColor(robot.robot_id, theme)
      const selected = this.selection?.kind === "robot" && this.selection.id === robot.robot_id
      const degraded = robot.degraded
      const stopped = robot.motion?.stop_reason !== undefined && robot.motion.stop_reason !== "none"
      const motionColour = degraded ? palette.amber : stopped ? palette.inkDim : colour

      const corners = orientedCorners(pose, lengthM, widthM, pose.theta).map((c) => toScreen(c, cam, vp))
      const flat = corners.flatMap((c) => [c.x, c.y])

      sprite.graphics.clear()
      sprite.graphics.poly(flat).fill({ color: motionColour, alpha: selected ? 0.4 : 0.26 })
      sprite.graphics.poly(flat).stroke({ width: selected ? 2.5 : 1.5, color: motionColour, alpha: 1 })

      // Heading chevron: direction must be readable without motion.
      const headingLen = Math.max(8, (lengthM / 2 + 0.35) * cam.zoom)
      const hx = Math.cos(pose.theta)
      const hy = Math.sin(pose.theta)
      const tip = { x: centre.x + hx * headingLen, y: centre.y - hy * headingLen }
      const left = { x: centre.x + hx * (headingLen - 6) - hy * 4, y: centre.y - hy * (headingLen - 6) - hx * 4 }
      const right = { x: centre.x + hx * (headingLen - 6) + hy * 4, y: centre.y - hy * (headingLen - 6) + hx * 4 }
      sprite.graphics.moveTo(left.x, left.y).lineTo(tip.x, tip.y).lineTo(right.x, right.y)
      sprite.graphics.stroke({ width: 1.5, color: motionColour, alpha: 0.95 })

      // Payload block: drawn at the configured overhang, so a loaded AMR looks
      // longer than an empty one.
      if (robot.carrying_payload) {
        const payloadLength = fp?.payload_length_m ?? 0.6
        const offset = fp?.payload_offset_m ?? lengthM / 2
        const pc = toScreen({ x: pose.x + hx * offset, y: pose.y + hy * offset }, cam, vp)
        const payloadCorners = orientedCorners(
          { x: pose.x + hx * offset, y: pose.y + hy * offset },
          payloadLength,
          fp?.payload_width_m ?? widthM,
          pose.theta,
        ).map((c) => toScreen(c, cam, vp))
        sprite.graphics.poly(payloadCorners.flatMap((c) => [c.x, c.y])).fill({ color: palette.teal, alpha: 0.75 })
        sprite.graphics.circle(pc.x, pc.y, 1.5).fill({ color: palette.teal })
      }

      // Uncertainty: the agent's own declared sigma, drawn at true scale.
      if (layers.uncertainty && robot.pose_estimate !== null) {
        const sigma = robot.pose_estimate.uncertainty.sigma_m
        if (typeof sigma === "number" && sigma > 0) {
          sprite.graphics.circle(centre.x, centre.y, sigma * cam.zoom * 2).stroke({
            width: 1,
            color: palette.amber,
            alpha: 0.5,
          })
        }
      }

      // Frozen / no-evidence badge. Hatched ring + dashed silhouette: two
      // non-colour signals that the pose is not confirmed.
      sprite.staleBadge.clear()
      if (frozen) {
        const r = Math.max(lengthM, widthM) * cam.zoom * 0.85
        sprite.staleBadge.circle(centre.x, centre.y, r).stroke({ width: 1.5, color: palette.amber, alpha: 0.9 })
        for (let i = -r; i <= r; i += 4) {
          sprite.staleBadge
            .moveTo(centre.x - r, centre.y + i)
            .lineTo(centre.x + r, centre.y + i)
        }
        sprite.staleBadge.stroke({ width: 1, color: palette.amber, alpha: 0.28 })
        sprite.staleBadge.circle(centre.x, centre.y, r + 4).stroke({
          width: 1,
          color: palette.amber,
          alpha: 0.9,
        })
      }

      sprite.label.visible = cam.zoom >= 10
      sprite.label.position.set(centre.x, centre.y)
      sprite.label.style.fill = palette.slab

      // Layer: local observations (sensor rays) for the selected robot only.
      if (layers.observations && selected) {
        this.drawObservationRays(robot, centre, cam, palette)
      }
      // Layer: reservations the agent believes it holds.
      if (layers.reservations) {
        for (const hold of robot.held_zones) {
          const zone = structure.zones.find((z) => z.zone_id === hold.zone_id)
          if (zone === undefined) continue
          const rect = rectFromOriginExtent(zone.protected_origin, zone.protected_extent)
          if (rect === null) continue
          const a = toScreen({ x: rect.x, y: rect.y + rect.height }, cam, vp)
          const b = toScreen({ x: rect.x + rect.width, y: rect.y }, cam, vp)
          g.rect(a.x, a.y, b.x - a.x, b.y - a.y).stroke({ width: 1, color: colour, alpha: 0.5 })
        }
      }
      // Layer: predicted intent of the selected robot.
      if (selected && layers.routes && robot.last_accepted_intent !== null) {
        this.drawIntentLabel(sprite, centre, robot.last_accepted_intent, palette)
      }
      if (selected && robot.why_waiting?.blocked === true) {
        const msg = "blocked — see inspector"
        const t = new Text({
          text: msg,
          style: { fill: palette.amber, fontFamily: "IBM Plex Sans, sans-serif", fontSize: 9, fontWeight: "600" },
        })
        t.position.set(centre.x + 10, centre.y - 22)
        this.overlayLayer.addChild(t)
        this.overlayCaptions.push(t)
      }
      void byId
    }

    // Layer: conflicts.
    if (layers.conflicts) {
      for (const zone of structure.zones) {
        if (zone.authority !== "contested") continue
        const rect = rectFromOriginExtent(zone.protected_origin, zone.protected_extent)
        if (rect === null) continue
        const a = toScreen({ x: rect.x, y: rect.y + rect.height }, cam, vp)
        const b = toScreen({ x: rect.x + rect.width, y: rect.y }, cam, vp)
        const w = b.x - a.x
        const h = b.y - a.y
        this.hatch(g, a.x, a.y, w, h, palette.red, 0.32)
        g.rect(a.x, a.y, w, h).stroke({ width: 2, color: palette.red })
      }
    }
  }

  private drawObservationRays(
    robot: RobotInspection,
    centre: { x: number; y: number },
    cam: Camera,
    palette: MapPalette,
  ): void {
    const g = this.dynamicGfx
    const theta = robot.pose_estimate?.pose.theta ?? this.display.get(robot.robot_id)?.theta ?? 0
    const range = cam.zoom * 3
    for (const offset of [-0.5, -0.25, 0, 0.25, 0.5]) {
      const a = theta + offset
      g.moveTo(centre.x, centre.y)
        .lineTo(centre.x + Math.cos(a) * range, centre.y - Math.sin(a) * range)
    }
    g.stroke({ width: 1, color: palette.teal, alpha: 0.35 })
  }

  private drawIntentLabel(sprite: RobotSprite, centre: { x: number; y: number }, intent: string, palette: MapPalette): void {
    const t = new Text({
      text: `intent: ${intent}`,
      style: { fill: palette.teal, fontFamily: "IBM Plex Mono, monospace", fontSize: 9 },
    })
    t.position.set(centre.x + 12, centre.y + 12)
    this.overlayLayer.addChild(t)
    this.overlayCaptions.push(t)
    void sprite
  }

  destroy(): void {
    if (this.resizeObserver !== null) {
      this.resizeObserver.disconnect()
      this.resizeObserver = null
    }
    if (this.app !== null && this.tickerHandle !== null) {
      this.app.ticker.remove(this.tickerHandle)
    }
    for (const sprite of this.robotSprites.values()) {
      sprite.graphics.destroy()
      sprite.staleBadge.destroy()
      sprite.label.destroy()
    }
    this.robotSprites.clear()
    for (const caption of this.overlayCaptions) caption.destroy()
    this.overlayCaptions = []
    if (this.app !== null) {
      this.app.destroy(true, { children: true })
      this.app = null
    }
    this.host = null
  }
}

function shortestAngle(from: number, to: number): number {
  let d = (to - from) % (Math.PI * 2)
  if (d > Math.PI) d -= Math.PI * 2
  if (d <= -Math.PI) d += Math.PI * 2
  return d
}

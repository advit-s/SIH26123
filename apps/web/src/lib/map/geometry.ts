/**
 * Map geometry. Pure functions only — no Pixi, no DOM. Everything here is
 * unit-testable and is the single place where world metres become screen
 * pixels, so the map can never disagree with the scale bar or the legend.
 *
 * Conventions:
 *   - World space is metres, +x right, +y up (maths), matching the contracts.
 *   - Screen space is CSS pixels, +y down.
 *   - `zoom` is **pixels per metre**. It is the only scale factor in the app.
 */

export interface Viewport {
  width: number
  height: number
}

export interface Camera {
  zoom: number
  cx: number
  cy: number
}

export interface Boundary {
  min_x: number
  min_y: number
  max_x: number
  max_y: number
}

export const MIN_ZOOM = 3
export const MAX_ZOOM = 160

export interface Point {
  x: number
  y: number
}

export function clampZoom(zoom: number): number {
  if (!Number.isFinite(zoom)) return MIN_ZOOM
  return Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom))
}

export function toScreen(world: Point, camera: Camera, viewport: Viewport): Point {
  return {
    x: (world.x - camera.cx) * camera.zoom + viewport.width / 2,
    y: viewport.height / 2 - (world.y - camera.cy) * camera.zoom,
  }
}

export function toWorld(screen: Point, camera: Camera, viewport: Viewport): Point {
  return {
    x: (screen.x - viewport.width / 2) / camera.zoom + camera.cx,
    y: (viewport.height / 2 - screen.y) / camera.zoom + camera.cy,
  }
}

/** Metres per pixel. */
export function metresPerPixel(camera: Camera): number {
  return 1 / clampZoom(camera.zoom)
}

export function fitCamera(boundary: Boundary, viewport: Viewport, paddingPx = 48): Camera {
  const widthM = Math.max(0.001, boundary.max_x - boundary.min_x)
  const heightM = Math.max(0.001, boundary.max_y - boundary.min_y)
  const usableW = Math.max(64, viewport.width - paddingPx * 2)
  const usableH = Math.max(64, viewport.height - paddingPx * 2)
  const zoom = clampZoom(Math.min(usableW / widthM, usableH / heightM))
  return {
    zoom,
    cx: (boundary.min_x + boundary.max_x) / 2,
    cy: (boundary.min_y + boundary.max_y) / 2,
  }
}

/** Pan in metres while keeping the cursor anchored to the same world point. */
export function panCamera(camera: Camera, viewport: Viewport, fromScreen: Point, toScreen: Point): Camera {
  const anchor = toWorld(fromScreen, camera, viewport)
  const moved = toWorld(toScreen, camera, viewport)
  return { ...camera, cx: camera.cx + (anchor.x - moved.x), cy: camera.cy + (anchor.y - moved.y) }
}

/** Zoom about a fixed screen point so the world under the cursor stays put. */
export function zoomCamera(camera: Camera, viewport: Viewport, atScreen: Point, factor: number): Camera {
  const before = toWorld(atScreen, camera, viewport)
  const zoom = clampZoom(camera.zoom * factor)
  const next: Camera = { ...camera, zoom }
  const after = toWorld(atScreen, next, viewport)
  return { zoom, cx: next.cx + (before.x - after.x), cy: next.cy + (before.y - after.y) }
}

/**
 * Scale bar: the largest 1/2/5 x 10^n metre length whose on-screen width stays
 * inside [minPx, maxPx]. The label always states real metres, never "zoom".
 */
export function scaleBar(camera: Camera, minPx = 70, maxPx = 150): { metres: number; px: number } {
  const targetPx = (minPx + maxPx) / 2
  const rawMetres = targetPx * metresPerPixel(camera)
  const magnitude = 10 ** Math.floor(Math.log10(Math.max(1e-6, rawMetres)))
  const normalised = rawMetres / magnitude
  const step = normalised >= 5 ? 5 : normalised >= 2 ? 2 : 1
  const metres = step * magnitude
  return { metres, px: metres * clampZoom(camera.zoom) }
}

/** Axis-aligned rectangle from a zone's protected origin + extent. */
export function rectFromOriginExtent(
  origin: [number, number] | null,
  extent: [number, number] | null,
): { x: number; y: number; width: number; height: number } | null {
  if (origin === null || extent === null) return null
  const [ox, oy] = origin
  const [w, h] = extent
  if (w < 0 || h < 0) return null
  return { x: Math.min(ox, ox + w), y: Math.min(oy, oy + h), width: w, height: h }
}

/** Oriented footprint corners for an obstacle / robot chassis, in world metres. */
export function orientedCorners(centre: Point, lengthM: number, widthM: number, theta: number): Point[] {
  const hl = lengthM / 2
  const hw = widthM / 2
  const cos = Math.cos(theta)
  const sin = Math.sin(theta)
  return [
    [hl, hw],
    [hl, -hw],
    [-hl, -hw],
    [-hl, hw],
  ].map(([lx, wy]) => {
    const lxN = lx ?? 0
    const wyN = wy ?? 0
    return {
      x: centre.x + lxN * cos - wyN * sin,
      y: centre.y + lxN * sin + wyN * cos,
    }
  })
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/** Shortest signed angular difference, in (-pi, pi]. */
export function angleDelta(from: number, to: number): number {
  let d = (to - from) % (Math.PI * 2)
  if (d > Math.PI) d -= Math.PI * 2
  if (d <= -Math.PI) d += Math.PI * 2
  return d
}

/** Hit test against an oriented rectangle. Used for canvas click selection. */
export function hitOrientedRect(point: Point, centre: Point, lengthM: number, widthM: number, theta: number, slackM = 0.2): boolean {
  const cos = Math.cos(-theta)
  const sin = Math.sin(-theta)
  const dx = point.x - centre.x
  const dy = point.y - centre.y
  const localX = dx * cos - dy * sin
  const localY = dx * sin + dy * cos
  return Math.abs(localX) <= lengthM / 2 + slackM && Math.abs(localY) <= widthM / 2 + slackM
}

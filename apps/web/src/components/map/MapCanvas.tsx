/**
 * Map stage — the thin React boundary around the Pixi renderer.
 *
 * React's only jobs here are:
 *   1. mount / unmount the renderer,
 *   2. forward camera and structural payloads when they change,
 *   3. own the DOM events for pan / zoom / selection,
 *   4. own one `requestAnimationFrame` loop that pushes the *mutable* live feed
 *      into the renderer.
 *
 * Nothing per-tick passes through React. The rAF loop reads `liveFeed` (a plain
 * mutable object) and calls imperative renderer methods, so a 20 Hz telemetry
 * stream produces zero React renders. When the stream goes stale the loop keeps
 * running but the renderer holds the last pose and badges its age — motion is
 * frozen, never extrapolated.
 *
 * The canvas is `aria-hidden`: an accessible entity table and a textual
 * selection summary are rendered beside it, which is the real alternative for
 * anyone who cannot use the canvas.
 */
import { useCallback, useEffect, useRef, useState } from "react"
import type { RobotInspection, ZoneInspection } from "../../lib/api/types"
import type { MapGeometry } from "../../lib/api/types"
import { liveFeed, evaluateFreshness, getStreamStatus } from "../../lib/api/stream"
import {
  fitCamera,
  metresPerPixel,
  panCamera,
  scaleBar,
  toWorld,
  zoomCamera,
  type Camera,
  type Point,
} from "../../lib/map/geometry"
import { useViewStore, type LayerFlags } from "../../lib/view/store"
import { readPalette } from "./palette"
import { WarehouseRenderer, type SelectionRef } from "./WarehouseRenderer"

export interface MapCanvasProps {
  geometry: MapGeometry | null
  zones: ZoneInspection[]
  robots: RobotInspection[]
  freshnessHorizonS: number
  simTimeS: number
  /** False while paused/stale/replaying-from-record: robots freeze. */
  fresh: boolean
  selectedRobotId: string | null
  onSelect: (kind: "robot" | "zone" | "task", id: string) => void
  /** Read-only view (replay, scenarios) disables pointer camera control. */
  interactive?: boolean
}

export function MapCanvas(props: MapCanvasProps) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const rendererRef = useRef<WarehouseRenderer | null>(null)
  const cameraRef = useRef<Camera | null>(null)
  const propsRef = useRef(props)
  propsRef.current = props

  const camera = useViewStore((s) => s.camera)
  const setCamera = useViewStore((s) => s.setCamera)
  const layers = useViewStore((s) => s.layers)
  const theme = useViewStore((s) => s.theme)
  const selection = useViewStore((s) => s.selection)
  const markCameraClean = useViewStore((s) => s.markCameraClean)

  const [ready, setReady] = useState(false)
  const [failure, setFailure] = useState<string | null>(null)

  const interactive = props.interactive ?? true

  /* ---------------------------------------------------------------- mount */
  useEffect(() => {
    const host = hostRef.current
    if (host === null) return
    let cancelled = false
    const renderer = new WarehouseRenderer()
    rendererRef.current = renderer

    renderer
      .init(host)
      .then(() => {
        if (cancelled) {
          renderer.destroy()
          return
        }
        setReady(true)
        renderer.setViewport(host.clientWidth, host.clientHeight)
        const boundary = propsRef.current.geometry?.map.boundary
        if (boundary !== undefined) {
          const fitted = fitCamera(boundary, { width: host.clientWidth, height: host.clientHeight })
          cameraRef.current = fitted
          setCamera(fitted)
          renderer.setCamera(fitted)
        }
      })
      .catch((cause: unknown) => {
        // An unavailable renderer is stated, not hidden. The DOM alternative
        // (entity table + textual summary) still works without WebGL.
        setFailure(
          cause instanceof Error
            ? `The canvas renderer could not start: ${cause.message}. Every entity is still listed in the tables below.`
            : "The canvas renderer could not start. Every entity is still listed in the tables below.",
        )
      })

    return () => {
      cancelled = true
      renderer.destroy()
      rendererRef.current = null
      cameraRef.current = null
    }
    // Mount once. Everything else is pushed imperatively below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /* ------------------------------------------------------- structural push */
  useEffect(() => {
    const renderer = rendererRef.current
    if (renderer === null || !ready) return
    renderer.setStructure({
      geometry: props.geometry,
      zones: props.zones,
      robots: props.robots,
      layers,
      palette: readPalette(),
      theme,
    })
  }, [ready, layers, theme, props.geometry, props.zones, props.robots])

  useEffect(() => {
    const renderer = rendererRef.current
    if (renderer === null) return
    renderer.setSelection(selection as SelectionRef | null)
  }, [ready, selection])

  useEffect(() => {
    const renderer = rendererRef.current
    if (renderer === null || !ready) return
    renderer.setCamera(camera)
    cameraRef.current = camera
    markCameraClean()
  }, [ready, camera, markCameraClean])

  /* --------------------------------------------------- the single rAF loop */
  useEffect(() => {
    if (!ready) return
    let handle = 0
    let lastStatus = getStreamStatus()

    const tick = (): void => {
      const renderer = rendererRef.current
      if (renderer !== null) {
        const current = propsRef.current
        evaluateFreshness(current.freshnessHorizonS)
        renderer.setDynamic({
          feed: liveFeed,
          freshnessHorizonS: current.freshnessHorizonS,
          // Frozen whenever the stream is not demonstrably live. A paused run
          // and a stale stream both stop motion; only the label differs.
          fresh: current.fresh && getStreamStatus() === "live",
          simTimeS: current.simTimeS,
        })
      }
      const status = getStreamStatus()
      if (status !== lastStatus) {
        lastStatus = status
      }
      handle = window.requestAnimationFrame(tick)
    }
    handle = window.requestAnimationFrame(tick)
    return () => window.cancelAnimationFrame(handle)
  }, [ready])

  /* -------------------------------------------------------------- pointer */
  const pointerState = useRef<{ id: number; from: Point } | null>(null)

  const onPointerDown = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (!interactive) return
      const rect = event.currentTarget.getBoundingClientRect()
      pointerState.current = {
        id: event.pointerId,
        from: { x: event.clientX - rect.left, y: event.clientY - rect.top },
      }
      event.currentTarget.setPointerCapture(event.pointerId)
    },
    [interactive],
  )

  const onPointerMove = useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      const state = pointerState.current
      const renderer = rendererRef.current
      if (state === null || renderer === null || !interactive) return
      if (state.id !== event.pointerId) return
      const rect = event.currentTarget.getBoundingClientRect()
      const to = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      const cam = cameraRef.current
      if (cam === null) return
      cameraRef.current = panCamera(cam, { width: rect.width, height: rect.height }, state.from, to)
      state.from = to
      renderer.setCamera(cameraRef.current)
      setCamera(cameraRef.current)
    },
    [interactive, setCamera],
  )

  const endPointer = useCallback((event: React.PointerEvent<HTMLDivElement>) => {
    if (pointerState.current !== null && pointerState.current.id === event.pointerId) {
      pointerState.current = null
    }
  }, [])

  const onWheel = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      if (!interactive) return
      const renderer = rendererRef.current
      const cam = cameraRef.current
      if (renderer === null || cam === null) return
      const rect = event.currentTarget.getBoundingClientRect()
      const at = { x: event.clientX - rect.left, y: event.clientY - rect.top }
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12
      const next = zoomCamera(cam, { width: rect.width, height: rect.height }, at, factor)
      cameraRef.current = next
      renderer.setCamera(next)
      setCamera(next)
    },
    [interactive, setCamera],
  )

  const onClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      const renderer = rendererRef.current
      const cam = cameraRef.current
      if (renderer === null || cam === null) return
      const rect = event.currentTarget.getBoundingClientRect()
      const world = toWorld(
        { x: event.clientX - rect.left, y: event.clientY - rect.top },
        cam,
        { width: rect.width, height: rect.height },
      )
      const hit = renderer.pick(world.x, world.y, propsRef.current.robots)
      if (hit !== null) propsRef.current.onSelect("robot", hit)
    },
    [],
  )

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      const renderer = rendererRef.current
      const cam = cameraRef.current
      const host = hostRef.current
      if (renderer === null || cam === null || host === null) return
      const rect = host.getBoundingClientRect()
      const vp = { width: rect.width, height: rect.height }
      const centre = { x: vp.width / 2, y: vp.height / 2 }
      const step = 60 * metresPerPixel(cam)

      let next: Camera | null = null
      switch (event.key) {
        case "ArrowLeft":
          next = panCamera(cam, vp, centre, { x: centre.x + step, y: centre.y })
          break
        case "ArrowRight":
          next = panCamera(cam, vp, centre, { x: centre.x - step, y: centre.y })
          break
        case "ArrowUp":
          next = panCamera(cam, vp, centre, { x: centre.x, y: centre.y + step })
          break
        case "ArrowDown":
          next = panCamera(cam, vp, centre, { x: centre.x, y: centre.y - step })
          break
        case "+":
        case "=":
          next = zoomCamera(cam, vp, centre, 1.2)
          break
        case "-":
        case "_":
          next = zoomCamera(cam, vp, centre, 1 / 1.2)
          break
        case "f":
        case "F": {
          const boundary = propsRef.current.geometry?.map.boundary
          if (boundary !== undefined) {
            next = fitCamera(boundary, vp)
            event.preventDefault()
          }
          break
        }
        default:
          return
      }
      if (next !== null) {
        event.preventDefault()
        cameraRef.current = next
        renderer.setCamera(next)
        setCamera(next)
      }
    },
    [setCamera],
  )

  /* --------------------------------------------------------------- fit/freeze */
  const fit = useCallback(() => {
    const renderer = rendererRef.current
    const boundary = props.geometry?.map.boundary
    const host = hostRef.current
    if (renderer === null || boundary === undefined || host === null) return
    const vp = { width: host.clientWidth, height: host.clientHeight }
    const next = fitCamera(boundary, vp)
    cameraRef.current = next
    renderer.setCamera(next)
    setCamera(next)
  }, [props.geometry, setCamera])

  const bar = scaleBar(camera)
  const status = getStreamStatus()
  const frozen = !props.fresh || status === "stale" || status === "reconnecting" || status === "paused"

  return (
    <div className="relative h-full w-full overflow-hidden bg-slab">
      <div
        ref={hostRef}
        role="application"
        tabIndex={0}
        aria-label={`Warehouse map. ${props.robots.length} robots, ${props.zones.length} zones. Use arrow keys to pan, plus and minus to zoom, F to fit. A full text alternative is listed below the map.`}
        className="h-full w-full cursor-grab outline-none active:cursor-grabbing"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onWheel={onWheel}
        onClick={onClick}
        onKeyDown={onKeyDown}
      />

      {failure !== null ? (
        <div
          role="status"
          className="absolute inset-x-4 top-4 border border-amber bg-amber-wash px-3 py-2 text-[12px] text-amber"
        >
          {failure}
        </div>
      ) : null}

      {!props.fresh && failure === null ? (
        <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2">
          <div className="replay-band border border-amber bg-panel px-3 py-1.5">
            <span className="stencil text-[10px] text-amber">
              frozen · telemetry not live · last known pose shown, age in the inspector
            </span>
          </div>
        </div>
      ) : null}

      {layers.evaluatorTruth ? (
        <div className="pointer-events-none absolute bottom-16 left-3">
          <div className="hatch-steel border border-steel bg-panel px-2 py-1">
            <span className="stencil text-[10px] text-steel">evaluator truth — not agent knowledge</span>
          </div>
        </div>
      ) : null}

      {/* Scale bar: always states real metres. */}
      <div className="pointer-events-none absolute bottom-3 left-3 flex items-end gap-2">
        <div className="border border-rule-strong bg-panel px-2 py-1">
          <div
            aria-hidden="true"
            className="h-[7px] border-x border-b border-rule-strong"
            style={{ width: `${Math.max(20, Math.min(220, bar.px))}px` }}
          />
          <div className="num mt-0.5 text-[10px] text-ink-3">
            {bar.metres >= 1 ? `${bar.metres} m` : `${(bar.metres * 100).toFixed(0)} cm`}
          </div>
        </div>
        <button
          type="button"
          onClick={fit}
          className="pointer-events-auto border border-rule bg-panel px-2 py-1 text-[10px] text-ink-2 hover:border-rule-strong hover:text-ink"
        >
          Fit to view
        </button>
      </div>

      {frozen && props.fresh === false ? (
        <div className="num pointer-events-none absolute bottom-3 right-3 text-[10px] text-ink-3">
          {`${metresPerPixel(camera).toFixed(3)} m/px`}
        </div>
      ) : null}
      <span className="sr-only">{`Map scale ${bar.metres} metres across ${Math.round(bar.px)} pixels.`}</span>
      <span className="sr-only" aria-live="polite">
        {/* One summary of the selection, not a per-tick announcement. */}
        {selectedSummary(props.robots, props.selectedRobotId)}
      </span>
    </div>
  )
}

function selectedSummary(robots: RobotInspection[], selectedRobotId: string | null): string {
  if (selectedRobotId === null) return ""
  const robot = robots.find((r) => r.robot_id === selectedRobotId)
  if (robot === undefined) return ""
  const pose = robot.pose_estimate?.pose
  const poseText = pose === undefined ? "pose unavailable" : `at ${pose.x.toFixed(2)} metres east, ${pose.y.toFixed(2)} metres north`
  const stop = robot.motion?.stop_reason ?? "unknown"
  return `${robot.robot_id} ${poseText}, motion state ${stop}.`
}

export type { LayerFlags }

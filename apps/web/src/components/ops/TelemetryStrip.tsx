/**
 * Telemetry strip chart (uPlot).
 *
 * ---------------------------------------------------------------------------
 * Why uPlot and not Recharts
 * ---------------------------------------------------------------------------
 * This chart draws up to ~240 samples per robot, refreshed on the render tick,
 * and it shares the cockpit's core performance rule with the map: **high-rate
 * motion must stay out of React reconciliation.** uPlot renders to a 2D canvas
 * and exposes `setData`, so the update path is one imperative call on an existing
 * chart — no React element, no SVG diff, no per-sample reconciliation. Recharts
 * would reconcile a React tree per redraw and pull its whole dependency graph
 * (d3-scale, victory-vendor, react-redux) into the bundle for two sparkline-ish
 * series. uPlot is ~50 kB, dependency-free, and purpose-built for this.
 *
 * It is also loaded with a dynamic `import()` so the chart runtime is not in the
 * initial bundle at all: it arrives when an operator actually opens a robot
 * inspector, and if it never arrives the component degrades to a stated
 * "unavailable" note rather than a blank box.
 */
import { useEffect, useRef, useState } from "react"
import type uPlot from "uplot"
import { liveFeed } from "../../lib/api/stream"

export interface TelemetryStripProps {
  robotId: string
  heightPx?: number
  /** Samples retained per robot by `LiveFeed`. */
  sampleCap?: number
}

const SERIES_COLORS = ["var(--nm-teal)", "var(--nm-amber)"] as const

export function TelemetryStrip({ robotId, heightPx = 64 }: TelemetryStripProps) {
  const hostRef = useRef<HTMLDivElement | null>(null)
  const plotRef = useRef<uPlot | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  useEffect(() => {
    const host = hostRef.current
    if (host === null) return
    // Feature detection: a headless environment (jsdom, some CI images) has no
    // usable 2D context. State that, do not pretend.
    let contextWorks = false
    try {
      contextWorks = document.createElement("canvas").getContext("2d") !== null
    } catch {
      contextWorks = false
    }
    if (!contextWorks) {
      setFailure("This environment has no 2D canvas context, so the strip chart cannot be drawn. The numeric readouts beside it are unaffected.")
      return
    }

    let disposed = false
    let handle = 0

    void import("uplot")
      .then((module) => {
        if (disposed) return
        const UPlot = module.default
        const width = Math.max(160, host.clientWidth)
        const plot = new UPlot(
          {
            width,
            height: heightPx,
            // No animations: a chart that eases is a chart that lies about
            // when the value changed. `setData(..., false)` below is the
            // unanimated redraw path.
            cursor: { show: false },
            legend: { show: false },
            select: { show: false, left: 0, top: 0, width: 0, height: 0 },
            padding: [2, 4, 0, 4],
            scales: { x: { time: true }, y: { range: (_u, min, max) => [Math.min(0, min), Math.max(max, 0.001)] } },
            axes: [
              { show: false },
              { show: false, side: 1, values: (_u, splits) => splits.map((s) => s.toFixed(2)) },
            ],
            series: [
              { label: "t" },
              { label: "speed m/s", stroke: SERIES_COLORS[0], width: 1.5, points: { show: false } },
              { label: "battery", stroke: SERIES_COLORS[1], width: 1.5, points: { show: false } },
            ],
          },
          [[], [], []],
          host,
        )
        plotRef.current = plot

        const tick = () => {
          if (disposed) return
          const history = liveFeed.history.get(robotId)
          if (history !== undefined && history.length > 1) {
            const times = history.map((s) => s.received_at_ms / 1000)
            const speed = history.map((s) => s.linear_mps)
            const battery = history.map((s) => (s.battery_fraction === null ? Number.NaN : s.battery_fraction))
            plot.setData([times, speed, battery], false)
          }
          handle = window.requestAnimationFrame(tick)
        }
        handle = window.requestAnimationFrame(tick)
      })
      .catch((error: unknown) => {
        if (disposed) return
        setFailure(
          `The strip chart runtime could not be loaded: ${error instanceof Error ? error.message : String(error)}. Numeric readouts are unaffected.`,
        )
      })

    const onResize = () => {
      const plot = plotRef.current
      if (plot === null || host === null) return
      plot.setSize({ width: Math.max(160, host.clientWidth), height: heightPx })
    }
    window.addEventListener("resize", onResize)

    return () => {
      disposed = true
      window.cancelAnimationFrame(handle)
      window.removeEventListener("resize", onResize)
      plotRef.current?.destroy()
      plotRef.current = null
    }
  }, [robotId, heightPx])

  if (failure !== null) {
    return (
      <p className="border-t border-rule px-3 py-1 text-[10px] text-ink-3" data-testid="telemetry-strip-unavailable">
        {failure}
      </p>
    )
  }

  return (
    <div
      ref={hostRef}
      role="img"
      aria-label={`Speed and battery history for ${robotId}, most recent ${heightPx} pixels of the retained sample window. Numeric values are in the fields above.`}
      className="border-t border-rule px-1 py-1"
      data-testid="telemetry-strip"
    />
  )
}
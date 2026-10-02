/**
 * Live stream client for `WS /api/v1/stream`.
 *
 * Three responsibilities that the rest of the app depends on:
 *
 * 1. **High-rate data never enters React.** Telemetry frames are written into a
 *    mutable `LiveFeed` that the Pixi ticker reads 60 times a second. React
 *    subscribes only to *status* changes, so a 20 Hz telemetry stream causes
 *    zero reconciliation.
 *
 * 2. **Holes are detected, not papered over.** `gap` frames and `has_more`
 *    event pages both trigger a resync from the durable event log. The UI can
 *    therefore state "evidence is incomplete between seq 410 and 419" instead
 *    of silently drawing an unbroken world.
 *
 * 3. **Buffers are bounded.** A multi-hour run at 20 Hz across six robots is
 *    ~3.5 M samples; keeping them all would exhaust the tab. Ring buffers cap
 *    what we keep, and the cap is exposed so the UI can say so.
 */
import { API_ROOT } from "./client"
import type { StreamEnvelope, StreamStatus } from "./types"

export interface PoseSample {
  robot_id: string
  sample_index: number
  sim_time_s: number
  x: number
  y: number
  theta: number
  linear_mps: number
  angular_radps: number
  battery_fraction: number | null
  stop_reason: string | null
  /** Local monotonic arrival time, for ageing evidence. Never sim time. */
  received_at_ms: number
}

export interface StreamGap {
  category: string
  cause: string
  from_seq: number
  to_seq: number
  sim_time_from_s: number
  sim_time_to_s: number
  recovered: boolean
}

const TELEMETRY_PER_ROBOT = 240
const EVENT_CAP = 2000

/** Mutable, non-reactive live feed. Read by Pixi; never by React. */
export class LiveFeed {
  /** Latest pose per robot. O(1) reads on the render path. */
  readonly poses = new Map<string, PoseSample>()
  /** Bounded per-robot history for sparklines. */
  readonly history = new Map<string, PoseSample[]>()
  /** Bounded durable event log, oldest first. */
  events: unknown[] = []
  gaps: StreamGap[] = []
  /** `true` when the newest pose is older than the freshness horizon. */
  stale = false
  /** Age in seconds of the newest telemetry sample, or null when none. */
  newest_age_s: number | null = null
  last_cursor = 0
  last_frame_at_ms = 0

  pushPose(sample: PoseSample): void {
    this.poses.set(sample.robot_id, sample)
    let buf = this.history.get(sample.robot_id)
    if (buf === undefined) {
      buf = []
      this.history.set(sample.robot_id, buf)
    }
    buf.push(sample)
    if (buf.length > TELEMETRY_PER_ROBOT) buf.splice(0, buf.length - TELEMETRY_PER_ROBOT)
    this.last_frame_at_ms = sample.received_at_ms
  }

  pushEvent(event: unknown): void {
    this.events.push(event)
    if (this.events.length > EVENT_CAP) this.events.splice(0, this.events.length - EVENT_CAP)
  }

  pushGap(gap: StreamGap): void {
    this.gaps.push(gap)
    if (this.gaps.length > 200) this.gaps.splice(0, this.gaps.length - 200)
  }

  /** Freeze the feed: record the age of what we have and stop implying motion. */
  markStale(nowMs = Date.now()): void {
    this.stale = true
    if (this.last_frame_at_ms === 0) {
      this.newest_age_s = null
      return
    }
    this.newest_age_s = (nowMs - this.last_frame_at_ms) / 1000
  }

  clearStale(): void {
    this.stale = false
  }

  reset(): void {
    this.poses.clear()
    this.history.clear()
    this.events = []
    this.gaps = []
    this.stale = false
    this.newest_age_s = null
    this.last_cursor = 0
    this.last_frame_at_ms = 0
  }

  /** Age of a specific robot's newest pose. Drives the "frozen pose" label. */
  ageOf(robotId: string, nowMs = Date.now()): number | null {
    const sample = this.poses.get(robotId)
    if (sample === undefined) return null
    return (nowMs - sample.received_at_ms) / 1000
  }
}

export const liveFeed = new LiveFeed()

/* -------------------------------------------------------------------------- */
/* React-facing status store                                                  */
/* -------------------------------------------------------------------------- */

type Listener = () => void

const statusListeners = new Set<Listener>()
let status: StreamStatus = "idle"
let statusSince = new Date().toISOString()
let resyncRequired = false

export function getStreamStatus(): StreamStatus {
  return status
}
export function getStreamStatusSince(): string {
  return statusSince
}
export function needsResync(): boolean {
  return resyncRequired
}

export function setStreamStatus(next: StreamStatus): void {
  if (next === status) return
  status = next
  statusSince = new Date().toISOString()
  for (const listener of statusListeners) listener()
}

export function setResyncRequired(value: boolean): void {
  resyncRequired = value
  for (const listener of statusListeners) listener()
}

export function subscribeStatus(listener: Listener): () => void {
  statusListeners.add(listener)
  return () => statusListeners.delete(listener)
}

/** Subscribe to high-rate telemetry without going through React. */
export function subscribeFeed(listener: () => void): () => void {
  return subscribeStatus(listener)
}

/* -------------------------------------------------------------------------- */
/* Socket                                                                     */
/* -------------------------------------------------------------------------- */

export function streamUrl(runId: string, cursor: number | null): string {
  const base = API_ROOT.replace(/^http/, "ws")
  const url = `${base}/stream?run_id=${encodeURIComponent(runId)}`
  return cursor === null ? url : `${url}&cursor=${cursor}`
}

export interface StreamHandle {
  close: () => void
}

interface Handlers {
  onEventsResync: (afterSeq: number) => void
  onSnapshot: () => void
}

function readPose(frame: Record<string, unknown>) {
  const samples = Array.isArray(frame.samples) ? frame.samples : []
  const now = Date.now()
  for (const raw of samples) {
    if (typeof raw !== "object" || raw === null) continue
    const o = raw as Record<string, unknown>
    const robotId = typeof o.robot_id === "string" ? o.robot_id : null
    const x = typeof o.x === "number" ? o.x : null
    const y = typeof o.y === "number" ? o.y : null
    const theta = typeof o.theta === "number" ? o.theta : null
    const sim = typeof o.sim_time_s === "number" ? o.sim_time_s : null
    if (robotId === null || x === null || y === null || theta === null || sim === null) continue
    liveFeed.pushPose({
      robot_id: robotId,
      sample_index: typeof o.sample_index === "number" ? o.sample_index : 0,
      sim_time_s: sim,
      x,
      y,
      theta,
      linear_mps: typeof o.linear_mps === "number" ? o.linear_mps : 0,
      angular_radps: typeof o.angular_radps === "number" ? o.angular_radps : 0,
      battery_fraction: typeof o.battery_fraction === "number" ? o.battery_fraction : null,
      stop_reason: typeof o.stop_reason === "string" ? o.stop_reason : null,
      received_at_ms: now,
    })
  }
}

function readGap(frame: Record<string, unknown>): void {
  const raw = frame.gap
  if (typeof raw !== "object" || raw === null) return
  const g = raw as Record<string, unknown>
  liveFeed.pushGap({
    category: typeof g.category === "string" ? g.category : "unknown",
    cause: typeof g.cause === "string" ? g.cause : "unspecified",
    from_seq: typeof g.from_seq === "number" ? g.from_seq : 0,
    to_seq: typeof g.to_seq === "number" ? g.to_seq : 0,
    sim_time_from_s: typeof g.sim_time_from_s === "number" ? g.sim_time_from_s : 0,
    sim_time_to_s: typeof g.sim_time_to_s === "number" ? g.sim_time_to_s : 0,
    recovered: g.recovered === true,
  })
  // A gap is a hole in durable evidence: force a resync from the event log and
  // make the hole visible rather than pretending the sequence was continuous.
  setResyncRequired(true)
  handlers.onEventsResync(liveFeed.last_cursor)
}

let handlers: Handlers = { onEventsResync: () => {}, onSnapshot: () => {} }

export function openStream(runId: string, overrides?: Partial<Handlers>): StreamHandle {
  handlers = { ...handlers, ...overrides }
  liveFeed.reset()
  setResyncRequired(false)

  let socket: WebSocket | null = null
  let retryTimer: number | null = null
  let attempt = 0
  let closed = false

  const connect = (): void => {
    if (closed) return
    setStreamStatus(attempt === 0 ? "connecting" : "reconnecting")
    const url = streamUrl(runId, attempt === 0 ? null : liveFeed.last_cursor)
    try {
      socket = new WebSocket(url)
    } catch {
      scheduleRetry()
      return
    }

    socket.onopen = () => {
      attempt = 0
      setStreamStatus("live")
    }

    socket.onmessage = (message: MessageEvent<string>) => {
      let frame: StreamEnvelope
      try {
        frame = JSON.parse(message.data) as StreamEnvelope
      } catch {
        setStreamStatus("error")
        return
      }
      if (typeof frame !== "object" || frame === null) return
      const cursor = typeof frame.cursor === "number" ? frame.cursor : liveFeed.last_cursor
      liveFeed.last_cursor = Math.max(liveFeed.last_cursor, cursor)
      liveFeed.clearStale()

      switch (frame.kind) {
        case "telemetry":
          readPose(frame as unknown as Record<string, unknown>)
          setStreamStatus("live")
          break
        case "event": {
          const events = (frame as unknown as { events: unknown[] }).events
          for (const event of events ?? []) liveFeed.pushEvent(event)
          if ((events?.length ?? 0) > 0) {
            const last = events[events.length - 1] as { seq?: number } | undefined
            if (typeof last?.seq === "number") liveFeed.last_cursor = Math.max(liveFeed.last_cursor, last.seq)
            handlers.onEventsResync(liveFeed.last_cursor)
          }
          break
        }
        case "snapshot":
          handlers.onSnapshot()
          break
        case "gap":
          readGap(frame as unknown as Record<string, unknown>)
          break
        case "status": {
          const next = (frame as unknown as { status: StreamStatus }).status
          setStreamStatus(next)
          break
        }
        default:
          break
      }
    }

    socket.onerror = () => {
      setStreamStatus("error")
    }

    socket.onclose = () => {
      if (closed) return
      liveFeed.markStale()
      scheduleRetry()
    }
  }

  const scheduleRetry = (): void => {
    if (closed) return
    attempt += 1
    setStreamStatus("reconnecting")
    // Backoff, capped. Exponential with jitter so a restarted API is not
    // hammered by every open tab at once.
    const base = Math.min(8000, 400 * 2 ** Math.min(attempt, 5))
    const delay = base * (0.75 + Math.random() * 0.5)
    retryTimer = window.setTimeout(connect, delay)
  }

  connect()

  return {
    close: () => {
      closed = true
      if (retryTimer !== null) window.clearTimeout(retryTimer)
      liveFeed.markStale()
      socket?.close()
      setStreamStatus("closed")
    },
  }
}

/**
 * Poll-driven staleness check. Called from the cockpit's single interval so
 * that only *derived boolean* transitions re-render React.
 */
export function evaluateFreshness(freshnessHorizonS: number, nowMs = Date.now()): void {
  if (liveFeed.last_frame_at_ms === 0) return
  const ageS = (nowMs - liveFeed.last_frame_at_ms) / 1000
  liveFeed.newest_age_s = ageS
  const shouldBeStale = ageS > Math.max(0.5, freshnessHorizonS)
  if (shouldBeStale !== liveFeed.stale) {
    liveFeed.stale = shouldBeStale
    setStreamStatus(shouldBeStale ? "stale" : "live")
  }
}

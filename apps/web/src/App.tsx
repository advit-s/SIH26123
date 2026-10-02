/**
 * Application root.
 *
 * Responsibilities:
 *   - own the WebSocket lifecycle for the attached run (one socket, one owner),
 *   - resolve the hash route and the attached run id,
 *   - keep the persistent context bar mounted above every destination,
 *   - state an unreachable API once, at the top, instead of letting every panel
 *     rediscover it.
 *
 * It deliberately does not fetch run state separately from the pages: the bar and
 * the operations page read the same cached query, so there is exactly one
 * request per resource.
 */
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react"
import { useQueryClient } from "@tanstack/react-query"
import {
  queryKeys,
  useHealth,
  useRunDetail,
  useRunState,
  useRuns,
} from "./lib/api/queries"
import { getStreamStatus, getStreamStatusSince, liveFeed, openStream, subscribeStatus } from "./lib/api/stream"
import { ApiError } from "./lib/api/types"
import { DEFAULT_FRESHNESS_HORIZON_S } from "./lib/map/freshness"
import { parseHash, useViewStore } from "./lib/view/store"
import { ContextBar } from "./components/shell/ContextBar"
import { NavRail } from "./components/shell/NavRail"
import { StatusStrip } from "./components/shell/StatusStrip"
import { OperationsPage } from "./routes/OperationsPage"
import { ScenariosPage } from "./routes/ScenariosPage"
import { ExperimentsPage } from "./routes/ExperimentsPage"
import { ReplaysPage } from "./routes/ReplaysPage"
import { SystemPage } from "./routes/SystemPage"
import { WelcomePage } from "./routes/WelcomePage"

export function App() {
  const qc = useQueryClient()
  const destination = useViewStore((s) => s.destination)
  const routeParam = useViewStore((s) => s.routeParam)
  const navigate = useViewStore((s) => s.navigate)
  const theme = useViewStore((s) => s.theme)
  const reduceMotion = useViewStore((s) => s.reduceMotion)
  const setReduceMotion = useViewStore((s) => s.setReduceMotion)

  const health = useHealth()
  const runs = useRuns()

  /* ------------------------------------------------------- hash routing */
  useEffect(() => {
    const apply = () => {
      const parsed = parseHash(window.location.hash)
      useViewStore.setState({ destination: parsed.destination, routeParam: parsed.param })
    }
    apply()
    window.addEventListener("hashchange", apply)
    window.addEventListener("popstate", apply)
    return () => {
      window.removeEventListener("hashchange", apply)
      window.removeEventListener("popstate", apply)
    }
  }, [])

  /* --------------------------------------------------------- theme sync */
  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  /* ------------------------------------------------- reduced motion sync */
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return
    const query = window.matchMedia("(prefers-reduced-motion: reduce)")
    setReduceMotion(query.matches)
    const onChange = (event: MediaQueryListEvent) => setReduceMotion(event.matches)
    query.addEventListener("change", onChange)
    return () => query.removeEventListener("change", onChange)
  }, [setReduceMotion])

  /* ------------------------------------------------------ attached run */
  const runId = useMemo(() => {
    if (routeParam !== null && routeParam.length > 0) return routeParam
    if (health.data?.run_id != null && health.data.run_id.length > 0) return health.data.run_id
    const inFlight = (runs.data ?? []).find((r) => r.state === "running" || r.state === "paused")
    return inFlight?.run_id ?? null
  }, [routeParam, health.data?.run_id, runs.data])

  const runState = useRunState(runId, true)
  const runDetail = useRunDetail(runId)

  /* ---------------------------------------------------- stream lifecycle */
  useEffect(() => {
    if (runId === null || destination === "replays") return
    const handle = openStream(runId, {
      onEventsResync: () => {
        void qc.invalidateQueries({ queryKey: queryKeys.events(runId, "") })
      },
      onSnapshot: () => {
        void qc.invalidateQueries({ queryKey: queryKeys.runState(runId) })
        void qc.invalidateQueries({ queryKey: queryKeys.robots(runId) })
        void qc.invalidateQueries({ queryKey: queryKeys.zones(runId) })
      },
    })
    return () => handle.close()
  }, [runId, destination, qc])

  /* ------------------------------- stream status, subscribed *sparingly* --- */
  const streamStatus = useSyncExternalStore(subscribeStatus, getStreamStatus, () => "closed" as const)
  const streamSince = useSyncExternalStore(subscribeStatus, getStreamStatusSince, () => "")
  const streamAgeS = liveFeed.newest_age_s
  const [barTick, setBarTick] = useState(0)
  const refreshBar = useCallback(() => setBarTick((n) => n + 1), [])
  void barTick

  const unreachable = health.error instanceof ApiError && health.error.unreachable
  const apiReachable = !unreachable

  const physicalActuation =
    runDetail.data === undefined || runDetail.data.manifest === undefined
      ? false
      : ((runDetail.data.manifest as unknown as { physical_actuation_enabled?: boolean })
          .physical_actuation_enabled ?? false)

  return (
    <div className="flex h-full flex-col bg-slab text-ink">
      <ContextBar
        state={runState.data ?? null}
        health={health.data ?? null}
        streamStatus={streamStatus}
        streamAgeS={streamAgeS}
        replaying={destination === "replays"}
        physicalActuation={physicalActuation}
        onOpenSystem={() => navigate("system")}
      />

      {physicalActuation ? (
        <div className="hatch-red flex shrink-0 items-center gap-2 border-b border-red bg-red-wash px-3 py-1">
          <span className="stencil text-[10px] text-red">physical actuation enabled</span>
          <span className="text-[11px] text-ink-2">
            Commands may reach configured hardware. Stopping this browser will not stop the fleet.
          </span>
        </div>
      ) : null}

      {unreachable ? (
        <div className="flex shrink-0 items-center gap-2 border-b border-red bg-red-wash px-3 py-1" role="status">
          <span className="stencil text-[10px] text-red">api unreachable</span>
          <span className="text-[11px] text-ink-2">
            {health.error instanceof ApiError ? health.error.message : "The API is not answering."}
          </span>
          <button
            type="button"
            onClick={() => {
              void qc.invalidateQueries()
              refreshBar()
            }}
            className="ml-auto border border-red px-2 py-0.5 text-[10px] text-red hover:bg-red-wash"
          >
            retry
          </button>
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <NavRail runId={runId} runCount={runs.data?.length ?? 0} />
        <main className="min-h-0 min-w-0 flex-1" data-testid="route" data-route={destination}>
          {destination === "welcome" ? <WelcomePage apiReachable={apiReachable} /> : null}
          {destination === "operations" ? (
            <OperationsPage
              runId={runId}
              freshnessHorizonS={DEFAULT_FRESHNESS_HORIZON_S}
              physicalActuation={physicalActuation}
              onGoToScenarios={() => navigate("scenarios")}
            />
          ) : null}
          {destination === "scenarios" ? <ScenariosPage initialScenarioId={routeParam} /> : null}
          {destination === "experiments" ? <ExperimentsPage /> : null}
          {destination === "replays" ? <ReplaysPage initialRunId={routeParam} /> : null}
          {destination === "system" ? <SystemPage /> : null}
        </main>
      </div>

      <StatusStrip
        artifactPath={runDetail.data?.result?.events_path ?? null}
        manifestDigest={runDetail.data?.result?.manifest_digest ?? null}
        reduceMotion={reduceMotion}
      />
      <span className="sr-only" data-testid="stream-since">
        {streamSince}
      </span>
    </div>
  )
}
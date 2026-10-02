/**
 * Operations cockpit.
 *
 * Layout intent: **the warehouse dominates.** The map takes the whole centre and
 * the full height of the working area; layers and the legend are a narrow rail
 * on the left; the inspector column on the right is the evidence column, not a
 * set of cards competing with the map.
 *
 * Data flow: TanStack Query polls the low-frequency read models at 1–2 s; the
 * WebSocket pushes telemetry into the mutable `LiveFeed` which the Pixi ticker
 * reads directly. React renders no per-tick markup.
 */
import { useMemo, useState, useSyncExternalStore } from "react"
import {
  useCommands,
  useCommunication,
  useEvents,
  useFaults,
  useMapGeometry,
  useRobots,
  useRunState,
  useTasks,
  useZones,
  type EventFilters,
} from "../lib/api/queries"
import { getStreamStatus, getStreamStatusSince, liveFeed, subscribeStatus } from "../lib/api/stream"
import type {
  CommunicationCell,
  RobotInspection,
  TaskInspection,
  ZoneInspection,
} from "../lib/api/types"
import { age } from "../lib/format"
import { useViewStore } from "../lib/view/store"
import { MapCanvas } from "../components/map/MapCanvas"
import { Panel, PanelBody } from "../components/primitives/Panel"
import { ErrorState, LoadingState } from "../components/primitives/States"
import { CommandPanel } from "../components/ops/CommandPanel"
import { CommunicationMatrix } from "../components/ops/CommunicationMatrix"
import { RobotTable, SelectionSummary, TaskTable, ZoneTable } from "../components/ops/EntityTables"
import { EventLog } from "../components/ops/EventLog"
import { FaultLab } from "../components/ops/FaultLab"
import { LayerPanel, MapLegend } from "../components/ops/LayerPanel"
import { RobotInspector } from "../components/ops/RobotInspector"
import { TaskInspector } from "../components/ops/TaskInspector"
import { ZoneInspector } from "../components/ops/ZoneInspector"

type BottomTab = "robots" | "zones" | "tasks" | "events"

export function OperationsPage({
  runId,
  freshnessHorizonS,
  physicalActuation,
  onGoToScenarios,
}: {
  runId: string | null
  freshnessHorizonS: number
  physicalActuation: boolean
  onGoToScenarios: () => void
}) {
  const runState = useRunState(runId, true)
  const robots = useRobots(runId, true)
  const zones = useZones(runId, true)
  const tasks = useTasks(runId, true)
  const communication = useCommunication(runId, true)
  const commands = useCommands(runId, true)
  const faults = useFaults(runId, true)
  const geometry = useMapGeometry(runId, runState.data?.map_id ?? null)

  const [eventFilters, setEventFilters] = useState<EventFilters>({ limit: 200 })
  const [bottomTab, setBottomTab] = useState<BottomTab>("robots")
  const [showTable, setShowTable] = useState(true)

  const streamStatus = useSyncExternalStore(subscribeStatus, getStreamStatus, () => "idle" as const)
  const streamSince = useSyncExternalStore(subscribeStatus, getStreamStatusSince, () => "")

  const events = useEvents(runId, eventFilters, runId !== null)

  const robotList = robots.data ?? []
  const zoneList = zones.data ?? []
  const taskList = tasks.data ?? []
  const robotIds = useMemo(() => robotList.map((r) => r.robot_id).toSorted(), [robotList])

  // Per-robot evidence age, read from the mutable feed. Recomputed only when
  // the *status* transitions, so this is not a per-tick React render.
  const poseAges = useMemo(() => {
    const map = new Map<string, number | null>()
    for (const robot of robotList) map.set(robot.robot_id, liveFeed.ageOf(robot.robot_id))
    return map
  }, [robotList, streamStatus])

  const streamAgeS = liveFeed.newest_age_s
  const live = streamStatus === "live"
  const selection = useViewStore((s) => s.selection)
  const selectedRobotId = selection?.kind === "robot" ? selection.id : null

  return (
    <div className="grid h-full min-h-0 grid-cols-[186px_minmax(0,1fr)_392px]">
      {/* ---------------- left rail: layers + legend ---------------- */}
      <aside className="flex min-h-0 flex-col gap-2 overflow-hidden border-r border-rule bg-panel p-2">
        <LayerPanel />
        <div className="min-h-0 flex-1 scroll-y">
          <MapLegend robotIds={robotIds} />
        </div>
      </aside>

      {/* ---------------- centre: the warehouse ---------------- */}
      <main className="flex min-h-0 min-w-0 flex-col">
        <div className="relative min-h-0 flex-1 border-b border-rule">
          {runId === null ? (
            <NoRunPrompt onGoToScenarios={onGoToScenarios} />
          ) : robots.isError || zones.isError ? (
            <ErrorState
              error={robots.error ?? zones.error}
              what="The run's robots and zones"
              onRetry={() => {
                void robots.refetch()
                void zones.refetch()
              }}
            />
          ) : robots.isPending || zones.isPending ? (
            <LoadingState what="run state" rows={6} />
          ) : (
            <MapCanvas
              geometry={geometry.data ?? null}
              zones={zoneList}
              robots={robotList}
              freshnessHorizonS={freshnessHorizonS}
              simTimeS={runState.data?.sim_time_s ?? 0}
              fresh={live}
              selectedRobotId={selectedRobotId}
              onSelect={(kind, id) => useViewStore.getState().select(kind, id)}
            />
          )}

          {/* Staleness is stated on the map itself, not only in the context bar,
              because the map is what people actually look at. */}
          {!live && runId !== null && !robots.isError && robots.isSuccess ? (
            <div className="pointer-events-none absolute left-1/2 top-3 -translate-x-1/2" data-testid="map-frozen-banner">
              <div className="hatch-amber border border-amber bg-panel px-3 py-1.5">
                <span className="stencil text-[10px] text-amber">
                  {streamStatus === "reconnecting"
                    ? "stream reconnecting — poses frozen, age in the inspector"
                    : streamStatus === "paused"
                      ? "harness paused — poses frozen at the last known value"
                      : `stream ${streamStatus} — poses frozen, last frame ${
                          streamAgeS === null ? "never" : age(streamAgeS)
                        } old`}
                </span>
              </div>
            </div>
          ) : null}
        </div>

        {/* ------------- accessible alternative + timeline ------------- */}
        <section className="flex min-h-0 flex-col" style={{ height: showTable ? "40%" : "auto" }}>
          <div className="flex shrink-0 items-center gap-1 border-b border-rule bg-panel px-2 py-1">
            <button
              type="button"
              onClick={() => setShowTable((v) => !v)}
              aria-expanded={showTable}
              className="stencil border border-rule px-1.5 py-[3px] text-[9px] text-ink-2 hover:border-rule-strong hover:text-ink"
            >
              {showTable ? "hide tables" : "show tables"}
            </button>
            <span className="stencil text-[9px] text-ink-4">text alternative to the canvas</span>
            <div className="ml-auto flex items-center gap-1" role="tablist" aria-label="Entity tables">
              {(
                [
                  ["robots", robotList.length],
                  ["zones", zoneList.length],
                  ["tasks", taskList.length],
                  ["events", events.data?.events.length ?? 0],
                ] as [BottomTab, number][]
              ).map(([tab, count]) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={bottomTab === tab}
                  onClick={() => setBottomTab(tab)}
                  data-testid={`tab-${tab}`}
                  className={`border px-2 py-[3px] text-[10px] ${
                    bottomTab === tab
                      ? "border-rule-strong bg-raised text-ink"
                      : "border-transparent text-ink-3 hover:text-ink"
                  }`}
                >
                  {tab}
                  <span className="num ml-1 text-ink-4">{count}</span>
                </button>
              ))}
            </div>
          </div>

          {showTable ? (
            <div className="min-h-0 flex-1 scroll-y bg-panel" role="tabpanel" aria-label={`${bottomTab} table`}>
              {runId === null ? (
                <p className="p-3 text-[12px] text-ink-3">Attach a run to see its entities.</p>
              ) : bottomTab === "robots" ? (
                robots.isError ? (
                  <ErrorState error={robots.error} what="The robot list" onRetry={() => void robots.refetch()} />
                ) : robots.isPending ? (
                  <LoadingState what="robots" />
                ) : (
                  <RobotTable robots={robotList} poseAges={poseAges} />
                )
              ) : bottomTab === "zones" ? (
                zones.isError ? (
                  <ErrorState error={zones.error} what="The zone list" onRetry={() => void zones.refetch()} />
                ) : zones.isPending ? (
                  <LoadingState what="zones" />
                ) : (
                  <ZoneTable zones={zoneList} />
                )
              ) : bottomTab === "tasks" ? (
                tasks.isError ? (
                  <ErrorState error={tasks.error} what="The task queue" onRetry={() => void tasks.refetch()} />
                ) : tasks.isPending ? (
                  <LoadingState what="tasks" />
                ) : (
                  <TaskTable tasks={taskList} />
                )
              ) : events.isError ? (
                <ErrorState error={events.error} what="The event log" onRetry={() => void events.refetch()} />
              ) : events.isPending ? (
                <LoadingState what="events" />
              ) : (
                <EventLog
                  events={events.data?.events ?? []}
                  gaps={runState.data?.recording_gaps ?? []}
                  filters={eventFilters}
                  onFiltersChange={setEventFilters}
                  hasMore={events.data?.has_more ?? false}
                  nextSeq={events.data?.next_seq ?? 0}
                  isFetching={events.isFetching}
                  onLoadMore={() => setEventFilters((prev) => ({ ...prev, afterSeq: events.data?.next_seq }))}
                  mode="live"
                />
              )}
            </div>
          ) : null}
        </section>
      </main>

      {/* ---------------- right: the evidence column ---------------- */}
      <aside className="flex min-h-0 flex-col overflow-hidden border-l border-rule bg-panel">
        <div className="shrink-0 border-b border-rule">
          <SelectionSummary robots={robotList} zones={zoneList} tasks={taskList} />
        </div>
        <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-hidden p-2">
          <InspectorColumn
            robots={robotList}
            zones={zoneList}
            tasks={taskList}
            communication={communication.data ?? []}
            robotIds={robotIds}
            poseAges={poseAges}
            freshnessHorizonS={freshnessHorizonS}
            live={live}
          />
        </div>
        <div className="scroll-y max-h-[46%] shrink-0 space-y-2 border-t border-rule p-2" data-testid="operator-panels">
          <CommandPanel
            runId={runId}
            state={runState.data ?? null}
            records={commands.data ?? []}
            physicalActuation={physicalActuation}
          />
          <FaultLab runId={runId} robotIds={robotIds} records={faults.data ?? []} />
        </div>
        <p className="num shrink-0 border-t border-rule px-3 py-1 text-[9px] text-ink-4">
          stream {streamStatus} since {streamSince === "" ? "—" : streamSince}
        </p>
      </aside>
    </div>
  )
}

function NoRunPrompt({ onGoToScenarios }: { onGoToScenarios: () => void }) {
  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="max-w-[46ch] text-center">
        <h2 className="text-[14px] font-semibold text-ink">No run attached</h2>
        <p className="mt-1.5 text-[12px] leading-relaxed text-ink-2">
          The cockpit shows a run, not a mock-up. Open <strong className="font-semibold">Scenarios</strong> to launch a
          saved revision, or <strong className="font-semibold">Experiments</strong> to run a paired matrix and then
          open one of its cells here.
        </p>
        <div className="mt-3 flex justify-center">
          <button type="button" onClick={onGoToScenarios} className="border border-teal bg-teal-wash px-3 py-1.5 text-[12px] text-teal">
            Go to Scenarios
          </button>
        </div>
      </div>
    </div>
  )
}

function InspectorColumn({
  robots,
  zones,
  tasks,
  communication,
  robotIds,
  poseAges,
  freshnessHorizonS,
  live,
}: {
  robots: RobotInspection[]
  zones: ZoneInspection[]
  tasks: TaskInspection[]
  communication: CommunicationCell[]
  robotIds: string[]
  poseAges: Map<string, number | null>
  freshnessHorizonS: number
  live: boolean
}) {
  const selection = useViewStore((s) => s.selection)
  const inspectorTab = useViewStore((s) => s.inspectorTab)
  const setInspectorTab = useViewStore((s) => s.setInspectorTab)

  const selectedRobot = selection?.kind === "robot" ? (robots.find((r) => r.robot_id === selection.id) ?? null) : null
  const selectedZone = selection?.kind === "zone" ? (zones.find((z) => z.zone_id === selection.id) ?? null) : null
  const selectedTask = selection?.kind === "task" ? (tasks.find((t) => t.task_id === selection.id) ?? null) : null

  const tabs: { id: typeof inspectorTab; label: string; count: number | null }[] = [
    { id: "robot", label: "robot", count: selectedRobot !== null ? 1 : null },
    { id: "zone", label: "zone", count: selectedZone !== null ? 1 : null },
    { id: "task", label: "task", count: selectedTask !== null ? 1 : null },
    { id: "comms", label: "peers", count: null },
  ]

  if (inspectorTab === "comms") {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <InspectorTabs
          tabs={tabs}
          active={inspectorTab}
          onSelect={setInspectorTab}
        />
        <div className="min-h-0 flex-1">
          <CommunicationMatrix cells={communication} robotIds={robotIds} />
        </div>
      </div>
    )
  }

  return (
    <Panel className="min-h-0 flex-1" ticks>
      <InspectorTabs tabs={tabs} active={inspectorTab} onSelect={setInspectorTab} />
      <PanelBody scroll={false} className="min-h-0">
        {inspectorTab === "robot" ? (
          selectedRobot === null ? (
            <p className="p-3 text-[12px] text-ink-3" data-testid="inspector-empty">
              No robot selected. Choose one from the map or the robots table.
            </p>
          ) : (
            <RobotInspector
              robot={selectedRobot}
              freshnessHorizonS={freshnessHorizonS}
              liveAgeS={poseAges.get(selectedRobot.robot_id) ?? null}
              streamLive={live}
            />
          )
        ) : inspectorTab === "zone" ? (
          selectedZone === null ? (
            <p className="p-3 text-[12px] text-ink-3" data-testid="inspector-empty">
              No zone selected. Choose one from the map or the zones table.
            </p>
          ) : (
            <ZoneInspector zone={selectedZone} />
          )
        ) : selectedTask === null ? (
          <p className="p-3 text-[12px] text-ink-3" data-testid="inspector-empty">
            No task selected. Choose one from the tasks table to read its bids and completion evidence.
          </p>
        ) : (
          <TaskInspector task={selectedTask} />
        )}
      </PanelBody>
    </Panel>
  )
}

function InspectorTabs({
  tabs,
  active,
  onSelect,
}: {
  tabs: { id: string; label: string; count: number | null }[]
  active: string
  onSelect: (id: never) => void
}) {
  return (
    <div className="flex shrink-0 border-b border-rule" role="tablist" aria-label="Inspector">
      {tabs.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={active === tab.id}
          data-testid={`inspector-tab-${tab.id}`}
          onClick={() => onSelect(tab.id as never)}
          className={`flex-1 border-b-2 px-2 py-1.5 text-[10px] ${
            active === tab.id ? "border-teal text-ink" : "border-transparent text-ink-3 hover:text-ink"
          }`}
        >
          {tab.label}
          {tab.count !== null ? <span className="num ml-1 text-teal">{tab.count}</span> : null}
        </button>
      ))}
    </div>
  )
}
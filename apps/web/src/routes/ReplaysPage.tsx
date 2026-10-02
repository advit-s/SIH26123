/**
 * Replays.
 *
 * Recorded playback is *visibly* a different activity from watching a run:
 * the whole page carries a hatch band and a "recorded playback" stencil, the
 * timeline is ruled, and no live control is offered — because nothing here is
 * being simulated.
 *
 * The seek implementation is the important part. Seeking backwards does **not**
 * rewind a forward-built object. `world` is recomputed by folding only
 * `events[0..cursor]`, so a completion, grant, obstacle insertion or alert that
 * happened after the cursor simply does not exist in the new state. See
 * `../lib/replay/reducer.ts`.
 */
import { useEffect, useMemo, useRef, useState } from "react"
import type { DomainEvent } from "@niharamesh/contracts/generated"
import { SCHEMA_VERSION } from "@niharamesh/contracts/generated"
import { useEvents, useReplayDetail, useReplayIndex } from "../lib/api/queries"
import { simClock } from "../lib/format"
import {
  buildReplayState,
  cursorBounds,
  eventsUpTo,
  firstFaultSeq,
  firstViolationSeq,
} from "../lib/replay/reducer"
import { useViewStore } from "../lib/view/store"
import { Panel, PanelBody, PanelHeader, Strip } from "../components/primitives/Panel"
import { HatchStrip } from "../components/primitives/Panel"
import { Button } from "../components/primitives/Button"
import { Chip } from "../components/primitives/Chip"
import { DataTable, type Column } from "../components/primitives/DataTable"
import { EmptyState, ErrorState, LoadingState } from "../components/primitives/States"

const SPEEDS = [0.25, 0.5, 1, 2, 4, 8]

export function ReplaysPage({ initialRunId }: { initialRunId: string | null }) {
  const index = useReplayIndex()
  const [runId, setRunId] = useState<string | null>(initialRunId)
  const detail = useReplayDetail(runId)
  const navigate = useViewStore((s) => s.navigate)

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_420px]">
      <div className="replay-band flex min-h-0 flex-col border-r border-rule">
        <div className="flex shrink-0 items-center gap-2 border-b border-rule bg-panel px-3 py-1.5">
          <span className="stencil text-[11px] text-steel">recorded playback</span>
          <span className="text-[11px] text-ink-3">
            Rebuilding the world from the durable event log. Nothing is being simulated and no robot is commanded.
          </span>
        </div>
        <Panel ticks className="min-h-0 flex-1">
          <PanelHeader
            title="replay index"
            subtitle="every run with a durable recording"
            tone="steel"
            right={<Chip tone="muted">{`${index.data?.length ?? 0} recordings`}</Chip>}
          />
          <PanelBody>
            {index.isError ? (
              <ErrorState error={index.error} what="The replay index" onRetry={() => void index.refetch()} />
            ) : index.isPending ? (
              <LoadingState what="recordings" />
            ) : (index.data?.length ?? 0) === 0 ? (
              <EmptyState
                title="No recordings yet"
                body="A recording becomes available once a run writes its durable event log. Launch a run, or run the demo, then come back."
              />
            ) : (
              <ul className="divide-y divide-rule">
                {index.data?.map((entry) => (
                  <li key={entry.run_id} className="flex flex-wrap items-center gap-2 px-3 py-2" data-testid="replay-index-row">
                    <span className="num min-w-0 flex-1 break-all text-[12px] text-ink">{entry.run_id}</span>
                    <span className="num text-[10px] text-ink-3">{entry.event_count} events</span>
                    <span className="num text-[10px] text-ink-3">
                      {simClock(entry.first_sim_time_s)} → {simClock(entry.last_sim_time_s)}
                    </span>
                    <Chip tone={entry.complete ? "teal" : "amber"}>{entry.complete ? "complete" : "gaps"}</Chip>
                    {(entry.gaps ?? []).length > 0 ? (
                      <Chip tone="red">{`${(entry.gaps ?? []).length} gaps`}</Chip>
                    ) : null}
                    <Button onClick={() => setRunId(entry.run_id)} variant={runId === entry.run_id ? "primary" : "default"}>
                      {runId === entry.run_id ? "playing" : "open"}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </PanelBody>
        </Panel>
      </div>

      <aside className="flex min-h-0 flex-col overflow-hidden">
        {runId === null ? (
          <div className="flex h-full items-center justify-center p-4">
            <EmptyState title="Nothing loaded" body="Choose a recording on the left to open its timeline and rebuilt state." />
          </div>
        ) : detail.isError ? (
          <ErrorState error={detail.error} what="This recording" onRetry={() => void detail.refetch()} />
        ) : detail.isPending ? (
          <LoadingState what="the recording" rows={6} />
        ) : (
          <ReplayPlayer
            runId={runId}
            eventCount={detail.data?.index.event_count ?? 0}
            firstSimTimeS={detail.data?.index.first_sim_time_s ?? 0}
            lastSimTimeS={detail.data?.index.last_sim_time_s ?? 0}
            gaps={detail.data?.index.gaps ?? []}
            notes={detail.data?.index.notes ?? null}
            onOpenLive={() => navigate("operations", runId)}
          />
        )}
      </aside>
    </div>
  )
}

function ReplayPlayer({
  runId,
  eventCount,
  firstSimTimeS,
  lastSimTimeS,
  gaps,
  notes,
  onOpenLive,
}: {
  runId: string
  eventCount: number
  firstSimTimeS: number
  lastSimTimeS: number
  gaps: { from_seq: number; to_seq: number; category: string; cause: string }[]
  notes: string | null
  onOpenLive: () => void
}) {
  const reduceMotion = useViewStore((s) => s.reduceMotion)
  const events = useEvents(runId, { limit: 5000 }, true)

  const all: DomainEvent[] = useMemo(() => events.data?.events.toSorted((a, b) => a.seq - b.seq) ?? [], [events.data])
  const bounds = useMemo(() => cursorBounds(all), [all])

  const [cursorSeq, setCursorSeq] = useState<number>(bounds.last ?? 0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)

  // Keep the cursor inside the loaded window. On the *first* load the cursor is
  // a placeholder, so it moves to the end of the log: opening a replay should
  // show the completed world, not an empty one at seq 0. After that it only ever
  // clamps down, so loading more events never yanks the operator's position.
  const cursorInitialised = useRef(false)
  useEffect(() => {
    if (bounds.last === null) return
    if (!cursorInitialised.current) {
      cursorInitialised.current = true
      setCursorSeq(bounds.last)
      return
    }
    if (cursorSeq > bounds.last) setCursorSeq(bounds.last)
  }, [bounds.last, cursorSeq])

  /** THE seek implementation: rebuild from the prefix, never un-apply. */
  const sliced = useMemo(() => eventsUpTo(all, cursorSeq), [all, cursorSeq])
  const world = useMemo(() => buildReplayState(sliced, SCHEMA_VERSION), [sliced])

  useEffect(() => {
    if (!playing || reduceMotion) return
    const step = setInterval(() => {
      setCursorSeq((current) => {
        if (bounds.last === null) return current
        if (current >= bounds.last) {
          setPlaying(false)
          return current
        }
        return current + 1
      })
    }, Math.max(40, 250 / speed))
    return () => clearInterval(step)
  }, [playing, speed, bounds.last, reduceMotion])

  const stepTo = (target: number | null) => {
    if (target === null) return
    setCursorSeq(target)
  }

  const nextSeq = useMemo(() => all.find((e) => e.seq > cursorSeq)?.seq ?? null, [all, cursorSeq])
  const prevSeq = useMemo(() => {
    let found: number | null = null
    for (const event of all) {
      if (event.seq >= cursorSeq) break
      found = event.seq
    }
    return found
  }, [all, cursorSeq])

  const faultSeq = useMemo(() => firstFaultSeq(all), [all])
  const violationSeq = useMemo(() => firstViolationSeq(all), [all])
  const total = Math.max(1, (bounds.last ?? 1) - (bounds.first ?? 0) + 1)
  const progress = bounds.first === null ? 0 : (cursorSeq - bounds.first) / total

  const unsupported = world.problems.find((p) => p.kind === "unsupported_version")

  const columns: Column<DomainEvent>[] = [
    { key: "seq", header: "seq", mono: true, width: "62px", render: (e) => e.seq },
    { key: "sim", header: "sim", mono: true, width: "66px", render: (e) => simClock(e.sim_time_s ?? null) },
    { key: "sev", header: "sev", width: "54px", render: (e) => <Chip tone={e.severity === "violation" || e.severity === "fault" ? "red" : e.severity === "attention" ? "amber" : "muted"}>{e.severity}</Chip> },
    { key: "type", header: "type", width: "160px", render: (e) => <span className="num text-[10px]">{e.type}</span> },
    { key: "reason", header: "reason", render: (e) => <span className="text-[11px] text-ink-2">{e.reason || "—"}</span> },
  ]

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ---------------- transport ---------------- */}
      <div className="shrink-0 border-b border-rule bg-panel px-3 py-2">
        <div className="flex flex-wrap items-center gap-1.5">
          <Button onClick={() => setPlaying((p) => !p)} variant={playing ? "harness" : "default"} data-testid="replay-play">
            {playing ? "Pause" : "Play"}
          </Button>
          <Button onClick={() => stepTo(prevSeq)} data-testid="replay-prev">
            Previous event
          </Button>
          <Button onClick={() => stepTo(nextSeq)} data-testid="replay-next">
            Next event
          </Button>
          <label className="sr-only" htmlFor="replay-speed">
            Playback speed
          </label>
          <select
            id="replay-speed"
            value={speed}
            onChange={(e) => setSpeed(Number(e.target.value))}
            className="border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
          >
            {SPEEDS.map((s) => (
              <option key={s} value={s}>
                {s.toFixed(2)}×
              </option>
            ))}
          </select>
          <Button onClick={() => faultSeq !== null && stepTo(faultSeq)} disabled={faultSeq === null}>
            first fault
          </Button>
          <Button onClick={() => violationSeq !== null && stepTo(violationSeq)} disabled={violationSeq === null}>
            first violation
          </Button>
          <Button onClick={onOpenLive}>open as a run</Button>
        </div>

        {/* Timeline: ruled, with explicit markers for the fault and violation. */}
        <div className="mt-2">
          <label className="sr-only" htmlFor="replay-cursor">
            Replay position
          </label>
          <input
            id="replay-cursor"
            type="range"
            min={bounds.first ?? 0}
            max={bounds.last ?? 0}
            value={cursorSeq}
            onChange={(e) => setCursorSeq(Number(e.target.value))}
            data-testid="replay-cursor"
            className="w-full accent-[var(--nm-steel)]"
          />
          <div className="relative h-[14px]">
            <div aria-hidden="true" className="absolute inset-x-0 top-[5px] h-[4px] border border-rule bg-raised" />
            <div
              aria-hidden="true"
              className="absolute top-[5px] h-[4px] bg-steel"
              style={{ left: 0, width: `${progress * 100}%` }}
            />
            {faultSeq !== null && bounds.first !== null && bounds.last !== null ? (
              <Marker at={faultSeq} first={bounds.first} last={bounds.last} label="fault" tone="amber" />
            ) : null}
            {violationSeq !== null && bounds.first !== null && bounds.last !== null ? (
              <Marker at={violationSeq} first={bounds.first} last={bounds.last} label="violation" tone="red" />
            ) : null}
          </div>
          <p className="num text-[10px] text-ink-3" data-testid="replay-cursor-label">
            {`seq ${cursorSeq} of ${bounds.last ?? 0} · sim ${simClock(world.lastSimTimeS)} · ${world.eventsApplied} of ${world.eventsConsidered} events folded into state`}
          </p>
        </div>
      </div>

      {/* ---------------- problems ---------------- */}
      <div className="shrink-0">
        {unsupported !== undefined ? (
          <HatchStrip tone="red" className="m-2" >
            <span data-testid="replay-unsupported">
              <strong className="font-semibold">This recording cannot be reconstructed.</strong> {unsupported.message}
            </span>
          </HatchStrip>
        ) : null}
        {gaps.length > 0 ? (
          <HatchStrip tone="amber" className="m-2">
            {gaps.length} recording gap{gaps.length === 1 ? "" : "s"} in this durable log. State between the marked
            sequence ranges was never recorded and is not being invented here.
          </HatchStrip>
        ) : null}
        {world.problems.filter((p) => p.kind !== "unsupported_version").length > 0 ? (
          <Strip tone="amber" className="m-2">
            <ul className="space-y-0.5 text-[10px]">
              {world.problems
                .filter((p) => p.kind !== "unsupported_version")
                .slice(0, 4)
                .map((p, i) => (
                  <li key={i}>{p.message}</li>
                ))}
            </ul>
          </Strip>
        ) : null}
      </div>

      {/* ---------------- rebuilt world ---------------- */}
      <div className="scroll-y min-h-0 flex-1">
        <dl className="grid grid-cols-3 gap-2 border-b border-rule px-3 py-2">
          <Stat label="robots" value={String(world.robots.size)} />
          <Stat label="zones" value={String(world.zones.size)} />
          <Stat label="tasks completed" value={String([...world.tasks.values()].filter((t) => t.completed).length)} />
          <Stat label="dynamic obstacles" value={String(world.obstacles.size)} />
          <Stat label="alerts at this point" value={String(world.alerts.length)} />
          <Stat label="recorded events" value={String(eventCount)} />
        </dl>

        <section className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">robots at the cursor</h3>
          <ul className="px-3 pb-2 text-[11px]">
            {[...world.robots.values()].map((robot) => (
              <li key={robot.robot_id} className="num flex flex-wrap items-center gap-2 py-0.5 text-ink-2">
                <span className="text-ink">{robot.robot_id}</span>
                <span>
                  {robot.x === null || robot.y === null ? "pose unavailable" : `${robot.x.toFixed(2)}, ${robot.y.toFixed(2)}`}
                </span>
                <span className="text-ink-3">
                  {robot.holding_zone === null ? "holding nothing" : `holding ${robot.holding_zone}`}
                </span>
                {robot.stop_reason !== null ? <Chip tone="amber">{robot.stop_reason}</Chip> : null}
                {robot.degraded ? <Chip tone="amber">degraded</Chip> : null}
                {robot.faulted ? <Chip tone="red">faulted</Chip> : null}
              </li>
            ))}
          </ul>
        </section>

        <section className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">
            completed tasks at the cursor ({[...world.tasks.values()].filter((t) => t.completed).length})
          </h3>
          <ul className="num px-3 pb-2 text-[11px] text-ink-2" data-testid="replay-completed-tasks">
            {[...world.tasks.values()]
              .filter((task) => task.completed)
              .map((task) => (
                <li key={task.task_id}>
                  {task.task_id} · completed at seq {task.completed_at_seq}
                </li>
              ))}
          </ul>
        </section>

        <section className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">alerts at the cursor ({world.alerts.length})</h3>
          <ul className="px-3 pb-2 text-[11px]">
            {world.alerts.map((alert) => (
              <li key={alert.seq} className="num py-0.5">
                <span className="text-red">seq {alert.seq}</span>{" "}
                <span className="text-ink-2">{alert.reason}</span>{" "}
                <span className="text-ink-3">{simClock(alert.sim_time_s)}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">events up to the cursor ({sliced.length})</h3>
          <DataTable
            caption="Recorded events up to the replay cursor"
            columns={columns}
            rows={sliced.toReversed().slice(0, 300)}
            rowKey={(e) => String(e.seq)}
            sort={null}
            onSort={() => {}}
          />
        </section>
      </div>

      <div className="shrink-0 border-t border-rule px-3 py-1">
        <p className="num text-[10px] text-ink-3">
          recording {simClock(firstSimTimeS)} → {simClock(lastSimTimeS)} · {eventCount} events
          {notes !== null ? ` · ${notes}` : ""}
        </p>
      </div>
    </div>
  )
}

function Marker({
  at,
  first,
  last,
  label,
  tone,
}: {
  at: number
  first: number
  last: number
  label: string
  tone: "amber" | "red"
}) {
  const span = Math.max(1, last - first)
  const left = ((at - first) / span) * 100
  return (
    <span
      aria-hidden="true"
      title={label}
      className={`absolute top-[2px] h-[10px] w-[2px] ${tone === "red" ? "bg-red" : "bg-amber"}`}
      style={{ left: `${Math.min(100, Math.max(0, left))}%` }}
    />
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="stencil text-[9px] text-ink-3">{label}</dt>
      <dd className="num text-[14px] text-ink">{value}</dd>
    </div>
  )
}
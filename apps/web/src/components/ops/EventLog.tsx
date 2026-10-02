/**
 * Durable event log.
 *
 * This is the evidence, so it is rendered as evidence: monotonically sequenced,
 * severity-marked with a glyph as well as a colour, filterable by category, and
 * explicitly short-circuited when a recording gap means the sequence is not
 * contiguous. A gap is printed in the stream at the place it happened — it is
 * not silently stitched over.
 */
import { useMemo, useState } from "react"
import type { DomainEvent } from "@niharamesh/contracts/generated"
import type { EventFilters } from "../../lib/api/queries"
import type { RecordingGap } from "../../lib/api/types"
import { UNAVAILABLE, simClock, utc } from "../../lib/format"
import { Chip } from "../primitives/Chip"
import { DataTable, sortRows, type Column, type SortDir } from "../primitives/DataTable"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"

const CATEGORIES = ["authority", "safety", "task", "planning", "evaluation", "fault", "command", "lifecycle"] as const

const SEVERITY_TONE: Record<string, Tone> = {
  info: "muted",
  attention: "amber",
  fault: "red",
  violation: "red",
}

export function EventLog({
  events,
  gaps,
  filters,
  onFiltersChange,
  hasMore,
  nextSeq,
  isFetching,
  onLoadMore,
  mode,
}: {
  events: DomainEvent[]
  gaps: RecordingGap[]
  filters: EventFilters
  onFiltersChange: (next: EventFilters) => void
  hasMore: boolean
  nextSeq: number
  isFetching: boolean
  onLoadMore: () => void
  mode: "live" | "replay"
}) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir }>({ key: "seq", dir: "desc" })
  const [category, setCategory] = useState<string | null>(null)

  const columns: Column<DomainEvent>[] = useMemo(
    () => [
      { key: "seq", header: "seq", mono: true, width: "64px", sortValue: (e) => e.seq, render: (e) => e.seq },
      {
        key: "sim",
        header: "sim s",
        mono: true,
        width: "72px",
        sortValue: (e) => e.sim_time_s ?? Number.NEGATIVE_INFINITY,
        render: (e) => simClock(e.sim_time_s ?? null),
      },
      {
        key: "sev",
        header: "sev",
        width: "56px",
        sortValue: (e) => e.severity ?? "info",
        render: (e) => (
          <Chip tone={SEVERITY_TONE[e.severity ?? "info"] ?? "muted"}>{e.severity ?? "info"}</Chip>
        ),
      },
      { key: "cat", header: "category", width: "86px", sortValue: (e) => e.category, render: (e) => e.category },
      {
        key: "who",
        header: "robot / zone / task",
        width: "150px",
        render: (e) => (
          <span className="num text-[10px] text-ink-3">
            {e.robot_id ?? "—"}
            {e.zone_id != null ? ` · ${e.zone_id}` : ""}
            {e.task_id != null ? ` · ${e.task_id}` : ""}
          </span>
        ),
      },
      { key: "type", header: "event", sortValue: (e) => e.type, render: (e) => <span className="num">{e.type}</span> },
      {
        key: "reason",
        header: "reason",
        render: (e) => <span className="text-[11px] text-ink-2">{e.reason ?? e.payload ? formatPayload(e) : "—"}</span>,
      },
      {
        key: "domain",
        header: "clock",
        width: "96px",
        sortValue: (e) => e.time_domain,
        render: (e) => (
          <span className="num text-[10px] text-ink-3" title={`received ${utc(new Date(e.receive_time_ns / 1e6).toISOString())}`}>
            {e.time_domain}
          </span>
        ),
      },
    ],
    [],
  )

  const rows = useMemo(() => {
    const filtered = category === null ? events : events.filter((e) => e.category === category)
    return sortRows(filtered, sort.key, sort.dir, columns)
  }, [events, category, sort, columns])

  return (
    <Panel className="min-h-0" ticks aria-label="Durable event log">
      <PanelHeader
        title={mode === "replay" ? "recorded events" : "durable event log"}
        subtitle={`${events.length} loaded · next seq ${nextSeq}${hasMore ? " · more available" : " · complete"}`}
        tone={gaps.length > 0 ? "amber" : "info"}
        right={
          <div className="flex items-center gap-1">
            <label className="sr-only" htmlFor="event-category">
              Filter events by category
            </label>
            <select
              id="event-category"
              value={category ?? ""}
              onChange={(event) => setCategory(event.target.value === "" ? null : event.target.value)}
              className="border border-rule bg-raised px-1 py-0.5 text-[10px] text-ink-2"
            >
              <option value="">all categories</option>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            {hasMore ? (
              <button
                type="button"
                onClick={onLoadMore}
                disabled={isFetching}
                className="border border-rule px-1.5 py-0.5 text-[10px] text-ink-2 hover:border-rule-strong hover:text-ink disabled:text-ink-4"
              >
                {isFetching ? "loading…" : "load older"}
              </button>
            ) : null}
          </div>
        }
      />
      <PanelBody>
        {/* Entity filters. These narrow the *server* query, so the count shown
            always matches what was actually fetched. */}
        <div className="flex flex-wrap items-end gap-1.5 border-b border-rule px-2 py-1.5">
          <FilterInput
            id="event-robot"
            label="robot"
            value={filters.robotId ?? ""}
            onChange={(value) => onFiltersChange({ ...filters, robotId: value === "" ? undefined : value })}
          />
          <FilterInput
            id="event-zone"
            label="zone"
            value={filters.zoneId ?? ""}
            onChange={(value) => onFiltersChange({ ...filters, zoneId: value === "" ? undefined : value })}
          />
          <FilterInput
            id="event-task"
            label="task"
            value={filters.taskId ?? ""}
            onChange={(value) => onFiltersChange({ ...filters, taskId: value === "" ? undefined : value })}
          />
          <button
            type="button"
            onClick={() =>
              onFiltersChange({
                limit: filters.limit ?? 200,
                afterSeq: filters.afterSeq,
              })
            }
            className="border border-rule px-1.5 py-0.5 text-[10px] text-ink-2 hover:border-rule-strong hover:text-ink"
          >
            clear filters
          </button>
        </div>
        {gaps.length > 0 ? (
          <div className="px-2 pt-2">
            <HatchStrip tone="amber">
              <div>
                <strong className="font-semibold">
                  {gaps.length} recording gap{gaps.length === 1 ? "" : "s"}.
                </strong>{" "}
                Durable evidence is missing between the following sequence ranges, so the log below is not contiguous
                and any metric derived from it is marked incomplete.
              </div>
            </HatchStrip>
            <ul className="mt-1.5 space-y-0.5">
              {gaps.slice(0, 6).map((gap) => (
                <li key={`${gap.from_seq}-${gap.to_seq}`} className="num flex flex-wrap gap-2 text-[10px] text-ink-3">
                  <span className="text-amber">
                    seq {gap.from_seq}–{gap.to_seq}
                  </span>
                  <span>{gap.category}</span>
                  <span>
                    {simClock(gap.sim_time_from_s)} → {simClock(gap.sim_time_to_s)}
                  </span>
                  <span>{gap.cause}</span>
                  {gap.recovered === true ? <span className="text-teal">recovered</span> : <span className="text-amber">unrecovered</span>}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {mode === "replay" ? (
          <Strip tone="steel" className="mx-2 mt-2">
            <span className="text-[10px]">Recorded playback. This log is the recording, not a fresh simulation.</span>
          </Strip>
        ) : null}

        <DataTable
          caption="Durable domain events for the selected run"
          columns={columns}
          rows={rows}
          rowKey={(e) => `${e.seq}-${e.type}`}
          sort={sort}
          onSort={(key) =>
            setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "desc" }))
          }
          emptyBody={
            <p className="p-3 text-[12px] text-ink-3">
              No durable events match this filter. That is a statement about the filter, not evidence that nothing
              happened.
            </p>
          }
        />

        <p className="num px-3 py-1.5 text-[10px] text-ink-3">
          filters: robot {filters.robotId ?? "any"} · zone {filters.zoneId ?? "any"} · task {filters.taskId ?? "any"}{" "}
          {filters.afterSeq === undefined ? "· from start" : `· after seq ${filters.afterSeq}`}
        </p>
      </PanelBody>
    </Panel>
  )
}

function FilterInput({
  id,
  label,
  value,
  onChange,
}: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
}) {
  return (
    <label className="flex items-center gap-1 text-[10px] text-ink-3">
      <span className="stencil text-[9px]">{label}</span>
      <input
        id={id}
        value={value}
        placeholder="any"
        onChange={(event) => onChange(event.target.value)}
        className="num w-[110px] border border-rule bg-raised px-1 py-0.5 text-[10px] text-ink"
      />
    </label>
  )
}

function formatPayload(event: DomainEvent): string {
  const payload = event.payload
  if (payload === undefined || Object.keys(payload).length === 0) return UNAVAILABLE
  return Object.entries(payload)
    .slice(0, 4)
    .map(([key, value]) => `${key}=${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
    .join(" ")
}
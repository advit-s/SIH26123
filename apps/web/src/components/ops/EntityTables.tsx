/**
 * Accessible entity tables — the real alternative to the canvas.
 *
 * These are not a fallback. They are the same data in a form that can be read,
 * sorted, screen-read and printed. Clicking a row selects the same entity the
 * canvas would, and the selection is shared, so the two views never disagree.
 */
import { useMemo, useState } from "react"
import type { RobotInspection, TaskInspection, ZoneInspection } from "../../lib/api/types"
import { UNAVAILABLE, age, metres, simClock } from "../../lib/format"
import { robotColor, robotGlyph, robotIndexLabel } from "../../lib/robotColor"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { DataTable, sortRows, type Column, type SortDir } from "../primitives/DataTable"
import { WhyWaitingChip } from "./WhyWaitingCard"

function useSort<T>(source: readonly T[], columns: Column<T>[], initial: { key: string; dir: SortDir } = { key: "", dir: "desc" }) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir }>(initial)
  const rows = useMemo(() => sortRows(source, sort.key, sort.dir, columns), [source, sort, columns])
  const onSort = (key: string) =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }))
  return { rows, sort, onSort }
}

export function RobotTable({
  robots,
  poseAges,
}: {
  robots: RobotInspection[]
  /** Live per-robot evidence age, or null when the stream has nothing. */
  poseAges: Map<string, number | null>
}) {
  const theme = useViewStore((s) => s.theme)
  const selection = useViewStore((s) => s.selection)
  const select = useViewStore((s) => s.select)

  const columns: Column<RobotInspection>[] = [
    {
      key: "id",
      header: "robot",
      mono: true,
      width: "118px",
      sortValue: (r) => r.robot_id,
      render: (r) => (
        <span className="flex items-center gap-1.5 whitespace-nowrap">
          <span aria-hidden="true" style={{ color: robotColor(r.robot_id, theme) }}>
            {robotGlyph(r.robot_id)}
          </span>
          <span>{r.robot_id}</span>
          <span className="text-ink-4">#{robotIndexLabel(r.robot_id)}</span>
        </span>
      ),
    },
    {
      key: "pose",
      header: "pose x, y",
      mono: true,
      width: "128px",
      sortValue: (r) => r.pose_estimate?.pose.x ?? Number.NEGATIVE_INFINITY,
      render: (r) =>
        r.pose_estimate === null ? (
          <span className="text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <span className="whitespace-nowrap">
            {r.pose_estimate.pose.x.toFixed(2)}, {r.pose_estimate.pose.y.toFixed(2)}
          </span>
        ),
    },
    {
      key: "browserage",
      header: "browser age",
      mono: true,
      width: "110px",
      sortValue: (r) => poseAges.get(r.robot_id) ?? Number.POSITIVE_INFINITY,
      render: (r) => {
        // Browser-side evidence age only. The agent's own declared age is a
        // different fact and is shown separately so the two are never conflated.
        const a = poseAges.get(r.robot_id) ?? null
        if (a === null) return <span className="whitespace-nowrap text-amber">no telemetry</span>
        return <span className={a > 2.5 ? "text-amber" : "text-ink-2"}>{age(a)}</span>
      },
    },
    {
      key: "agentage",
      header: "agent age",
      mono: true,
      width: "88px",
      sortValue: (r) => r.pose_age_s ?? Number.POSITIVE_INFINITY,
      render: (r) =>
        r.pose_age_s === null ? (
          <span className="whitespace-nowrap text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <span className="whitespace-nowrap text-ink-3">{age(r.pose_age_s)}</span>
        ),
    },
    {
      key: "motion",
      header: "motion",
      width: "150px",
      sortValue: (r) => r.motion?.stop_reason ?? "none",
      render: (r) =>
        r.motion === null ? (
          <span className="text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <span className="flex flex-wrap items-center gap-1">
            <span className="num">{r.motion.linear_velocity_mps ?? "—"} m/s</span>
            <Chip tone={r.motion.stop_reason === "none" ? "teal" : "amber"}>{r.motion.stop_reason}</Chip>
          </span>
        ),
    },
    {
      key: "battery",
      header: "battery",
      mono: true,
      width: "120px",
      sortValue: (r) => r.battery?.fraction ?? Number.NEGATIVE_INFINITY,
      render: (r) =>
        r.battery === null || r.battery.fraction == null ? (
          <span className="text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <span>
            {Math.round(r.battery.fraction * 100)}%{" "}
            <span className="text-[10px] text-ink-3">({r.battery.source})</span>
          </span>
        ),
    },
    {
      key: "task",
      header: "task",
      width: "130px",
      sortValue: (r) => r.task?.task_id ?? "",
      render: (r) => <span className="num">{r.task?.task_id ?? "—"}</span>,
    },
    {
      key: "why",
      header: "why waiting",
      width: "110px",
      sortValue: (r) => (r.why_waiting?.blocked === true ? 1 : 0),
      render: (r) => <WhyWaitingChip why={r.why_waiting} />,
    },
  ]

  const { rows, sort, onSort } = useSort(robots, columns)

  return (
    <DataTable
      caption="Robots in this run, with pose, evidence age, motion state, battery provenance, task and blocking reason"
      columns={columns}
      rows={rows}
      rowKey={(r) => r.robot_id}
      sort={sort}
      onSort={onSort}
      selectedKey={selection?.kind === "robot" ? selection.id : null}
      onRowClick={(r) => select("robot", r.robot_id)}
      emptyBody={<p className="p-3 text-[12px] text-ink-3">This run has no robot agents, so there is nothing to inspect.</p>}
    />
  )
}

export function ZoneTable({ zones }: { zones: ZoneInspection[] }) {
  const selection = useViewStore((s) => s.selection)
  const select = useViewStore((s) => s.select)

  const columns: Column<ZoneInspection>[] = [
    { key: "id", header: "zone", mono: true, sortValue: (z) => z.zone_id, render: (z) => z.zone_id },
    {
      key: "authority",
      header: "authority",
      width: "150px",
      sortValue: (z) => z.authority,
      render: (z) => <ZoneAuthorityCell zone={z} />,
    },
    {
      key: "holder",
      header: "holder",
      width: "100px",
      sortValue: (z) => z.authority_holder ?? "",
      render: (z) => <span className="num">{z.authority_holder ?? "—"}</span>,
    },
    {
      key: "physical",
      header: "physical occupancy",
      width: "140px",
      sortValue: (z) => z.physical_occupancy,
      render: (z) => (
        <span className={z.physical_occupancy === "occupied" ? "text-red" : "text-ink-2"}>
          {z.physical_occupancy.replace(/_/g, " ")}
        </span>
      ),
    },
    {
      key: "evaluator",
      header: "evaluator",
      width: "110px",
      sortValue: (z) => (z.evaluator_occupancy === true ? 1 : 0),
      render: (z) =>
        z.evaluator_occupancy === null ? (
          <span className="text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <Chip tone="steel">{z.evaluator_occupancy ? "occupied" : "clear"}</Chip>
        ),
    },
    {
      key: "entry",
      header: "entry",
      width: "120px",
      sortValue: (z) => (z.entry_withheld ? 1 : 0),
      render: (z) => (z.entry_withheld ? <Chip tone="amber">withheld</Chip> : <Chip tone="teal">permitted</Chip>),
    },
    {
      key: "entries",
      header: "entries",
      mono: true,
      width: "70px",
      sortValue: (z) => z.entries,
      render: (z) => z.entries,
    },
  ]

  const { rows, sort, onSort } = useSort(zones, columns)

  return (
    <DataTable
      caption="Exclusive zones with authority state, conservative physical occupancy, evaluator verdict and the entry decision"
      columns={columns}
      rows={rows}
      rowKey={(z) => z.zone_id}
      sort={sort}
      onSort={onSort}
      selectedKey={selection?.kind === "zone" ? selection.id : null}
      onRowClick={(z) => select("zone", z.zone_id)}
      emptyBody={
        <p className="p-3 text-[12px] text-ink-3">
          This map declares no exclusive zones, so there is no coordination to show. That is a property of the
          scenario, not a missing panel.
        </p>
      }
    />
  )
}

function ZoneAuthorityCell({ zone }: { zone: ZoneInspection }) {
  const tone =
    zone.authority === "held" || zone.authority === "granted_pending_entry"
      ? "teal"
      : zone.authority === "occupied" || zone.authority === "contested"
        ? "red"
        : zone.authority === "free"
          ? "muted"
          : "amber"
  return <Chip tone={tone}>{zone.authority.replace(/_/g, " ")}</Chip>
}

export function TaskTable({ tasks }: { tasks: TaskInspection[] }) {
  const selection = useViewStore((s) => s.selection)
  const select = useViewStore((s) => s.select)

  const columns: Column<TaskInspection>[] = [
    { key: "id", header: "task", mono: true, sortValue: (t) => t.task_id, render: (t) => t.task_id },
    {
      key: "route",
      header: "pickup → drop",
      width: "190px",
      sortValue: (t) => (t.task === null ? "" : `${t.task.pickup_station_id}${t.task.drop_station_id}`),
      render: (t) =>
        t.task === null ? (
          <span className="text-ink-3">{UNAVAILABLE}</span>
        ) : (
          <span className="num">
            {t.task.pickup_station_id} → {t.task.drop_station_id}
          </span>
        ),
    },
    {
      key: "owner",
      header: "owner",
      width: "100px",
      sortValue: (t) => t.owner ?? "",
      render: (t) => <span className="num">{t.owner ?? "unowned"}</span>,
    },
    {
      key: "state",
      header: "state",
      width: "140px",
      sortValue: (t) => t.ownership_state,
      render: (t) => (
        <span className="flex flex-wrap items-center gap-1">
          <Chip tone={t.completed ? "teal" : t.owner === null ? "muted" : "amber"}>{t.ownership_state}</Chip>
          {t.completed ? <Chip tone="teal">completed</Chip> : null}
        </span>
      ),
    },
    {
      key: "version",
      header: "own. v",
      mono: true,
      width: "70px",
      sortValue: (t) => t.ownership_version,
      render: (t) => t.ownership_version,
    },
    {
      key: "bids",
      header: "bids",
      mono: true,
      width: "110px",
      sortValue: (t) => t.bids.length,
      render: (t) => `${t.feasible_bids} ok / ${t.infeasible_bids} no`,
    },
    {
      key: "custody",
      header: "custody",
      width: "150px",
      sortValue: (t) => t.custody?.state ?? "",
      render: (t) =>
        t.custody === null || t.custody.state == null ? (
          <span className="text-ink-3">none</span>
        ) : (
          <span className="num text-[11px]">
            {t.custody.state}
            {t.custody.holder != null ? ` · ${t.custody.holder}` : ""}
          </span>
        ),
    },
  ]

  const { rows, sort, onSort } = useSort(tasks, columns)

  return (
    <DataTable
      caption="Tasks with ownership version, bid feasibility, custody state and completion status"
      columns={columns}
      rows={rows}
      rowKey={(t) => t.task_id}
      sort={sort}
      onSort={onSort}
      selectedKey={selection?.kind === "task" ? selection.id : null}
      onRowClick={(t) => select("task", t.task_id)}
      emptyBody={
        <p className="p-3 text-[12px] text-ink-3">
          No task queue was published for this run. An empty queue is not evidence that the allocation policy is fast.
        </p>
      }
    />
  )
}

/** Selection summary in words — required for anyone not using the canvas. */
export function SelectionSummary({
  robots,
  zones,
  tasks,
}: {
  robots: RobotInspection[]
  zones: ZoneInspection[]
  tasks: TaskInspection[]
}) {
  const selection = useViewStore((s) => s.selection)
  if (selection === null) {
    return (
      <p className="px-3 py-1.5 text-[11px] text-ink-3" data-testid="selection-summary">
        Nothing selected. Pick a robot, zone or task — from the map or from the tables below.
      </p>
    )
  }
  if (selection.kind === "robot") {
    const robot = robots.find((r) => r.robot_id === selection.id)
    if (robot === undefined) return <p className="px-3 py-1.5 text-[11px] text-amber">Selected robot {selection.id} is no longer present in this run.</p>
    const pose = robot.pose_estimate?.pose
    return (
      <p className="num px-3 py-1.5 text-[11px] text-ink-2" data-testid="selection-summary">
        <span className="stencil text-ink-3">selected </span>
        {robot.robot_id} — {pose === undefined ? "pose unavailable" : `${metres(pose.x)} E, ${metres(pose.y)} N`} —{" "}
        {robot.motion?.stop_reason ?? "motion unknown"} —{" "}
        {robot.why_waiting?.blocked === true ? robot.why_waiting.reason : "not blocked"}
        {robot.recent_events.length > 0 ? (
          <span className="text-ink-3"> · latest event seq {robot.recent_events[robot.recent_events.length - 1]?.seq ?? "—"}</span>
        ) : null}
        {robot.pose_age_s !== null ? <span className="text-ink-3"> · pose age {age(robot.pose_age_s)}</span> : null}
      </p>
    )
  }
  if (selection.kind === "zone") {
    const zone = zones.find((z) => z.zone_id === selection.id)
    if (zone === undefined) return <p className="px-3 py-1.5 text-[11px] text-amber">Selected zone {selection.id} is not in this map.</p>
    return (
      <p className="num px-3 py-1.5 text-[11px] text-ink-2" data-testid="selection-summary">
        <span className="stencil text-ink-3">selected zone </span>
        {zone.zone_id} — authority {zone.authority.replace(/_/g, " ")} —{" "}
        {zone.authority_holder !== null ? `held by ${zone.authority_holder}` : "unheld"} —{" "}
        {zone.entry_withheld ? `entry withheld: ${zone.entry_withheld_reason ?? "reason unavailable"}` : "entry permitted"}
        {zone.evaluator_occupancy !== null ? ` · evaluator ${zone.evaluator_occupancy ? "occupied" : "clear"}` : ""}
      </p>
    )
  }
  const task = tasks.find((t) => t.task_id === selection.id)
  if (task === undefined) return <p className="px-3 py-1.5 text-[11px] text-amber">Selected task {selection.id} is not in this queue.</p>
  return (
    <p className="num px-3 py-1.5 text-[11px] text-ink-2" data-testid="selection-summary">
      <span className="stencil text-ink-3">selected task </span>
      {task.task_id} — {task.ownership_state} — owner {task.owner ?? "none"} v{task.ownership_version} —{" "}
      {task.bids.length} bid{task.bids.length === 1 ? "" : "s"} —{" "}
      {task.completion_evidence === null ? "no completion evidence" : `completed at seq ${task.completion_evidence.seq}`}
      {task.task?.release_at_s != null ? ` · released ${simClock(task.task.release_at_s)}` : ""}
    </p>
  )
}
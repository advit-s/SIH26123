/**
 * The persistent context bar.
 *
 * This is the one component that is always on screen, and it is deliberately
 * *not* a KPI row. Vanity metrics change under a reviewer's finger; execution
 * mode, run identity, evidence freshness and clock domain do not. So the bar
 * answers, left to right:
 *
 *   1. What am I looking at? (mode plate — the most visually dominant object)
 *   2. Which run, which immutable scenario revision?
 *   3. Which clock is this, and in which domain?
 *   4. How fresh is the evidence, and is the recording intact?
 *
 * Density: eleven cells have to survive 1440x900 and stay readable at
 * 1280x720. So every label is one line and every value *truncates* with its full
 * text in a `title`, rather than wrapping (which would make the bar taller than
 * its own content) or overflowing (which would clip the evidence state). A
 * truncated identifier is still verifiable by hovering; a clipped one is not.
 */
import { useMemo } from "react"
import type { ReactNode } from "react"
import type { HealthStatus, RunStateSnapshot, StreamStatus } from "../../lib/api/types"
import { UNAVAILABLE, age, outcomeLabel, simClock, speed, speedLong, utc, utcTime } from "../../lib/format"
import { resolveExecution } from "../../lib/view/executionMode"
import { Chip } from "../primitives/Chip"
import type { Tone } from "../primitives/tone"

export interface ContextBarProps {
  state: RunStateSnapshot | null
  health: HealthStatus | null | undefined
  streamStatus: StreamStatus
  streamAgeS: number | null
  replaying: boolean
  physicalActuation: boolean
  onOpenSystem?: () => void
}

const TONE_BORDER: Record<Tone, string> = {
  teal: "border-teal",
  amber: "border-amber",
  red: "border-red",
  steel: "border-steel",
  muted: "border-rule",
  info: "border-rule-strong",
}
const TONE_TEXT: Record<Tone, string> = {
  teal: "text-teal",
  amber: "text-amber",
  red: "text-red",
  steel: "text-steel",
  muted: "text-ink-3",
  info: "text-ink-2",
}
const TONE_BG: Record<Tone, string> = {
  teal: "bg-teal-wash",
  amber: "bg-amber-wash",
  red: "bg-red-wash",
  steel: "bg-steel-wash",
  muted: "bg-raised",
  info: "bg-raised",
}

export function ContextBar(props: ContextBarProps) {
  const { state, health, streamStatus, streamAgeS, replaying, physicalActuation } = props
  const execution = useMemo(
    () => resolveExecution(state, { physicalActuation, replaying }),
    [state, physicalActuation, replaying],
  )

  const connection: { tone: Tone; label: string } =
    streamStatus === "live"
      ? { tone: "teal", label: "stream live" }
      : streamStatus === "connecting"
        ? { tone: "amber", label: "connecting" }
        : streamStatus === "reconnecting"
          ? { tone: "amber", label: "reconnecting" }
          : streamStatus === "error"
            ? { tone: "red", label: "stream error" }
            : streamStatus === "closed"
              ? { tone: "muted", label: "stream closed" }
              : { tone: "amber", label: "stream idle" }

  const platePaint = execution.paint === "replay" ? "replay-band" : execution.paint === "hatch" ? "hatch-amber" : ""

  const runId = state?.run_id ?? UNAVAILABLE
  const scenario =
    state === null || state === undefined || state.scenario_id === null
      ? UNAVAILABLE
      : `${state.scenario_id} r${state.scenario_revision ?? "?"}`
  const map =
    state === null || state === undefined || state.map_id === null ? UNAVAILABLE : `${state.map_id} r${state.map_revision ?? "?"}`

  return (
    <header
      className="flex shrink-0 items-stretch overflow-hidden border-b border-rule bg-panel"
      data-testid="context-bar"
      aria-label="Execution context"
    >
      {/* 1. Mode plate — the loudest thing in the bar. */}
      <div
        className={`flex w-[218px] shrink-0 flex-col justify-center border-r px-3 py-1.5 ${TONE_BORDER[execution.tone]} ${TONE_BG[execution.tone]} ${platePaint}`}
        data-testid="execution-plate"
        data-execution-kind={execution.kind}
        data-frozen={execution.frozen ? "true" : "false"}
      >
        <div className="flex items-center gap-1.5">
          <span aria-hidden="true" className={`text-[10px] ${TONE_TEXT[execution.tone]}`}>
            {execution.frozen ? "❚❚" : "▶"}
          </span>
          <span className={`stencil truncate text-[11px] ${TONE_TEXT[execution.tone]}`} data-testid="execution-mode">
            {execution.plate}
          </span>
        </div>
        <p className="mt-0.5 truncate text-[10px] leading-tight text-ink-3" title={execution.caption}>
          {execution.caption}
        </p>
      </div>

      {/* 2. Run identity. */}
      <Cell label="run" grow={3} title={runId}>
        <span className="num block truncate text-[12px] text-ink" data-testid="context-run-id">
          {runId}
        </span>
      </Cell>
      <Cell label="scenario" grow={3} title={`${scenario}${state?.scenario_digest ? ` · digest ${state.scenario_digest}` : ""}`}>
        <span className="num block truncate text-[12px] text-ink">{scenario}</span>
      </Cell>
      <Cell label="map" grow={2} title={map}>
        <span className="num block truncate text-[12px] text-ink">{map}</span>
      </Cell>

      {/* 3. Clocks — each in its own domain, named. */}
      <Cell label="sim s · logical" grow={2} title="Simulation seconds in the injected logical clock domain">
        <span className="num block truncate text-[13px] text-ink" data-testid="context-sim-time">
          {simClock(state?.sim_time_s ?? null)}
        </span>
        {state?.max_sim_time_s != null ? (
          <span className="num block truncate text-[9px] text-ink-3">of {simClock(state.max_sim_time_s)}</span>
        ) : null}
      </Cell>
      <Cell
        label="wall · UTC"
        grow={2}
        title={`${utc(state?.wall_time_utc ?? null)} — display UTC, for humans only, never used for expiry`}
      >
        <span className="num block truncate text-[12px] text-ink">{utcTime(state?.wall_time_utc ?? null)}</span>
      </Cell>
      <Cell label="speed" grow={2} title={`harness speed ${speedLong(state?.speed_multiplier ?? null)}`}>
        <span className="num block truncate text-[12px] text-ink">{speed(state?.speed_multiplier ?? null)}</span>
      </Cell>

      {/* 4. Fleet, policy, evidence. */}
      <Cell label="fleet" grow={2} title="Independent robot agent processes attached to this run">
        <span className="num block truncate text-[12px] text-ink">
          {state?.robot_count ?? 0}
          <span className="ml-1 text-[10px] text-ink-3">agents</span>
        </span>
      </Cell>
      <Cell label="coordination" grow={4} title={`coordination ${state?.coordination_policy ?? "unknown"}`}>
        <span className="num block truncate text-[12px] text-ink">{state?.coordination_policy ?? UNAVAILABLE}</span>
        {state?.assignment_policy != null ? (
          <span className="num block truncate text-[9px] text-ink-3">{state.assignment_policy}</span>
        ) : null}
      </Cell>
      <Cell label="run state" grow={3} minW="86px">
        <Chip tone={state == null ? "muted" : state.state === "unsafe" ? "red" : state.state === "completed" ? "teal" : "amber"}>
          {state == null ? UNAVAILABLE : outcomeLabel(state.state, state.outcome)}
        </Chip>
      </Cell>
      <Cell label="evidence" grow={3} title="Age of the newest telemetry frame actually received by this browser.">
        <span
          className={`block truncate text-[11px] ${
            connection.tone === "teal" ? "text-teal" : connection.tone === "red" ? "text-red" : "text-amber"
          }`}
        >
          <span aria-hidden="true">{connection.tone === "teal" ? "●" : "▲"}</span> {connection.label}
        </span>
        <span className="num block truncate text-[9px] text-ink-3">
          {streamAgeS === null ? "no telemetry" : `${age(streamAgeS)} old`}
        </span>
      </Cell>
      <Cell label="recording" grow={2} title="Durable evidence health for this run.">
        {state == null ? (
          <span className="block truncate text-[12px] text-ink-3">{UNAVAILABLE}</span>
        ) : state.recording_healthy && state.recording_gaps.length === 0 ? (
          <Chip tone="teal">complete</Chip>
        ) : (
          <Chip tone="amber" title={`${state.recording_gaps.length} gap(s) in durable evidence`}>
            {state.recording_gaps.length} gap{state.recording_gaps.length === 1 ? "" : "s"}
          </Chip>
        )}
      </Cell>

      {/* Health / build identity, right-aligned and compact. */}
      <div className="ml-auto flex w-[150px] shrink-0 items-center gap-1.5 border-l border-rule px-2.5 py-1.5">
        {health === null || health === undefined ? (
          <span className="block truncate text-[11px] text-ink-3">api unknown</span>
        ) : health.status === "ok" ? (
          <Chip tone="teal" title={`API ${health.version} · schema ${health.schema_version} · protocol ${health.protocol_version}`}>
            api ok
          </Chip>
        ) : (
          <Chip tone="amber" title={`API ${health.version}`}>
            api degraded
          </Chip>
        )}
        <span className="num block truncate text-[9px] text-ink-3" title={`v${health?.version ?? UNAVAILABLE} · schema ${health?.schema_version ?? UNAVAILABLE} · protocol ${health?.protocol_version ?? UNAVAILABLE}`}>
          {health?.version ?? UNAVAILABLE}
        </span>
        {props.onOpenSystem !== undefined ? (
          <button
            type="button"
            onClick={props.onOpenSystem}
            className="stencil ml-auto shrink-0 border border-rule px-1.5 py-[3px] text-[9px] text-ink-3 hover:border-rule-strong hover:text-ink"
          >
            system
          </button>
        ) : null}
      </div>
    </header>
  )
}

/**
 * One context cell. `grow` distributes the *remaining* bar width across the
 * cells in proportion, so the bar fits 1440 and 1280 exactly and never clips the
 * evidence state. Fixed-width cells would overflow; equal cells would starve the
 * run id.
 */
function Cell({
  label,
  children,
  grow,
  title,
  minW,
}: {
  label: string
  children: ReactNode
  grow: number
  title?: string
  minW?: string
}) {
  return (
    <div
      className="flex min-w-0 flex-col justify-center border-r border-rule px-2.5 py-1.5"
      style={{ flexGrow: grow, flexBasis: 0, minWidth: minW ?? "72px" }}
      title={title}
    >
      <span className="stencil block truncate whitespace-nowrap text-[9px] text-ink-3">{label}</span>
      <div className="min-w-0 overflow-hidden">{children}</div>
    </div>
  )
}
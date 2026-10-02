/**
 * Experiment-harness controls and the command lifecycle.
 *
 * Two rules this component exists to enforce:
 *
 * 1. **Nothing here is an emergency stop.** Every control is labelled as acting
 *    on the *experiment harness* or on *an operator request to one agent*. A
 *    browser button cannot stop a physical fleet, so it must never claim to.
 *
 * 2. **A sent command is not an observed stop.** The lifecycle is rendered as
 *    four distinct stages — requested → acknowledged → applied → *observed* —
 *    with the observed stage filled in only from evidence that the world
 *    actually changed. An operator request that has only been *requested* is
 *    rendered as an outstanding request, never as a stop.
 */
import { useState } from "react"
import { Pause, Play, SkipForward, Square, Zap } from "lucide-react"
import { useSendCommand } from "../../lib/api/queries"
import type { CommandRecord, CommandStageState, RunStateSnapshot } from "../../lib/api/types"
import { UNAVAILABLE } from "../../lib/format"
import { Button } from "../primitives/Button"
import { Chip } from "../primitives/Chip"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"

const STAGE_TONE: Record<CommandStageState["state"], Tone> = {
  unknown: "muted",
  requested: "info",
  acknowledged: "info",
  applied: "amber",
  observed: "teal",
  refused: "red",
  failed: "red",
}

/**
 * The four lifecycle stages, in order. `observed` is filled in only from
 * evidence that the world changed — never from the fact that we sent something.
 */
const STAGE_ORDER = ["requested", "acknowledged", "applied", "observed"] as const

function idempotencyKey(command: string): string {
  // A stable-per-click key. The API rejects replays of the same key, which is
  // how "request stop" cannot be double-counted by an impatient double-click.
  const stamp = new Date().toISOString().replace(/[^0-9]/g, "").slice(0, 17)
  return `cockpit-${command}-${stamp}`
}

export function CommandPanel({
  runId,
  state,
  records,
  physicalActuation,
}: {
  runId: string | null
  state: RunStateSnapshot | null
  records: CommandRecord[]
  physicalActuation: boolean
}) {
  const send = useSendCommand(runId)
  const [lastError, setLastError] = useState<string | null>(null)

  const issue = (command: string, params: Record<string, unknown> = {}) => {
    setLastError(null)
    send.mutate(
      { command, params, idempotency_key: idempotencyKey(command) },
      {
        onError: (error: unknown) => {
          setLastError(error instanceof Error ? error.message : "The command could not be submitted.")
        },
      },
    )
  }

  const isPaused = state?.paused === true
  const disabled = runId === null || send.isPending

  return (
    <Panel className="min-h-0 shrink-0" ticks aria-label="Experiment harness controls">
      <PanelHeader
        title="experiment harness — simulation"
        subtitle="these controls act on the lab, never on hardware"
        tone="amber"
        right={<Zap className="h-[11px] w-[11px] text-amber" aria-hidden />}
      />
      <PanelBody scroll={false}>
        <div className="px-3 py-2">
          <Strip tone="amber" className="border">
            <span className="text-[10px]">
              This panel controls the <strong className="font-semibold">simulation harness</strong>. It is not an
              emergency stop and it cannot stop a physical robot. Physical actuation is{" "}
              <strong className="font-semibold">{physicalActuation ? "ENABLED" : "disabled"}</strong> for this run.
            </span>
          </Strip>

          <div className="mt-2 flex flex-wrap gap-1.5">
            <Button
              variant="harness"
              disabled={disabled}
              onClick={() => issue(isPaused ? "resume" : "pause")}
              data-testid="cmd-pause"
            >
              {isPaused ? <Play className="h-[12px] w-[12px]" aria-hidden /> : <Pause className="h-[12px] w-[12px]" aria-hidden />}
              {isPaused ? "Resume simulation" : "Pause simulation"}
            </Button>
            <Button variant="harness" disabled={disabled} onClick={() => issue("step", { steps: 1 })}>
              <SkipForward className="h-[12px] w-[12px]" aria-hidden />
              Step one tick
            </Button>
            <Button variant="harness" disabled={disabled} onClick={() => issue("set_speed", { multiplier: 1 })}>
              1.00× speed
            </Button>
            <Button variant="harness" disabled={disabled} onClick={() => issue("set_speed", { multiplier: 4 })}>
              4.00× speed
            </Button>
          </div>

          <div className="mt-2 border-t border-rule pt-2">
            <p className="stencil text-[9px] text-ink-3">operator stop request</p>
            <p className="mt-0.5 text-[10px] text-ink-3">
              Sends a stop <em>request</em> to the named agent through the coordinator. Only the observed stage means
              the world has actually stopped.
            </p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {state?.robot_count === 0 || state === null ? (
                <span className="text-[11px] text-ink-3">No agents are attached to this run.</span>
              ) : null}
              <Button
                variant="danger"
                disabled={disabled || runId === null}
                onClick={() => issue("request_stop", { scope: "run" })}
                data-testid="cmd-request-stop"
              >
                <Square className="h-[11px] w-[11px]" aria-hidden />
                Request stop — whole run
              </Button>
              <Button variant="danger" disabled={disabled} onClick={() => issue("clear_stop", { scope: "run" })}>
                Clear stop requests
              </Button>
            </div>
          </div>

          {lastError !== null ? (
            <HatchStrip tone="red" className="mt-2">
              <span data-testid="command-error">
                <strong className="font-semibold">Command refused.</strong> {lastError}
              </span>
            </HatchStrip>
          ) : null}
        </div>

        {/* -------- command records -------- */}
        <div className="border-t border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">command records (requested ≠ observed)</h3>
          {records.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">
              No operator command has been issued against this run.
            </p>
          ) : (
            <ul className="px-2 pb-2">
              {records.toReversed().slice(0, 6).map((record) => (
                <li key={record.command_id} className="border-b border-rule/60 px-1 py-1.5 last:border-b-0">
                  <div className="flex items-center justify-between gap-2">
                    <span className="num text-[11px] text-ink">{record.command}</span>
                    <span className="num text-[9px] text-ink-3" title={record.idempotency_key}>
                      by {record.requested_by}
                    </span>
                  </div>
                  <ol className="mt-1 flex flex-wrap gap-1" aria-label={`Lifecycle of command ${record.command_id}`}>
                    {STAGE_ORDER.map((stage) => {
                      const value = record[stage]
                      return (
                        <li key={stage} className="flex items-center gap-1">
                          <Chip tone={STAGE_TONE[value.state]} title={value.detail ?? `stage ${stage}: ${value.state}`}>
                            {stage}
                          </Chip>
                        </li>
                      )
                    })}
                  </ol>
                  <p className="num mt-0.5 text-[9px] text-ink-3" data-testid={`command-stage-${record.command_id}`}>
                    {`requested=${record.requested.state} · acknowledged=${record.acknowledged.state} · applied=${record.applied.state} · observed=${record.observed.state}`}
                  </p>
                  {record.requested.state !== "unknown" && record.observed.state !== "observed" ? (
                    <p className="mt-0.5 text-[10px] text-amber">
                      Not observed yet. This command has been sent, not confirmed by evidence.
                    </p>
                  ) : null}
                  {record.observed.detail !== null ? (
                    <p className="mt-0.5 text-[10px] text-ink-2">{record.observed.detail}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="num px-3 py-1 text-[10px] text-ink-3">
          idempotency key {idempotencyKey("example")} pattern · run {runId ?? UNAVAILABLE}
        </p>
      </PanelBody>
    </Panel>
  )
}
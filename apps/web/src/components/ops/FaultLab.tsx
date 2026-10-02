/**
 * Fault laboratory.
 *
 * The form exists to make a class of mistake impossible: a coordination-channel
 * fault with no sender or receiver. The brief requires *directed* fault
 * injection, not a global switch, so an untargeted channel fault is rejected in
 * the browser with an actionable message before it can be submitted.
 *
 * The form also separates the two things that are routinely confused:
 *   - `coordination` — the agent↔agent message channel. Faults here change what
 *     peers can know, and therefore what the protocol decides.
 *   - `telemetry`    — the dashboard feed. Faults here blind the *observer*
 *     without changing any robot's behaviour.
 *
 * Every fault carries its expected invariant, because a fault whose consequence
 * nobody predicted is a bug, not evidence.
 */
import { useMemo, useState } from "react"
import { FlaskConical, Zap, ZapOff } from "lucide-react"
import type { FaultRecord, FaultSpec } from "@niharamesh/contracts/generated"
import { useClearFault, useInjectFault } from "../../lib/api/queries"
import { simClock, titleCase } from "../../lib/format"
import { Button } from "../primitives/Button"
import { Chip } from "../primitives/Chip"
import { Field, ControlField } from "../primitives/Field"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"

/**
 * The fault-kind union is *derived* from the generated contract rather than
 * re-declared, so this form can never accept a kind the domain does not know.
 */
type FaultKind = NonNullable<FaultSpec["target"]["kind"]>

const CHANNEL_FAULTS: FaultKind[] = ["delay", "loss", "duplicate", "reorder", "partition"]
const PROCESS_FAULTS: FaultKind[] = ["process_crash", "process_restart", "control_overload", "clock_skew"]
const WORLD_FAULTS: FaultKind[] = ["obstacle_insert", "obstacle_remove"]
const DASHBOARD_FAULTS: FaultKind[] = ["sensor_stale", "sensor_dropout"]

const FAULT_GROUPS: { channel: "coordination" | "telemetry"; kinds: FaultKind[]; label: string }[] = [
  { channel: "coordination", kinds: CHANNEL_FAULTS, label: "peer message channel" },
  { channel: "coordination", kinds: PROCESS_FAULTS, label: "agent process" },
  { channel: "coordination", kinds: WORLD_FAULTS, label: "warehouse world" },
  { channel: "telemetry", kinds: DASHBOARD_FAULTS, label: "dashboard telemetry only" },
]

const FAULT_STATE_TONE: Record<string, Tone> = {
  scheduled: "info",
  active: "amber",
  elapsed: "muted",
  cancelled: "muted",
  failed: "red",
}

export interface FaultFormState {
  kind: FaultKind
  channel: "coordination" | "telemetry"
  sender: string
  receiver: string
  robot: string
  zoneId: string
  startAtS: string
  durationS: string
  seed: string
  expectedInvariant: string
}

export function initialFaultForm(robotIds: string[]): FaultFormState {
  return {
    kind: "delay",
    channel: "coordination",
    sender: robotIds[0] ?? "",
    receiver: robotIds[1] ?? "",
    robot: robotIds[0] ?? "",
    zoneId: "",
    startAtS: "5",
    durationS: "3",
    seed: "1234",
    expectedInvariant: "",
  }
}

export interface FaultFormProblem {
  field: string
  message: string
}

/**
 * Pure validation, exported so it can be tested directly: an untargeted
 * coordination-channel fault must be rejected with an actionable message.
 */
export function validateFaultForm(form: FaultFormState, robotIds: string[]): FaultFormProblem[] {
  const problems: FaultFormProblem[] = []
  const needsDirectedPair = CHANNEL_FAULTS.includes(form.kind)
  const needsAgent = !WORLD_FAULTS.includes(form.kind)

  if (needsDirectedPair) {
    if (form.sender.trim() === "" || form.receiver.trim() === "") {
      problems.push({
        field: "target",
        message:
          "A coordination-channel fault must name both a sender and a receiver. The brief requires directed fault injection; an untargeted global switch is refused. Pick the source robot, then pick the sender robot and the peer whose channel you want to disturb.",
      })
    } else if (form.sender.trim() === form.receiver.trim()) {
      problems.push({
        field: "target",
        message: "Sender and receiver must be different robots. A fault on a robot's own local voter is a different experiment.",
      })
    }
  }

  if (needsAgent && form.robot.trim() === "") {
    problems.push({
      field: "robot",
      message: `Name the agent this fault targets. Known agents in this run: ${robotIds.length === 0 ? "none published yet" : robotIds.join(", ")}.`,
    })
  }

  const start = Number(form.startAtS)
  if (!Number.isFinite(start) || start < 0) {
    problems.push({ field: "startAtS", message: "Start time must be a non-negative number of simulation seconds." })
  }

  const duration = Number(form.durationS)
  const faultsWithoutDuration = form.kind === "process_restart" || form.kind === "clock_skew"
  if (!faultsWithoutDuration && (!Number.isFinite(duration) || duration <= 0)) {
    problems.push({ field: "durationS", message: "Duration must be greater than zero simulation seconds." })
  }

  if (form.expectedInvariant.trim() === "") {
    problems.push({
      field: "expectedInvariant",
      message:
        "State the invariant you expect this fault to test. A fault with no predicted consequence is a bug report, not an experiment.",
    })
  }

  return problems
}

export function buildFaultPayload(form: FaultFormState, robotIds: string[]) {
  const needsDirectedPair = CHANNEL_FAULTS.includes(form.kind)
  return {
    fault_id: `manual-${form.kind}-${Date.now().toString(36)}`,
    target: {
      channel: form.channel,
      kind: form.kind,
      ...(needsDirectedPair ? { sender: form.sender, receiver: form.receiver } : {}),
      ...(form.kind === "obstacle_insert" && form.zoneId !== "" ? { zone_id: form.zoneId } : {}),
      ...(!needsDirectedPair && form.robot !== "" ? { robot: form.robot } : {}),
    },
    start_at_s: Number(form.startAtS),
    duration_s: Number(form.durationS),
    seed: Number.isFinite(Number(form.seed)) ? Number(form.seed) : 0,
    expected_invariant: form.expectedInvariant,
    robot_ids_hint: robotIds,
  }
}

export function FaultLab({
  runId,
  robotIds,
  records,
}: {
  runId: string | null
  robotIds: string[]
  records: FaultRecord[]
}) {
  const [form, setForm] = useState<FaultFormState>(() => initialFaultForm(robotIds))
  const [submitted, setSubmitted] = useState(false)
  const inject = useInjectFault(runId)
  const clear = useClearFault(runId)

  const problems = useMemo(() => validateFaultForm(form, robotIds), [form, robotIds])
  const problemFor = (field: string) => problems.find((p) => p.field === field)
  const blocking = problems.find((p) => p.field === "target")

  const update = <K extends keyof FaultFormState>(key: K, value: FaultFormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const submit = () => {
    setSubmitted(true)
    if (problems.length > 0 || runId === null) return
    inject.mutate(buildFaultPayload(form, robotIds), {
      onSuccess: () => setSubmitted(false),
    })
  }

  const groupKinds = FAULT_GROUPS.filter((g) => g.channel === form.channel)

  return (
    <Panel className="min-h-0 shrink-0" ticks aria-label="Fault laboratory">
      <PanelHeader
        title="fault laboratory"
        subtitle="directed injection into a live run"
        tone="red"
        right={<FlaskConical className="h-[11px] w-[11px] text-red" aria-hidden />}
      />
      <PanelBody scroll={false}>
        <div className="px-3 py-2">
          <div className="flex gap-1">
            {(["coordination", "telemetry"] as const).map((channel) => (
              <button
                key={channel}
                type="button"
                onClick={() => update("channel", channel)}
                aria-pressed={form.channel === channel}
                className={`flex flex-1 items-center gap-1 border px-2 py-1 text-[11px] ${
                  form.channel === channel
                    ? channel === "coordination"
                      ? "border-red bg-red-wash text-red"
                      : "border-amber bg-amber-wash text-amber"
                    : "border-rule bg-raised text-ink-3"
                }`}
              >
                {channel === "coordination" ? <ZapOff className="h-[11px] w-[11px]" aria-hidden /> : <Zap className="h-[11px] w-[11px]" aria-hidden />}
                {channel === "coordination" ? "coordination" : "dashboard telemetry"}
              </button>
            ))}
          </div>
          <p className="mt-1 text-[10px] text-ink-3">
            {form.channel === "coordination"
              ? "Coordination faults change what agents know and therefore what the protocol decides."
              : "Telemetry faults blind this observer only. No robot changes behaviour, and the run's metrics stay valid."}
          </p>

          <div className="mt-2 grid grid-cols-2 gap-2">
            <ControlField label="fault kind">
              <select
                value={form.kind}
                onChange={(event) => update("kind", event.target.value as FaultKind)}
                className="w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
                data-testid="fault-kind"
              >
                {groupKinds.map((group) => (
                  <optgroup key={group.label} label={group.label}>
                    {group.kinds.map((kind) => (
                      <option key={kind} value={kind}>
                        {titleCase(kind)}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </ControlField>
            <ControlField label="target agent">
              <select
                value={form.robot}
                onChange={(event) => update("robot", event.target.value)}
                className="w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
                data-testid="fault-robot"
              >
                <option value="">choose an agent…</option>
                {robotIds.map((id) => (
                  <option key={id} value={id}>
                    {id}
                  </option>
                ))}
              </select>
            </ControlField>

            {CHANNEL_FAULTS.includes(form.kind) ? (
              <>
                <ControlField label="sender (channel source)">
                  <select
                    value={form.sender}
                    onChange={(event) => update("sender", event.target.value)}
                    className="w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
                    data-testid="fault-sender"
                  >
                    <option value="">choose a sender…</option>
                    {robotIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </ControlField>
                <ControlField label="receiver (channel sink)">
                  <select
                    value={form.receiver}
                    onChange={(event) => update("receiver", event.target.value)}
                    className="w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
                    data-testid="fault-receiver"
                  >
                    <option value="">choose a receiver…</option>
                    {robotIds.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                </ControlField>
              </>
            ) : null}

            <ControlField label="start at (sim s)">
              <input
                type="number"
                min={0}
                step={0.5}
                value={form.startAtS}
                onChange={(event) => update("startAtS", event.target.value)}
                className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
              />
            </ControlField>
            <ControlField label="duration (sim s)">
              <input
                type="number"
                min={0.1}
                step={0.5}
                value={form.durationS}
                onChange={(event) => update("durationS", event.target.value)}
                className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
              />
            </ControlField>
            <ControlField label="seed">
              <input
                type="number"
                value={form.seed}
                onChange={(event) => update("seed", event.target.value)}
                className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
              />
            </ControlField>
            {form.kind === "obstacle_insert" ? (
              <ControlField label="zone (optional)">
                <input
                  value={form.zoneId}
                  onChange={(event) => update("zoneId", event.target.value)}
                  placeholder="e.g. Z-INTERSECTION-A"
                  className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
                />
              </ControlField>
            ) : null}
          </div>

          <Field label="expected invariant" className="mt-2">
            <textarea
              value={form.expectedInvariant}
              aria-label="expected invariant"
              onChange={(event) => update("expectedInvariant", event.target.value)}
              rows={2}
              placeholder="e.g. AMR2 keeps physical occupancy of Z-2 while its heartbeat is lost, and refuses entry until release or recovery."
              className="w-full resize-y border border-rule bg-raised px-1.5 py-1 text-[11px] text-ink"
              data-testid="fault-invariant"
            />
          </Field>

          {blocking !== undefined && submitted ? (
            <HatchStrip tone="red" className="mt-2">
              <span data-testid="fault-error">
                <strong className="font-semibold">This fault is not targeted.</strong>{" "}
                {blocking?.message ?? "A coordination-channel fault must name a sender and a receiver."}
              </span>
            </HatchStrip>
          ) : null}

          {problemFor("expectedInvariant") !== undefined && submitted ? (
            <HatchStrip tone="amber" className="mt-2">
              {problemFor("expectedInvariant")?.message}
            </HatchStrip>
          ) : null}

          {inject.isError ? (
            <HatchStrip tone="red" className="mt-2">
              <strong className="font-semibold">Injection refused.</strong>{" "}
              {inject.error instanceof Error ? inject.error.message : "The API rejected the fault."}
            </HatchStrip>
          ) : null}

          <div className="mt-2 flex items-center gap-1.5">
            <Button variant="danger" onClick={submit} disabled={runId === null || inject.isPending} data-testid="fault-submit">
              Inject fault
            </Button>
            {runId === null ? (
              <span className="text-[10px] text-ink-3">Launch a run first — a fault needs a live run to enter.</span>
            ) : null}
          </div>

          <Strip tone="info" className="mt-2 border">
            <span className="text-[10px]">
              Removing a network fault restores communication, not movement permission. Agents that entered degraded
              operation must still complete recovery through the protocol.
            </span>
          </Strip>
        </div>

        {/* -------- active faults -------- */}
        <div className="border-t border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">faults in this run ({records.length})</h3>
          {records.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">No fault has been injected into this run.</p>
          ) : (
            <ul className="px-2 pb-2">
              {records.toReversed().slice(0, 8).map((record) => (
                <li key={record.fault_id} className="flex items-start justify-between gap-2 border-b border-rule/60 px-1 py-1.5 last:border-b-0">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="num break-all text-[11px] text-ink">{record.fault_id}</span>
                      <Chip tone={FAULT_STATE_TONE[record.state] ?? "muted"}>{record.state}</Chip>
                      {record.manual === true ? <Chip tone="info">manual</Chip> : <Chip tone="muted">scheduled</Chip>}
                    </div>
                    <p className="num mt-0.5 text-[10px] text-ink-3">
                      started {simClock(record.started_at_ns / 1e9)}
                      {record.ended_at_ns != null ? ` · ended ${simClock(record.ended_at_ns / 1e9)}` : " · still open"}
                      {record.injected_by != null ? ` · by ${record.injected_by}` : ""}
                    </p>
                    {record.note != null && record.note.length > 0 ? (
                      <p className="mt-0.5 text-[10px] text-ink-2">{record.note}</p>
                    ) : null}
                  </div>
                  {record.state === "active" || record.state === "scheduled" ? (
                    <Button
                      onClick={() => clear.mutate(record.fault_id)}
                      disabled={clear.isPending}
                      aria-label={`Clear fault ${record.fault_id}`}
                    >
                      Clear
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          <p className="num px-3 pb-2 text-[10px] text-ink-3">
            expected invariants are recorded with the run manifest and quoted in the report bundle.
          </p>
        </div>
      </PanelBody>
    </Panel>
  )
}

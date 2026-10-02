/**
 * System / doctor.
 *
 * Shows only what was actually collected. A latency or a CPU figure appears
 * only when the API measured it; otherwise the row says `unavailable` and names
 * what would produce it. This is the one page where over-reporting would be
 * most tempting and most dishonest.
 *
 * It also carries the guided path, because the brief asks for an operator who
 * can go from "I just started" to "I understand why a robot waited".
 */
import { useState } from "react"
import { Cpu, FileText, ListChecks, Radio, ScrollText, ServerCog } from "lucide-react"
import { useDoctor, useHealth } from "../lib/api/queries"
import { UNAVAILABLE, age, simClock, utc } from "../lib/format"
import { useViewStore, type Destination } from "../lib/view/store"
import { Button } from "../components/primitives/Button"
import { Chip } from "../components/primitives/Chip"
import { Field } from "../components/primitives/Field"
import { Panel, PanelBody, PanelHeader, Strip } from "../components/primitives/Panel"
import { ErrorState, LoadingState, UnavailableFeature } from "../components/primitives/States"
import type { CheckStatus } from "../lib/api/types"

const CHECK_TONE: Record<CheckStatus, "teal" | "amber" | "red" | "muted"> = {
  pass: "teal",
  warn: "amber",
  fail: "red",
  unknown: "muted",
}

export function SystemPage() {
  const health = useHealth()
  const doctor = useDoctor()
  const navigate = useViewStore((s) => s.navigate)
  const [step, setStep] = useState(0)

  const guide: { title: string; body: string; action: { label: string; go: Destination; runId?: string } }[] = [
    {
      title: "Launch one three-robot run",
      body: "Open Scenarios, pick a revision, and validate and launch it. A run freezes its scenario into an immutable snapshot with its own digest.",
      action: { label: "Open Scenarios", go: "scenarios" },
    },
    {
      title: "Watch the map and select a robot",
      body: "Operations shows the warehouse at true scale. Click a chassis: the inspector reads pose, uncertainty and its age, motion state, task, custody and the agent's own reasons.",
      action: { label: "Open Operations", go: "operations" },
    },
    {
      title: "Inject one fault",
      body: "The fault laboratory requires a directed target. Partition AMR2's channel to AMR3 and watch AMR2 enter degraded operation rather than assuming the aisle is free.",
      action: { label: "Open Operations", go: "operations" },
    },
    {
      title: "Read why a robot is waiting",
      body: "The why-waiting card names the blocking request, the blocking peer or resource, the age of the evidence, and the condition that would clear it.",
      action: { label: "Open Operations", go: "operations" },
    },
    {
      title: "Replay it, and step backwards",
      body: "Replays rebuild the world from the durable log. Seeking backwards removes future completions, grants and alerts rather than leaving them on screen.",
      action: { label: "Open Replays", go: "replays" },
    },
  ]

  return (
    <div className="scroll-y h-full">
      <div className="grid gap-2 p-2 min-[1180px]:grid-cols-[minmax(0,1fr)_400px]">
        {/* ---------------- doctor ---------------- */}
        <div className="flex flex-col gap-2">
          <Panel ticks>
            <PanelHeader
              title="runtime doctor"
              subtitle="measured values only; anything not collected reads as unavailable"
              tone={doctor.data === undefined ? "muted" : doctor.isError ? "red" : "teal"}
              right={
                <Button onClick={() => void doctor.refetch()} disabled={doctor.isFetching}>
                  {doctor.isFetching ? "checking…" : "re-check"}
                </Button>
              }
            />
            <PanelBody>
              {doctor.isError ? (
                <ErrorState error={doctor.error} what="The doctor report" onRetry={() => void doctor.refetch()} />
              ) : doctor.isPending ? (
                <LoadingState what="the doctor report" rows={6} />
              ) : (
                <div className="space-y-0">
                  <section className="border-b border-rule">
                    <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
                      <ServerCog className="h-[10px] w-[10px]" aria-hidden />
                      build identity
                    </h3>
                    <dl className="grid grid-cols-2 gap-2 px-3 py-2 min-[560px]:grid-cols-3">
                      <Field label="version" mono>
                        {doctor.data?.build.version}
                      </Field>
                      <Field label="schema version" mono>
                        {doctor.data?.build.schema_version}
                      </Field>
                      <Field label="protocol version" mono>
                        {doctor.data?.build.protocol_version}
                      </Field>
                      <Field label="source revision" mono>
                        {doctor.data?.build.source_revision ?? UNAVAILABLE}
                      </Field>
                      <Field label="config digest" mono>
                        {doctor.data?.build.config_digest ?? UNAVAILABLE}
                      </Field>
                      <Field label="report generated" mono>
                        {utc(doctor.data?.generated_at_utc ?? null)}
                      </Field>
                    </dl>
                    <Strip tone={CHECK_TONE[doctor.data?.schema_compatibility.status ?? "unknown"]} className="mx-3 mb-2 border">
                      <span className="text-[11px]">
                        <strong className="font-semibold">Schema compatibility:</strong>{" "}
                        {doctor.data?.schema_compatibility.detail} (expected{" "}
                        {doctor.data?.schema_compatibility.expected}, actual{" "}
                        {doctor.data?.schema_compatibility.actual ?? UNAVAILABLE})
                      </span>
                    </Strip>
                  </section>

                  <section className="border-b border-rule">
                    <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
                      <Radio className="h-[10px] w-[10px]" aria-hidden />
                      api health
                    </h3>
                    <dl className="grid grid-cols-2 gap-2 px-3 py-2 min-[560px]:grid-cols-4">
                      <Field label="status">
                        <Chip tone={health.data?.status === "ok" ? "teal" : "amber"}>{health.data?.status ?? UNAVAILABLE}</Chip>
                      </Field>
                      <Field label="mode" mono>
                        {health.data?.mode ?? UNAVAILABLE}
                      </Field>
                      <Field label="active run" mono>
                        {health.data?.run_id ?? "none"}
                      </Field>
                      <Field label="uptime" mono>
                        {health.data === undefined ? UNAVAILABLE : age(health.data.uptime_s)}
                      </Field>
                    </dl>
                  </section>

                  <section className="border-b border-rule">
                    <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
                      <Cpu className="h-[10px] w-[10px]" aria-hidden />
                      processes
                    </h3>
                    <table className="w-full text-[11px]">
                      <caption className="sr-only">Runtime processes with role, status, pid and host</caption>
                      <thead>
                        <tr className="border-b border-rule">
                          {["name", "role", "status", "pid", "host"].map((h) => (
                            <th key={h} scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(doctor.data?.processes.length ?? 0) === 0 ? (
                          <tr>
                            <td colSpan={5} className="px-2 py-2 text-ink-3">
                              The doctor report listed no processes. That is a gap in the report, not evidence that
                              nothing is running.
                            </td>
                          </tr>
                        ) : (
                          doctor.data?.processes.map((process) => (
                            <tr key={process.name} className="border-b border-rule/50">
                              <td className="num px-2 py-1 text-ink">{process.name}</td>
                              <td className="px-2 py-1 text-ink-3">{process.role}</td>
                              <td className="px-2 py-1">
                                <Chip tone={process.status === "running" ? "teal" : process.status === "stopped" ? "red" : "muted"}>
                                  {process.status}
                                </Chip>
                              </td>
                              <td className="num px-2 py-1 text-ink-2">{process.pid ?? UNAVAILABLE}</td>
                              <td className="num px-2 py-1 text-ink-3">{process.host ?? UNAVAILABLE}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </section>

                  <section className="border-b border-rule">
                    <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">endpoints (latency only when measured)</h3>
                    <table className="w-full text-[11px]">
                      <caption className="sr-only">API endpoints with reachability and measured latency</caption>
                      <thead>
                        <tr className="border-b border-rule">
                          {["name", "url", "status", "latency"].map((h) => (
                            <th key={h} scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(doctor.data?.endpoints.length ?? 0) === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-2 py-2 text-ink-3">
                              No endpoint probes were published, so no latency figure can be shown.
                            </td>
                          </tr>
                        ) : (
                          doctor.data?.endpoints.map((endpoint) => (
                            <tr key={endpoint.name} className="border-b border-rule/50">
                              <td className="px-2 py-1 text-ink">{endpoint.name}</td>
                              <td className="num break-all px-2 py-1 text-ink-3">{endpoint.url}</td>
                              <td className="px-2 py-1">
                                <Chip tone={CHECK_TONE[endpoint.status]}>{endpoint.status}</Chip>
                              </td>
                              <td className="num px-2 py-1 text-ink-2">
                                {endpoint.latency_ms === null ? UNAVAILABLE : `${endpoint.latency_ms} ms`}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </section>

                  <section className="border-b border-rule">
                    <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
                      <ScrollText className="h-[10px] w-[10px]" aria-hidden />
                      journals
                    </h3>
                    <table className="w-full text-[11px]">
                      <caption className="sr-only">Append-only journals with path and health</caption>
                      <thead>
                        <tr className="border-b border-rule">
                          {["journal", "path", "status", "detail"].map((h) => (
                            <th key={h} scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                              {h}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {(doctor.data?.journals.length ?? 0) === 0 ? (
                          <tr>
                            <td colSpan={4} className="px-2 py-2 text-ink-3">
                              No journals were listed.
                            </td>
                          </tr>
                        ) : (
                          doctor.data?.journals.map((journal) => (
                            <tr key={journal.name} className="border-b border-rule/50">
                              <td className="px-2 py-1 text-ink">{journal.name}</td>
                              <td className="num break-all px-2 py-1 text-ink-3">{journal.path ?? UNAVAILABLE}</td>
                              <td className="px-2 py-1">
                                <Chip tone={CHECK_TONE[journal.status]}>{journal.status}</Chip>
                              </td>
                              <td className="px-2 py-1 text-ink-3">{journal.detail}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </section>

                  <section>
                    <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
                      <ListChecks className="h-[10px] w-[10px]" aria-hidden />
                      checks
                    </h3>
                    <ul className="px-3 pb-2">
                      {(doctor.data?.checks.length ?? 0) === 0 ? (
                        <li className="py-1 text-[11px] text-ink-3">The doctor report published no individual checks.</li>
                      ) : (
                        doctor.data?.checks.map((check) => (
                          <li key={check.id} className="border-b border-rule/50 py-1.5 last:border-b-0">
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-[12px] text-ink">{check.label}</span>
                              <Chip tone={CHECK_TONE[check.status]}>{check.status}</Chip>
                            </div>
                            <p className="text-[11px] text-ink-3">{check.detail}</p>
                            {check.measured != null ? (
                              <dl className="num mt-0.5 flex flex-wrap gap-3 text-[10px] text-ink-3">
                                {Object.entries(check.measured).map(([k, v]) => (
                                  <div key={k} className="flex gap-1">
                                    <dt>{k}</dt>
                                    <dd className="text-ink-2">{v === null ? UNAVAILABLE : String(v)}</dd>
                                  </div>
                                ))}
                              </dl>
                            ) : (
                              <p className="num mt-0.5 text-[10px] text-ink-4">no measured values were collected for this check</p>
                            )}
                          </li>
                        ))
                      )}
                    </ul>
                  </section>

                  <section className="border-t border-rule p-3">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="stencil text-[9px] text-ink-3">recording health</h3>
                      <Chip tone={doctor.data?.recording.healthy ? "teal" : "amber"}>
                        {doctor.data?.recording.healthy ? "healthy" : "degraded"}
                      </Chip>
                    </div>
                    <p className="mt-1 text-[11px] text-ink-2">{doctor.data?.recording.detail}</p>
                    {(doctor.data?.recording.gaps.length ?? 0) > 0 ? (
                      <ul className="num mt-1 space-y-0.5 text-[10px] text-amber">
                        {doctor.data?.recording.gaps.map((gap) => (
                          <li key={`${gap.from_seq}-${gap.to_seq}`}>
                            seq {gap.from_seq}–{gap.to_seq} · {gap.category} · {simClock(gap.sim_time_from_s)} →{" "}
                            {simClock(gap.sim_time_to_s)} · {gap.cause}
                            {gap.recovered === true ? " · recovered" : " · unrecovered"}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </section>
                </div>
              )}
            </PanelBody>
          </Panel>

          <div className="grid gap-2 min-[720px]:grid-cols-2">
            <UnavailableFeature
              title="Hardware-in-the-loop actuation"
              prerequisite="Configured device endpoints, a controlled test area, operator authorisation, and NIHARA_PHYSICAL_ACTUATION_ENABLED=true"
              detail="No physical robot is actuated in this deployment. Physical actuation ships disabled by default and refuses to start while an unsafe research ablation flag is set. The button that would arm it is absent rather than present-and-dead."
            />
            <UnavailableFeature
              title="ROS 2 bridge"
              prerequisite="ros2_bridge package, a sourced ROS 2 installation, and a matching edge profile"
              detail="The bridge boundary and message definitions are authored and unit-tested, but no ROS 2 runtime is present here, so no ROS topic is being subscribed. Nothing on this page is reading ROS data."
            />
          </div>
        </div>

        {/* ---------------- guided path ---------------- */}
        <aside className="flex flex-col gap-2">
          <Panel ticks className="shrink-0">
            <PanelHeader
              title="guided path"
              subtitle="first launch → one run → a fault → an inspector → a replay"
              tone="teal"
              right={<FileText className="h-[11px] w-[11px] text-ink-3" aria-hidden />}
            />
            <PanelBody scroll={false}>
              <ol className="px-3 py-2">
                {guide.map((item, index) => (
                  <li key={item.title} className="border-b border-rule/60 py-2 last:border-b-0">
                    <div className="flex items-start gap-2">
                      <span
                        aria-hidden="true"
                        className={`stencil mt-[1px] text-[10px] ${index === step ? "text-teal" : "text-ink-4"}`}
                      >
                        {String(index + 1).padStart(2, "0")}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className={`text-[12px] font-medium ${index === step ? "text-ink" : "text-ink-2"}`}>
                          {item.title}
                        </p>
                        {index === step ? (
                          <>
                            <p className="mt-0.5 text-[11px] leading-relaxed text-ink-2">{item.body}</p>
                            <div className="mt-1.5 flex gap-1.5">
                              <Button
                                variant="primary"
                                onClick={() => navigate(item.action.go, item.action.runId ?? null)}
                                data-testid={`guide-step-${index + 1}`}
                              >
                                {item.action.label}
                              </Button>
                              <Button onClick={() => setStep(index + 1)} disabled={index === guide.length - 1}>
                                next step
                              </Button>
                            </div>
                          </>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setStep(index)}
                            className="mt-0.5 text-[11px] text-ink-3 underline underline-offset-2 hover:text-ink"
                          >
                            show this step
                          </button>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
              {step >= guide.length ? (
                <Strip tone="teal" className="m-2 border">
                  <span>That is the whole loop. Everything you saw is backed by a run artefact under `var/runs/`.</span>
                </Strip>
              ) : null}
            </PanelBody>
          </Panel>

          <Panel ticks className="min-h-0 flex-1">
            <PanelHeader title="what this console does not do" tone="amber" />
            <PanelBody>
              <ul className="space-y-2 px-3 py-2 text-[11px] leading-relaxed text-ink-2">
                <li>
                  It does not advance robot truth. Every value here is a read model of what robots already did.
                </li>
                <li>
                  It does not plan, award or grant. Awarding is computed by the agents from the received bid set; the
                  API is not in that loop.
                </li>
                <li>
                  It does not invent a measurement. A missing number reads <code className="num">unavailable</code>, and a
                  zero collision count is reported as an observation, not as a proof.
                </li>
                <li>
                  It is not an emergency stop. Stopping this browser does not stop the world or the robots.
                </li>
                <li>
                  It is not a certified safety system. No industrial safety certification is claimed anywhere in this
                  product.
                </li>
              </ul>
            </PanelBody>
          </Panel>
        </aside>
      </div>
    </div>
  )
}
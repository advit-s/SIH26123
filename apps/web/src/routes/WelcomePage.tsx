/**
 * Quick start.
 *
 * A local welcome view, not a login wall: there is no account, no session and
 * no gate. It exists to answer, in under a minute, "what am I looking at and
 * what should I click first", and to be honest about whether the API is up.
 *
 * The lead element is the five-destination map of the product as a *floor plan
 * strip*, not a marketing hero: five bays, each with what it answers.
 */
import { useState } from "react"
import { ArrowRight, Boxes, FlaskConical, History, Radio, ServerCog } from "lucide-react"
import type { ComponentType } from "react"
import { useHealth, useRuns, useScenarioLibrary } from "../lib/api/queries"
import { UNAVAILABLE } from "../lib/format"
import { useViewStore, type Destination } from "../lib/view/store"
import { Button } from "../components/primitives/Button"
import { Chip } from "../components/primitives/Chip"
import { Panel, PanelBody, PanelHeader, Strip } from "../components/primitives/Panel"

const DESTINATIONS: {
  id: Destination
  label: string
  question: string
  Icon: ComponentType<{ className?: string }>
}[] = [
  { id: "operations", label: "Operations", question: "What is the fleet doing, and why?", Icon: Radio },
  { id: "scenarios", label: "Scenarios", question: "What exactly am I about to run?", Icon: Boxes },
  { id: "experiments", label: "Experiments", question: "Did the protocol actually help?", Icon: FlaskConical },
  { id: "replays", label: "Replays", question: "What happened, second by second?", Icon: History },
  { id: "system", label: "System", question: "Is the evidence trustworthy right now?", Icon: ServerCog },
]

export function WelcomePage({ apiReachable }: { apiReachable: boolean }) {
  const health = useHealth()
  const runs = useRuns()
  const library = useScenarioLibrary()
  const navigate = useViewStore((s) => s.navigate)
  const [confirmRun, setConfirmRun] = useState<string | null>(null)

  const running = (runs.data ?? []).filter((r) => r.state === "running" || r.state === "paused" || r.state === "queued")

  return (
    <div className="scroll-y h-full">
      <div className="mx-auto max-w-[1180px] space-y-2 p-3">
        <Panel ticks>
          <PanelHeader
            title="NĪHĀRAMESH"
            subtitle="distributed fleet coordination for warehouse AMRs — SIH26123 · NihāraNetra"
            tone="teal"
            right={
              apiReachable ? (
                <Chip tone={health.data?.status === "ok" ? "teal" : "amber"}>
                  API {health.data?.status ?? "reachable"}
                </Chip>
              ) : (
                <Chip tone="red">API not reachable</Chip>
              )
            }
          />
          <PanelBody scroll={false}>
            <div className="grid gap-4 px-3 py-3 min-[860px]:grid-cols-[minmax(0,1fr)_300px]">
              <div>
                <h1 className="text-[19px] font-semibold leading-tight text-ink">
                  A warehouse floor that explains itself.
                </h1>
                <p className="mt-2 max-w-[68ch] text-[13px] leading-relaxed text-ink-2">
                  Three or more robots run as independent processes. They plan their own routes, bid for their own
                  tasks, and negotiate exclusive aisles with each other over direct peer messages. This console shows
                  that negotiation as it happens — and, when a robot stops, it shows what it was waiting for.
                </p>
                <p className="mt-2 max-w-[68ch] text-[12px] leading-relaxed text-ink-3">
                  The interesting engineering here is freshness. Knowing whether a peer&rsquo;s information is still
                  usable, keeping conservative physical occupancy through a failure, and never letting a late message
                  revive a decision that was already cancelled. Those rules are visible in every panel: colour, hatching,
                  an age, and a sentence saying what the evidence does and does not prove.
                </p>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Button
                    variant="primary"
                    onClick={() => navigate("scenarios")}
                    data-testid="welcome-start"
                  >
                    Launch a scenario
                    <ArrowRight className="h-[12px] w-[12px]" aria-hidden />
                  </Button>
                  <Button onClick={() => navigate("operations")}>Open Operations</Button>
                  <Button onClick={() => navigate("system")}>Run the doctor</Button>
                </div>

                {!apiReachable ? (
                  <p className="mt-3 border border-red bg-red-wash px-2.5 py-2 text-[12px] text-red" data-testid="api-down">
                    The NĪHĀRAMESH API is not answering at{" "}
                    <code className="num">{health.isError ? "the configured base URL" : "127.0.0.1:8100"}</code>. Start it
                    with <code className="num">pnpm dev</code> (API + cockpit) or{" "}
                    <code className="num">pnpm doctor</code> to diagnose. Until then every panel reports the failure
                    honestly instead of showing invented numbers.
                  </p>
                ) : null}
              </div>

              <div className="border border-rule bg-raised p-2">
                <p className="stencil text-[9px] text-ink-3">current lab state</p>
                <dl className="mt-1.5 space-y-1 text-[11px]">
                  <Row label="API mode" value={health.data?.mode ?? UNAVAILABLE} />
                  <Row label="active run" value={health.data?.run_id ?? "none"} />
                  <Row
                    label="recording"
                    value={
                      health.data === undefined
                        ? UNAVAILABLE
                        : health.data.recording_healthy
                          ? "healthy"
                          : "degraded"
                    }
                  />
                  <Row label="runs on disk" value={runs.data === undefined ? UNAVAILABLE : String(runs.data.length)} />
                  <Row
                    label="runs in flight"
                    value={runs.data === undefined ? UNAVAILABLE : String(running.length)}
                  />
                  <Row
                    label="scenarios"
                    value={library.data === undefined ? UNAVAILABLE : String(library.data.length)}
                  />
                  <Row label="uptime" value={health.data === undefined ? UNAVAILABLE : `${Math.round(health.data.uptime_s)} s`} />
                </dl>
              </div>
            </div>
          </PanelBody>
        </Panel>

        {/* Destination strip, drawn as five bays. */}
        <Panel ticks>
          <PanelHeader title="where things are" subtitle="five destinations, in the order you use them" tone="info" />
          <PanelBody scroll={false}>
            <ul className="grid gap-px bg-rule min-[760px]:grid-cols-5">
              {DESTINATIONS.map((destination, index) => {
                const Icon = destination.Icon
                return (
                  <li key={destination.id} className="bg-panel">
                    <button
                      type="button"
                      onClick={() => navigate(destination.id)}
                      data-testid={`welcome-go-${destination.id}`}
                      className="flex h-full w-full flex-col items-start gap-1.5 p-3 text-left hover:bg-raised"
                    >
                      <span className="flex items-center gap-2">
                        <Icon className="h-[14px] w-[14px] text-ink-3" aria-hidden />
                        <span className="text-[12px] font-semibold text-ink">{destination.label}</span>
                        <span aria-hidden="true" className="stencil text-[9px] text-ink-4">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                      </span>
                      <span className="text-[11px] leading-snug text-ink-2">{destination.question}</span>
                    </button>
                  </li>
                )
              })}
            </ul>
          </PanelBody>
        </Panel>

        {running.length > 0 ? (
          <Panel ticks>
            <PanelHeader title="runs currently attached to this lab" tone="teal" />
            <PanelBody scroll={false}>
              <ul className="divide-y divide-rule">
                {running.map((run) => (
                  <li key={run.run_id} className="flex flex-wrap items-center gap-2 px-3 py-2">
                    <span className="num min-w-0 flex-1 break-all text-[12px] text-ink">{run.run_id}</span>
                    <Chip tone={run.state === "running" ? "teal" : "amber"}>{run.state}</Chip>
                    <span className="num text-[10px] text-ink-3">
                      seed {run.seed} · r{run.scenario_revision} · {run.coordination_policy}
                    </span>
                    <Button
                      onClick={() => {
                        setConfirmRun(run.run_id)
                        navigate("operations", run.run_id)
                      }}
                    >
                      watch
                    </Button>
                  </li>
                ))}
              </ul>
              {confirmRun !== null ? (
                <Strip tone="teal" className="m-2 border">
                  <span className="num text-[11px]">
                    Attaching to {confirmRun}. Operations is read-only with respect to robot truth — watching never
                    changes what the robots do.
                  </span>
                </Strip>
              ) : null}
            </PanelBody>
          </Panel>
        ) : null}

        <div className="grid gap-2 min-[980px]:grid-cols-2">
          <Panel ticks>
            <PanelHeader title="the three evidence categories" tone="info" />
            <PanelBody scroll={false}>
              <dl className="space-y-2 px-3 py-2 text-[11px] leading-relaxed">
                <div>
                  <dt className="stencil text-[9px] text-ink-3">configured assumption</dt>
                  <dd className="text-ink-2">
                    Robot dimensions, speed limits, sensor noise, battery model, protocol deadlines. Values we chose,
                    labelled as simulation configuration wherever they appear.
                  </dd>
                </div>
                <div>
                  <dt className="stencil text-[9px] text-ink-3">implemented and verified</dt>
                  <dd className="text-ink-2">Code exists, checks ran, and the evidence path is recorded.</dd>
                </div>
                <div>
                  <dt className="stencil text-[9px] text-ink-3">measured outcome</dt>
                  <dd className="text-ink-2">
                    A number from one run artefact, with its manifest, environment and trace. A zero observed collision
                    count is not a collision-free proof, and the ≥20 % makespan figure is a target reported only as a
                    paired measurement with eligibility rules and sample counts.
                  </dd>
                </div>
              </dl>
            </PanelBody>
          </Panel>

          <Panel ticks>
            <PanelHeader title="how to read the map" tone="info" />
            <PanelBody scroll={false}>
              <ul className="space-y-1.5 px-3 py-2 text-[11px] leading-relaxed text-ink-2">
                <li>
                  <span className="text-teal">Teal</span> means normal coordination: granted, moving, fresh.
                </li>
                <li>
                  <span className="text-amber">Amber with hatching</span> means attention: stale evidence, withheld
                  entry, degraded operation. The hatching is deliberate — it survives a monochrome print-out.
                </li>
                <li>
                  <span className="text-red">Red with hatching</span> is a confirmed fault: an invariant was broken,
                  not merely a warning.
                </li>
                <li>
                  <span className="text-steel">Steel blue hatching</span> is the evaluator&rsquo;s independent verdict.
                  It is never agent knowledge, and it is off by default.
                </li>
                <li>
                  Robot colour is derived from the robot id and never changes during a run. The stencilled number on each
                  chassis is a second, colour-free identifier.
                </li>
                <li>
                  When telemetry stops, robots <em>freeze</em> and show their evidence age. The map never animates
                  presumed motion.
                </li>
              </ul>
            </PanelBody>
          </Panel>
        </div>

        <p className="px-1 pb-3 text-[11px] leading-relaxed text-ink-3">
          Full documentation ships with the repository: the project brief, the architecture and authority boundaries,
          the zone protocol with its crash and recovery rules, the scenario authoring guide, the fault-injection guide,
          the replay semantics, and the benchmark methodology with its limitations.
        </p>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-ink-3">{label}</dt>
      <dd className="num break-all text-right text-ink-2">{value}</dd>
    </div>
  )
}
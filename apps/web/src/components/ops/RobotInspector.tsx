/**
 * Robot inspector.
 *
 * Answers, in order: where is it, how sure are we, what is it doing, why, and
 * what is it running as. Every number declares its source and every absence says
 * `unavailable`.
 *
 * The pose block is the important part. When the stream is stale the pose is
 * **frozen and labelled with its age**, and the block says so in words, because
 * silently showing a stale pose is how an operator ends up believing a robot is
 * somewhere it is not.
 */
import { AlertTriangle, BatteryCharging, Cpu, Info, PauseOctagon } from "lucide-react"
import type { RobotInspection } from "../../lib/api/types"
import { UNAVAILABLE, age, heading, metres, simClock, titleCase } from "../../lib/format"
import { describePoseFreshness } from "../../lib/map/freshness"
import { robotColor, robotGlyph, robotIndexLabel } from "../../lib/robotColor"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { BatteryReadout, Field, FieldGrid, Row } from "../primitives/Field"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"
import { TelemetryStrip } from "./TelemetryStrip"
import { WhyWaitingCard } from "./WhyWaitingCard"

function stopTone(stopReason: string | undefined): Tone {
  if (stopReason === undefined || stopReason === "none") return "teal"
  if (stopReason === "operator_request" || stopReason === "workload_complete") return "info"
  return "amber"
}

export function RobotInspector({
  robot,
  freshnessHorizonS,
  liveAgeS,
  streamLive,
}: {
  robot: RobotInspection
  freshnessHorizonS: number
  /** Age, in seconds, of the newest telemetry frame *this browser* received. */
  liveAgeS: number | null
  /** False whenever the stream is not demonstrably live. */
  streamLive: boolean
}) {
  const theme = useViewStore((s) => s.theme)
  const select = useViewStore((s) => s.select)
  const colour = robotColor(robot.robot_id, theme)

  const pose = robot.pose_estimate?.pose ?? null
  /**
   * Freshness is judged on *browser* evidence only. The agent's own declared
   * `pose_age_s` answers a different question ("how old is my own
   * observation?"); it does not make this browser's picture fresh. When the
   * stream is down, the browser's evidence is absent no matter what the agent
   * says, and the pose is frozen.
   */
  const agentAgeS = robot.pose_age_s
  const browserAgeS = streamLive ? liveAgeS : null
  const freshness = describePoseFreshness(browserAgeS, freshnessHorizonS)
  const poseTone: Tone = freshness.tone === "live" ? "teal" : freshness.tone === "aging" ? "amber" : "red"

  const sigma = robot.pose_estimate?.uncertainty.sigma_m
  const headingSigma = robot.pose_estimate?.uncertainty.sigma_rad
  const observedAt = robot.pose_estimate?.observed_at_ns

  return (
    <Panel ticks className="min-h-0" aria-label={`Inspector for robot ${robot.robot_id}`}>
      <PanelHeader
        title={
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" style={{ color: colour }}>
              {robotGlyph(robot.robot_id)}
            </span>
            <span className="num">{robot.robot_id}</span>
            <span className="text-ink-4">#{robotIndexLabel(robot.robot_id)}</span>
          </span>
        }
        subtitle={robot.degraded ? "degraded operation" : "nominal operation"}
        tone={robot.degraded ? "amber" : "teal"}
        right={
          <Chip tone={robot.degraded ? "amber" : "teal"}>{robot.degraded ? "degraded" : "nominal"}</Chip>
        }
      />
      <PanelBody>
        {/* ---------------- pose + freshness ---------------- */}
        <section aria-label="Pose and freshness" className="border-b border-rule">
          <div className="flex items-start justify-between gap-2 px-3 py-2">
            <div className="min-w-0">
              <p className="stencil text-[9px] text-ink-3">pose (agent observation)</p>
              {pose === null ? (
                <p className="mt-0.5 text-[13px] text-ink-3">{UNAVAILABLE}</p>
              ) : (
                <p className="num mt-0.5 text-[15px] leading-tight text-ink" data-testid="robot-pose">
                  {metres(pose.x)} E · {metres(pose.y)} N
                </p>
              )}
              <p className="num mt-0.5 text-[11px] text-ink-3">
                heading {heading(pose?.theta ?? null)}
                {robot.pose_estimate?.time_domain != null ? ` · clock ${robot.pose_estimate.time_domain}` : ""}
              </p>
            </div>
            <Chip tone={poseTone} title={freshness.label}>
              {freshness.short}
            </Chip>
          </div>

          {freshness.frozen ? (
            <HatchStrip tone={freshness.tone === "absent" ? "amber" : "amber"} className="mx-3 mb-2">
              <span data-testid="robot-frozen-pose">
                <strong className="font-semibold">Frozen.</strong> {freshness.label}
              </span>
            </HatchStrip>
          ) : null}

          <FieldGrid>
            <Field label="position σ" mono hint="Declared standard deviation of the agent's own pose estimate.">
              {sigma == null ? <span className="text-ink-3">{UNAVAILABLE}</span> : <>{metres(sigma, 3)}</>}
            </Field>
            <Field label="heading σ" mono>
              {headingSigma == null ? <span className="text-ink-3">{UNAVAILABLE}</span> : <>{headingSigma.toFixed(3)} rad</>}
            </Field>
            <Field
              label="browser age"
              mono
              hint="Age of the newest telemetry frame received by *this browser*. This is the age that decides whether the pose is frozen."
            >
              {browserAgeS === null ? <span className="text-ink-3">{UNAVAILABLE}</span> : <>{age(browserAgeS)}</>}
            </Field>
            <Field label="agent age" mono hint="Age of the agent's own pose observation, as the agent declares it.">
              {agentAgeS === null ? <span className="text-ink-3">{UNAVAILABLE}</span> : <>{age(agentAgeS)}</>}
            </Field>
            <Field label="observed at" mono>
              {observedAt == null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>
                  {simClock(observedAt / 1e9)}
                  <span className="block text-[10px] text-ink-3">{robot.pose_estimate?.time_domain}</span>
                </>
              )}
            </Field>
          </FieldGrid>
        </section>

        {/* ---------------- motion + power ---------------- */}
        <section aria-label="Motion and power" className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">motion &amp; power</h3>
          <FieldGrid>
            <Field label="observed v" mono>
              {robot.motion === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>{metres(robot.motion.linear_velocity_mps, 3)}/s</>
              )}
            </Field>
            <Field label="observed ω" mono>
              {robot.motion?.angular_velocity_radps == null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>{robot.motion.angular_velocity_radps.toFixed(3)} rad/s</>
              )}
            </Field>
            <Field label="commanded v" mono>
              {robot.motion?.commanded_linear_mps == null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>{metres(robot.motion.commanded_linear_mps, 3)}/s</>
              )}
            </Field>
            <Field label="command seq" mono>
              {robot.motion?.command_seq == null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>{robot.motion.command_seq}</>
              )}
            </Field>
            <Field label="stop reason">
              <Chip tone={stopTone(robot.motion?.stop_reason)}>
                {robot.motion?.stop_reason == null ? UNAVAILABLE : titleCase(robot.motion.stop_reason)}
              </Chip>
            </Field>
            <Field label="actuator">
              <span className="text-[12px]">
                {robot.motion?.actuator == null ? UNAVAILABLE : titleCase(robot.motion.actuator)}
              </span>
            </Field>
            <Field label="battery" className="col-span-2">
              <BatteryReadout
                fraction={robot.battery?.fraction}
                source={robot.battery?.source}
                drainModel={robot.battery?.drain_model}
              />
            </Field>
          </FieldGrid>
          {robot.battery?.source === "estimated" || robot.battery?.source === "simulated" ? (
            <p className="px-3 pb-2 text-[10px] text-ink-3">
              <Info className="mr-1 inline h-[10px] w-[10px]" aria-hidden />
              Battery is not a measured value in this run. Treat range as a configured assumption.
            </p>
          ) : null}
          <TelemetryStrip robotId={robot.robot_id} />
        </section>

        {/* ---------------- work + custody ---------------- */}
        <section aria-label="Task and custody" className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">task &amp; custody</h3>
          <Row label="task">
            {robot.task === null ? (
              <span className="text-ink-3">{UNAVAILABLE}</span>
            ) : (
              <span className="num">{robot.task.task_id}</span>
            )}
          </Row>
          <Row label="ownership">
            {robot.ownership === null ? (
              <span className="text-ink-3">{UNAVAILABLE}</span>
            ) : (
              <span className="num">
                {robot.ownership.state ?? "unknown"} · v{robot.ownership.ownership_version ?? 0}
              </span>
            )}
          </Row>
          <Row label="custody">
            {robot.custody === null || robot.custody.state == null ? (
              <span className="text-ink-3">none declared</span>
            ) : (
              <span className="num">
                {robot.custody.state}
                {robot.custody.custody_version != null ? ` · v${robot.custody.custody_version}` : ""}
              </span>
            )}
          </Row>
          <Row label="carrying">
            {robot.carrying_payload ? (
              <Chip tone="teal" glyph={false}>
                payload aboard
              </Chip>
            ) : (
              <span className="text-ink-3">empty</span>
            )}
          </Row>
          {robot.task !== null ? (
            <Row label="pickup → drop">
              <span className="num">
                {robot.task.pickup_station_id} → {robot.task.drop_station_id}
              </span>
            </Row>
          ) : null}
        </section>

        {/* ---------------- zones ---------------- */}
        <section aria-label="Zone authority" className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">zone authority believed</h3>
          {robot.held_zones.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">Holding no exclusive zone.</p>
          ) : (
            <ul className="px-3 pb-2">
              {robot.held_zones.map((hold) => (
                <li key={`${robot.robot_id}-${hold.zone_id}`} className="flex items-center justify-between gap-2 py-0.5">
                  <button
                    type="button"
                    onClick={() => select("zone", hold.zone_id)}
                    className="num text-[12px] text-teal underline underline-offset-2"
                  >
                    {hold.zone_id}
                  </button>
                  <span className="num text-[10px] text-ink-3">{hold.state}</span>
                </li>
              ))}
            </ul>
          )}
          {robot.observed_zones.length > 0 ? (
            <>
              <h4 className="stencil px-3 pt-1 text-[9px] text-ink-3">observed occupied</h4>
              <ul className="px-3 pb-2">
                {robot.observed_zones.slice(0, 6).map((occ) => (
                  <li key={`${robot.robot_id}-obs-${occ.zone_id}`} className="flex items-center justify-between gap-2 py-0.5 text-[11px]">
                    <button
                      type="button"
                      onClick={() => select("zone", occ.zone_id)}
                      className="num text-ink-2 underline underline-offset-2"
                    >
                      {occ.zone_id}
                    </button>
                    <span className="flex items-center gap-1">
                      <span className="text-ink-3">{occ.occupant ?? "unknown"}</span>
                      {occ.source === "evaluator" ? <Chip tone="steel">evaluator</Chip> : null}
                      {occ.age_s !== null ? <span className="num text-[10px] text-ink-3">{age(occ.age_s)}</span> : null}
                    </span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </section>

        {/* ---------------- why waiting ---------------- */}
        <section aria-label="Why waiting">
          {robot.why_waiting === null ? (
            <p className="px-3 py-2 text-[11px] text-ink-3">
              This robot is not blocked, and the API published no blocking reason.
            </p>
          ) : (
            <WhyWaitingCard why={robot.why_waiting} />
          )}
        </section>

        {/* ---------------- planner + identity ---------------- */}
        <section aria-label="Planner and process identity" className="border-t border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">planner &amp; process</h3>
          <Row label="planner state">
            {robot.planner_state ?? <span className="text-ink-3">{UNAVAILABLE}</span>}
          </Row>
          <Row label="plan version" mono>
            {robot.plan_version ?? <span className="text-ink-3">{UNAVAILABLE}</span>}
          </Row>
          <Row label="last accepted intent">
            {robot.last_accepted_intent ?? <span className="text-ink-3">none recorded</span>}
          </Row>
          <Row label="map / epoch">
            <span className="num">
              {robot.map_epoch ?? "unversioned"}
              {robot.plan_version !== null ? ` · plan ${robot.plan_version}` : ""}
            </span>
          </Row>
          <Row label="model">
            <span className="flex items-center gap-1">
              <Cpu className="h-[11px] w-[11px] text-ink-3" aria-hidden />
              {robot.identity.model ?? "unrecorded"}
            </span>
          </Row>
          <Row label="footprint" mono>
            {metres(robot.identity.footprint.width_m)} × {metres(robot.identity.footprint.length_m)}
            {robot.identity.footprint.turning_radius_m != null
              ? ` · r ${metres(robot.identity.footprint.turning_radius_m)}`
              : ""}
          </Row>
          <Row label="session (boot)">
            {robot.session === null ? (
              <span className="text-ink-3">no session record</span>
            ) : (
              <span className="num break-all text-[11px]">
                  {robot.session.session_id}
                  <span className="block text-[10px] text-ink-3">
                    pid {robot.session.pid ?? "?"} · {robot.session.host ?? "?"}:
                    {robot.session.listening_port ?? "?"} · session started{" "}
                    {simClock(robot.session.started_at_ns / 1e9)}
                  </span>
                </span>
            )}
          </Row>
          <Row label="capabilities">
            {robot.identity.capabilities == null || robot.identity.capabilities.length === 0 ? (
              <span className="text-ink-3">none declared</span>
            ) : (
              <span className="text-[11px]">{robot.identity.capabilities.join(", ")}</span>
            )}
          </Row>
        </section>

        {/* ---------------- reasons ---------------- */}
        <section aria-label="Recent reasons" className="border-t border-rule">
          <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
            <AlertTriangle className="h-[10px] w-[10px]" aria-hidden />
            recent reasons from this agent
          </h3>
          {robot.reasons.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">The agent has recorded no reasons in the retained window.</p>
          ) : (
            <ol className="px-3 pb-2">
              {robot.reasons.toReversed().map((reason) => (
                <li key={`${reason.at_seq}-${reason.text.slice(0, 24)}`} className="border-b border-rule/50 py-1 last:border-b-0">
                  <div className="flex items-center justify-between gap-2">
                    <Chip tone={reason.severity === "violation" || reason.severity === "fault" ? "red" : reason.severity === "attention" ? "amber" : "muted"}>
                      {reason.category}
                    </Chip>
                    <span className="num text-[10px] text-ink-3">
                      seq {reason.at_seq}
                      {reason.sim_time_s !== null ? ` · ${simClock(reason.sim_time_s)}` : ""}
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] leading-snug text-ink-2">{reason.text}</p>
                </li>
              ))}
            </ol>
          )}
        </section>

        {robot.degraded_reason !== null ? (
          <Strip tone="amber" className="border-t">
            <PauseOctagon className="h-[11px] w-[11px] shrink-0" aria-hidden />
            <span>
              <strong className="font-semibold">Degraded:</strong> {robot.degraded_reason}
            </span>
          </Strip>
        ) : null}
      </PanelBody>
    </Panel>
  )
}

export function RobotBatteryIcon() {
  return <BatteryCharging className="h-[11px] w-[11px]" aria-hidden />
}
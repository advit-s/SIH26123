/**
 * Task inspector.
 *
 * The bid table is deliberately shown *verbatim* — each declared component, its
 * unit, and its value — because a fleet operator's first question about a
 * makespan difference is "which term moved". Totals are never presented without
 * the components that produced them.
 */
import { Gavel } from "lucide-react"
import type { TaskInspection } from "../../lib/api/types"
import { UNAVAILABLE, age, simClock } from "../../lib/format"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { Field, FieldGrid, Row } from "../primitives/Field"
import { Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"

export function TaskInspector({ task }: { task: TaskInspection }) {
  const select = useViewStore((s) => s.select)

  return (
    <Panel ticks className="min-h-0" aria-label={`Inspector for task ${task.task_id}`}>
      <PanelHeader
        title={<span className="num">{task.task_id}</span>}
        subtitle={task.task === null ? "task definition unavailable" : `${task.task.pickup_station_id} → ${task.task.drop_station_id}`}
        tone={task.completed ? "teal" : task.blocked_reason !== null ? "amber" : "info"}
        right={
          <Chip tone={task.completed ? "teal" : task.ownership_state === "unowned" ? "muted" : "amber"}>
            {task.completed ? "completed" : task.ownership_state}
          </Chip>
        }
      />
      <PanelBody>
        <FieldGrid cols={3}>
          <Field label="owner">
            {task.owner !== null ? (
              <button
                type="button"
                onClick={() => select("robot", task.owner as string)}
                className="num text-teal underline underline-offset-2"
              >
                {task.owner}
              </button>
            ) : (
              <span className="text-ink-3">unowned</span>
            )}
          </Field>
          <Field label="ownership version" mono>
            {task.ownership_version}
          </Field>
          <Field label="feasible bids" mono>
            {task.feasible_bids} feasible / {task.infeasible_bids} infeasible
          </Field>
        </FieldGrid>

        {task.task !== null ? (
          <>
            <Row label="weight">
              <span className="num">{task.task.weight_kg == null ? UNAVAILABLE : `${task.task.weight_kg} kg`}</span>
            </Row>
            <Row label="priority" mono>
              {task.task.priority == null ? UNAVAILABLE : task.task.priority}
            </Row>
            <Row label="release at">
              <span className="num">
                {task.task.release_at_s == null ? UNAVAILABLE : simClock(task.task.release_at_s)}
              </span>
            </Row>
            <Row label="service time">
              <span className="num">
                {task.task.service_time_s == null ? UNAVAILABLE : `${task.task.service_time_s} s`}
              </span>
            </Row>
            <Row label="capabilities">
              {task.task.required_capabilities == null || task.task.required_capabilities.length === 0 ? (
                <span className="text-ink-3">none required</span>
              ) : (
                <span className="text-[11px]">{task.task.required_capabilities.join(", ")}</span>
              )}
            </Row>
          </>
        ) : null}

        <Row label="custody">
          {task.custody === null || task.custody.state == null ? (
            <span className="text-ink-3">none declared</span>
          ) : (
            <span className="num">
              {task.custody.state}
              {task.custody.holder != null ? ` · ${task.custody.holder}` : ""}
              {task.custody.custody_version != null ? ` · v${task.custody.custody_version}` : ""}
            </span>
          )}
        </Row>

        {task.blocked_reason !== null ? (
          <Strip tone="amber">
            <strong className="font-semibold">Blocked:</strong> {task.blocked_reason}
          </Strip>
        ) : null}

        {/* -------- bids -------- */}
        <section aria-label="Bid components" className="border-t border-rule">
          <h3 className="stencil flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3">
            <Gavel className="h-[10px] w-[10px]" aria-hidden />
            bid components (computed locally by each robot)
          </h3>
          {task.bids.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">
              No bid has been published for this task in the retained window.
            </p>
          ) : (
            <ul>
              {task.bids.map((bid) => {
                const winner = task.winner === bid.robot_id
                return (
                  <li
                    key={bid.robot_id}
                    className={`border-b border-rule/60 px-3 py-2 last:border-b-0 ${winner ? "bg-teal-wash" : ""}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <button
                        type="button"
                        onClick={() => select("robot", bid.robot_id)}
                        className="num text-[12px] text-ink underline underline-offset-2"
                      >
                        {bid.robot_id}
                      </button>
                      <span className="flex items-center gap-1.5">
                        <span className="num text-[12px] text-ink">total {bid.total_cost.toFixed(3)}</span>
                        <Chip tone={bid.feasible ? (winner ? "teal" : "info") : "red"}>
                          {bid.feasible ? "feasible" : "infeasible"}
                        </Chip>
                      </span>
                    </div>
                    {!bid.feasible && bid.infeasible_reason !== null ? (
                      <p className="mt-0.5 text-[11px] text-red">{bid.infeasible_reason}</p>
                    ) : null}
                    {bid.components.length > 0 ? (
                      <table className="num mt-1 w-full text-[11px]">
                        <caption className="sr-only">Declared bid components for {bid.robot_id}</caption>
                        <tbody>
                          {bid.components.map((component) => (
                            <tr key={component.name} className="border-b border-rule/40 last:border-b-0">
                              <th scope="row" className="py-0.5 pr-2 text-left font-normal text-ink-3">
                                {component.name}
                              </th>
                              <td className="py-0.5 text-right text-ink-2">{component.value.toFixed(3)}</td>
                              <td className="w-[52px] py-0.5 pl-2 text-left text-ink-3">{component.unit}</td>
                            </tr>
                          ))}
                          <tr>
                            <th scope="row" className="py-0.5 pr-2 text-left font-semibold text-ink-2">
                              total
                            </th>
                            <td className="py-0.5 text-right font-semibold text-ink">{bid.total_cost.toFixed(3)}</td>
                            <td className="py-0.5 pl-2 text-left text-ink-3">
                              {bid.tie_break === null ? "—" : `tie ${bid.tie_break.toFixed(4)}`}
                            </td>
                          </tr>
                        </tbody>
                      </table>
                    ) : (
                      <p className="mt-0.5 text-[11px] text-ink-3">
                        This robot published a total with no component breakdown.
                      </p>
                    )}
                    {bid.round_id !== null ? (
                      <p className="num mt-0.5 text-[10px] text-ink-3">round {bid.round_id}</p>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          )}
          <p className="px-3 py-1.5 text-[10px] text-ink-3">
            Awarding is deterministic given the same bid set: lowest total among feasible bids, ties broken by tie
            break then robot id. No backend picks winners.
          </p>
        </section>

        {/* -------- completion evidence -------- */}
        <section aria-label="Completion evidence" className="border-t border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">completion evidence</h3>
          {task.completion_evidence === null ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">
              No completion event has been recorded. Custody is the physical claim; it is never inferred from
              ownership.
            </p>
          ) : (
            <div className="px-3 pb-2" data-testid="task-completion-evidence">
              <Row label="event type">
                <span className="num">{task.completion_evidence.type}</span>
              </Row>
              <Row label="seq" mono>
                {task.completion_evidence.seq}
              </Row>
              <Row label="sim time">
                <span className="num">
                  {task.completion_evidence.sim_time_s == null ? UNAVAILABLE : simClock(task.completion_evidence.sim_time_s)}
                </span>
              </Row>
              <Row label="reason">
                {task.completion_evidence.reason ?? <span className="text-ink-3">none recorded</span>}
              </Row>
              <Row label="correlation" mono>
                <span className="break-all text-[10px]">{task.completion_evidence.correlation_id ?? "none"}</span>
              </Row>
            </div>
          )}
        </section>
      </PanelBody>
    </Panel>
  )
}

export function TaskRowMeta({ task }: { task: TaskInspection }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <Chip tone={task.completed ? "teal" : task.owner === null ? "muted" : "amber"}>
        {task.completed ? "completed" : task.owner ?? "unowned"}
      </Chip>
      {task.ownership_version > 0 ? <span className="num text-[10px] text-ink-3">v{task.ownership_version}</span> : null}
    </span>
  )
}

export function TaskAge({ atNs }: { atNs: number | null }) {
  if (atNs === null) return null
  return <span className="num text-[10px] text-ink-3">{age(atNs / 1e9)}</span>
}
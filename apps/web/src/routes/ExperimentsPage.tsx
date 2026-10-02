/**
 * Experiments.
 *
 * A comparison view, not a leaderboard. The three rules it enforces:
 *   1. **Configuration differences are shown before any number.** You cannot
 *      read a paired improvement until you can see what varied between the two
 *      runs it was computed from.
 *   2. **Eligibility is explicit and per-run.** An unsafe, timed-out, cancelled
 *      or evidence-incomplete run is ineligible, and is rendered as ineligible
 *      rather than quietly excluded.
 *   3. **No success badge without complete evidence.** A performance mark is
 *      only ever attached to an eligible, completed, evidence-complete run.
 */
import { useMemo, useState } from "react"
import { Ban, Check, FlaskConical } from "lucide-react"
import {
  useCreateExperimentBatch,
  useExperimentDetail,
  useExperimentReport,
  useExperiments,
} from "../lib/api/queries"
import { UNAVAILABLE, percent, titleCase } from "../lib/format"
import { useViewStore } from "../lib/view/store"
import { Button } from "../components/primitives/Button"
import { Chip } from "../components/primitives/Chip"
import { Field } from "../components/primitives/Field"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../components/primitives/Panel"
import { DataTable, type Column } from "../components/primitives/DataTable"
import { EmptyState, ErrorState, LoadingState } from "../components/primitives/States"
import type { ExperimentCell, PairedRow } from "../lib/api/types"

const FAILED_STATES = new Set(["unsafe", "failed", "timed_out", "cancelled"])

export function cellVerdict(cell: ExperimentCell): { tone: "teal" | "amber" | "red" | "muted" | "info"; label: string } {
  if (FAILED_STATES.has(cell.state)) return { tone: cell.state === "cancelled" ? "muted" : "red", label: cell.state.replace(/_/g, " ") }
  if (cell.state === "queued") return { tone: "muted", label: "queued" }
  if (cell.state === "running") return { tone: "info", label: "running" }
  if (!cell.evidence_complete) return { tone: "amber", label: "incomplete evidence" }
  if (cell.outcome === "success") return { tone: "teal", label: "success" }
  if (cell.outcome === "degraded") return { tone: "amber", label: "degraded" }
  return { tone: "muted", label: titleCase(cell.outcome) }
}

/** A success mark requires a completed, successful, evidence-complete run. */
export function SuccessBadge({ cell }: { cell: ExperimentCell }) {
  const verdict = cellVerdict(cell)
  const eligible = verdict.tone === "teal"
  return (
    <span className="inline-flex items-center gap-1">
      <Chip tone={verdict.tone} title={`outcome ${cell.outcome}, state ${cell.state}`}>
        {verdict.label}
      </Chip>
      {eligible ? (
        <span aria-label="eligible for comparison" title="eligible for a paired comparison" className="text-teal">
          <Check className="h-[11px] w-[11px]" aria-hidden />
        </span>
      ) : (
        <span
          aria-label="not eligible for comparison"
          title={cell.evidence_complete ? `not eligible: state ${cell.state}` : "not eligible: recording gaps present"}
          className="text-ink-4"
        >
          <Ban className="h-[11px] w-[11px]" aria-hidden />
        </span>
      )}
    </span>
  )
}

export function ExperimentsPage() {
  const matrix = useExperiments()
  const navigate = useViewStore((s) => s.navigate)
  const [batchId, setBatchId] = useState<string | null>(null)
  const detail = useExperimentDetail(batchId)
  const [showReport, setShowReport] = useState(false)
  const report = useExperimentReport(batchId, showReport && batchId !== null)
  const create = useCreateExperimentBatch()

  const [scenarioId, setScenarioId] = useState("")
  const [seeds, setSeeds] = useState("101,102,103")
  const [policies, setPolicies] = useState("stop_and_wait,canonical_sequential")

  const paired = detail.data?.paired ?? []
  const eligiblePairs = paired.filter((p) => p.eligible)
  const improvements = eligiblePairs
    .map((p) => p.improvement_pct)
    .filter((v): v is number => v !== null)

  const summary = useMemo(() => {
    if (improvements.length === 0) return null
    // Paired sample statistics. Mean and spread only — no claim without n.
    const mean = improvements.reduce((a, b) => a + b, 0) / improvements.length
    const variance = improvements.reduce((a, b) => a + (b - mean) ** 2, 0) / improvements.length
    const sd = Math.sqrt(variance)
    const sorted = improvements.toSorted((a, b) => a - b)
    const median = sorted[Math.floor(sorted.length / 2)] ?? 0
    return { n: improvements.length, mean, sd, median }
  }, [improvements])

  const runColumns: Column<ExperimentCell>[] = [
    { key: "run", header: "run", mono: true, render: (c) => c.run_id },
    {
      key: "config",
      header: "configuration",
      width: "230px",
      render: (c) => (
        <span className="num text-[10px] text-ink-2">
          {c.scenario_id} @ r{c.scenario_revision} · seed {c.seed} · {c.coordination_policy}
        </span>
      ),
    },
    { key: "verdict", header: "verdict", width: "180px", render: (c) => <SuccessBadge cell={c} /> },
    {
      key: "makespan",
      header: "makespan",
      mono: true,
      align: "right",
      width: "110px",
      render: (c) => (c.makespan_s === null ? <span className="text-ink-3">{UNAVAILABLE}</span> : `${c.makespan_s.toFixed(2)} s`),
    },
    {
      key: "tasks",
      header: "tasks",
      mono: true,
      align: "right",
      width: "90px",
      render: (c) => `${c.tasks_completed}/${c.tasks_total}`,
    },
    {
      key: "collisions",
      header: "collisions",
      mono: true,
      align: "right",
      width: "96px",
      render: (c) =>
        c.collisions === null ? (
          <span className="text-ink-3" title="No collision metric was published for this run.">
            {UNAVAILABLE}
          </span>
        ) : (
          <span className={c.collisions === 0 ? "text-ink" : "text-red"}>{c.collisions}</span>
        ),
    },
    {
      key: "evidence",
      header: "evidence",
      width: "110px",
      render: (c) => (c.evidence_complete ? <Chip tone="teal">complete</Chip> : <Chip tone="amber">gaps present</Chip>),
    },
    {
      key: "open",
      header: "",
      width: "80px",
      render: (c) => (
        <button
          type="button"
          onClick={() => navigate("operations", c.run_id)}
          className="border border-rule px-1.5 py-0.5 text-[10px] text-ink-2 hover:border-rule-strong hover:text-ink"
        >
          open
        </button>
      ),
    },
  ]

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_400px]">
      <div className="flex min-h-0 flex-col gap-2 overflow-auto border-r border-rule p-2">
        <Panel ticks className="shrink-0">
          <PanelHeader
            title="experiment batches"
            subtitle="run matrices over immutable scenario revisions"
            tone="info"
            right={<Chip tone="muted">{`${matrix.data?.total_runs ?? 0} runs`}</Chip>}
          />
          <PanelBody scroll={false}>
            {matrix.isError ? (
              <ErrorState error={matrix.error} what="The experiment matrix" onRetry={() => void matrix.refetch()} />
            ) : matrix.isPending ? (
              <LoadingState what="experiment batches" />
            ) : (matrix.data?.batches.length ?? 0) === 0 ? (
              <EmptyState
                title="No experiment batches yet"
                body="A batch pairs a scenario revision against both coordination policies across a set of seeds, so the only difference between the two arms is the protocol under test."
              />
            ) : (
              <ul className="divide-y divide-rule">
                {matrix.data?.batches.map((batch) => (
                  <li key={batch.batch_id} className="flex items-center gap-2 px-3 py-2" data-testid="batch-row">
                    <span className="num min-w-0 flex-1 break-all text-[12px] text-ink">{batch.name}</span>
                    <span className="num text-[10px] text-ink-3">{batch.run_count} runs</span>
                    <Chip tone={batch.state === "completed" ? "teal" : batch.state === "failed" ? "red" : "amber"}>
                      {batch.state}
                    </Chip>
                    <Button
                      onClick={() => {
                        setBatchId(batch.batch_id)
                        setShowReport(false)
                      }}
                      variant={batchId === batch.batch_id ? "primary" : "default"}
                    >
                      {batchId === batch.batch_id ? "open" : "inspect"}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
            {(matrix.data?.axes.length ?? 0) > 0 ? (
              <div className="border-t border-rule px-3 py-2">
                <p className="stencil text-[9px] text-ink-3">axes in this matrix</p>
                <ul className="mt-1 flex flex-wrap gap-1.5">
                  {matrix.data?.axes.map((axis) => (
                    <li key={axis.name}>
                      <Chip tone="info">
                        {axis.name}: {axis.values.join(" · ")}
                      </Chip>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </PanelBody>
        </Panel>

        {batchId === null ? (
          <Panel ticks className="min-h-0 flex-1">
            <PanelHeader title="select a batch" tone="muted" />
            <PanelBody scroll={false}>
              <EmptyState
                title="Nothing selected"
                body="Pick a batch to see its raw runs, its configuration differences and its paired table."
              />
            </PanelBody>
          </Panel>
        ) : detail.isError ? (
          <Panel ticks className="min-h-0 flex-1">
            <PanelHeader title={`batch ${batchId}`} tone="red" />
            <PanelBody scroll={false}>
              <ErrorState error={detail.error} what="This experiment batch" onRetry={() => void detail.refetch()} />
            </PanelBody>
          </Panel>
        ) : detail.isPending ? (
          <Panel ticks className="min-h-0 flex-1">
            <PanelHeader title={`batch ${batchId}`} tone="info" />
            <PanelBody scroll={false}>
              <LoadingState what="the experiment batch" />
            </PanelBody>
          </Panel>
        ) : (
          <>
            {/* -------- configuration differences, BEFORE any number -------- */}
            <Panel ticks className="shrink-0" data-testid="config-diff">
              <PanelHeader
                title="configuration differences"
                subtitle="read this before reading any improvement"
                tone={detail.data?.config_diff.some((d) => d.material) ? "amber" : "teal"}
              />
              <PanelBody scroll={false}>
                {detail.data?.config_diff.length === 0 ? (
                  <p className="px-3 py-2 text-[12px] text-ink-3">
                    The API published no configuration diff for this batch. Differences are unknown, not identical.
                  </p>
                ) : (
                  <table className="w-full text-[11px]">
                    <caption className="sr-only">Configuration differences across the batch runs</caption>
                    <thead>
                      <tr className="border-b border-rule">
                        <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                          field
                        </th>
                        <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                          values across runs
                        </th>
                        <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
                          material?
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {detail.data?.config_diff.map((diff) => (
                        <tr key={diff.field} className="border-b border-rule/50">
                          <th scope="row" className="num px-2 py-1 text-left font-normal text-ink-2">
                            {diff.field}
                          </th>
                          <td className="num px-2 py-1 text-ink-3">
                            {diff.values.map((v) => `${v.run_id.slice(0, 10)}=${v.value}`).join(" · ")}
                          </td>
                          <td className="px-2 py-1">
                            {diff.material ? <Chip tone="amber">material</Chip> : <Chip tone="muted">immaterial</Chip>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </PanelBody>
            </Panel>

            {/* -------- raw runs -------- */}
            <Panel ticks className="min-h-0 flex-1">
              <PanelHeader
                title="raw runs"
                subtitle="every run, including failures"
                tone="info"
                right={
                  <Button onClick={() => setShowReport((v) => !v)} disabled={detail.data?.report_available === false}>
                    {showReport ? "hide report" : "show report"}
                  </Button>
                }
              />
              <PanelBody>
                <DataTable
                  caption="Every run in the batch with its configuration, verdict, makespan, task counts and evidence completeness"
                  columns={runColumns}
                  rows={detail.data?.runs ?? []}
                  rowKey={(c) => c.run_id}
                  sort={null}
                  onSort={() => {}}
                />
              </PanelBody>
            </Panel>

            {/* -------- paired table -------- */}
            <Panel ticks className="shrink-0">
              <PanelHeader
                title="paired comparison"
                subtitle="same seed, both policies — eligibility is per pair"
                tone={summary !== null ? "teal" : "amber"}
                right={
                  <Chip tone="muted">
                    {`${eligiblePairs.length} eligible of ${paired.length} pairs`}
                  </Chip>
                }
              />
              <PanelBody>
                {summary === null ? (
                  <HatchStrip tone="amber">
                    <span data-testid="no-eligible-pairs">
                      <strong className="font-semibold">No eligible pair.</strong> No improvement figure can be
                      reported until at least one pair completed successfully with complete evidence on both sides.
                    </span>
                  </HatchStrip>
                ) : (
                  <div className="flex flex-wrap items-center gap-3 px-3 py-2" data-testid="paired-summary">
                    <Metric label="eligible pairs" value={`${summary.n}`} />
                    <Metric label="mean improvement" value={percent(summary.mean)} tone="teal" />
                    <Metric label="median improvement" value={percent(summary.median)} tone="teal" />
                    <Metric label="std. deviation" value={`${summary.sd.toFixed(1)} pp`} tone="amber" />
                  </div>
                )}
                <PairedTable rows={paired} />
                {detail.data !== undefined && detail.data.eligibility.ineligible_runs.length > 0 ? (
                  <div className="px-3 py-2">
                    <p className="stencil text-[9px] text-ink-3">ineligible runs and why</p>
                    <ul className="mt-1 space-y-0.5">
                      {detail.data.eligibility.ineligible_runs.map((r) => (
                        <li key={r.run_id} className="num text-[11px]">
                          <span className="text-red">{r.run_id}</span>{" "}
                          <span className="text-ink-3">{r.reason}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
                <Strip tone="info" className="mx-3 mb-2 border">
                  <span className="text-[10px]">
                    The ≥20 % makespan figure is a target. It is reported only as a paired measurement with these
                    eligibility rules and this sample count — never as a claim, and never averaged across
                    ineligible runs.
                  </span>
                </Strip>
                {showReport ? <ReportView markdown={report.data?.markdown ?? null} csv={report.data?.csv ?? null} isLoading={report.isPending} error={report.error} /> : null}
              </PanelBody>
            </Panel>
          </>
        )}
      </div>

      {/* -------- right: new batch -------- */}
      <aside className="flex min-h-0 flex-col gap-2 overflow-auto p-2">
        <Panel ticks className="shrink-0">
          <PanelHeader
            title="new experiment batch"
            subtitle="paired over seeds, same immutable revision"
            tone="info"
            right={<FlaskConical className="h-[11px] w-[11px] text-ink-3" aria-hidden />}
          />
          <PanelBody scroll={false}>
            <div className="space-y-2 px-3 py-2">
              <Field label="scenario id" mono>
                <input
                  value={scenarioId}
                  onChange={(e) => setScenarioId(e.target.value)}
                  placeholder="e.g. three-way-intersection"
                  className="num w-full border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </Field>
              <Field label="seeds (comma separated)" mono>
                <input
                  value={seeds}
                  onChange={(e) => setSeeds(e.target.value)}
                  className="num w-full border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </Field>
              <Field label="coordination policies" mono>
                <input
                  value={policies}
                  onChange={(e) => setPolicies(e.target.value)}
                  className="num w-full border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </Field>
              <Button
                variant="primary"
                disabled={scenarioId.trim() === "" || create.isPending}
                onClick={() =>
                  create.mutate({
                    scenario_id: scenarioId.trim(),
                    seeds: seeds
                      .split(",")
                      .map((s) => Number(s.trim()))
                      .filter((n) => Number.isFinite(n)),
                    coordination: policies
                      .split(",")
                      .map((s) => s.trim())
                      .filter((s) => s.length > 0),
                    revisions: [],
                  })
                }
              >
                Queue batch
              </Button>
              {create.isError ? (
                <HatchStrip tone="red">
                  The batch was refused: {create.error instanceof Error ? create.error.message : "the API rejected the request."}
                </HatchStrip>
              ) : null}
              <p className="text-[10px] text-ink-3">
                A batch may only compare immutable scenario revisions. Editing a scenario afterwards never mutates a
                run that has already executed.
              </p>
            </div>
          </PanelBody>
        </Panel>

        <Panel ticks className="min-h-0 flex-1">
          <PanelHeader title="method notes" tone="info" />
          <PanelBody>
            <ul className="space-y-2 px-3 py-2 text-[11px] leading-relaxed text-ink-2">
              <li>
                <strong className="font-semibold text-ink">Eligibility.</strong> A run is ineligible if it ended
                unsafe, failed, timed out, was cancelled, or has unresolved recording gaps. An ineligible run is
                never given a success mark.
              </li>
              <li>
                <strong className="font-semibold text-ink">Pairing.</strong> Only baseline/candidate pairs sharing a
                seed and a scenario revision are compared.
              </li>
              <li>
                <strong className="font-semibold text-ink">Collisions.</strong> A zero observed collision count in
                one run is not a collision-free proof and is reported as an observation with its evidence path.
              </li>
              <li>
                <strong className="font-semibold text-ink">Cancelling</strong> a batch does not corrupt its
                artifacts: a cancelled run is recorded with the reason and excluded from claims.
              </li>
            </ul>
          </PanelBody>
        </Panel>
      </aside>
    </div>
  )
}

function Metric({ label, value, tone = "info" }: { label: string; value: string; tone?: "teal" | "amber" | "info" }) {
  return (
    <div className="border-l-2 border-rule pl-2" style={tone === "teal" ? { borderColor: "var(--nm-teal)" } : tone === "amber" ? { borderColor: "var(--nm-amber)" } : undefined}>
      <p className="stencil text-[9px] text-ink-3">{label}</p>
      <p className="num text-[16px] leading-tight text-ink">{value}</p>
    </div>
  )
}

function PairedTable({ rows }: { rows: PairedRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="px-3 pb-2 text-[12px] text-ink-3">
        The API published no paired rows for this batch. Absence of pairs is not evidence of equal performance.
      </p>
    )
  }
  return (
    <div className="px-2 pb-2">
      <table className="w-full text-[11px]">
        <caption className="sr-only">Paired baseline and candidate results per seed, with eligibility</caption>
        <thead>
          <tr className="border-b border-rule">
            <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
              seed
            </th>
            <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
              baseline
            </th>
            <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
              candidate
            </th>
            <th scope="col" className="stencil px-2 py-1 text-right text-[9px] text-ink-3">
              Δ makespan
            </th>
            <th scope="col" className="stencil px-2 py-1 text-left text-[9px] text-ink-3">
              eligible
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.seed}-${row.baseline_run_id}`} className="border-b border-rule/50">
              <td className="num px-2 py-1 text-ink-2">{row.seed}</td>
              <td className="num px-2 py-1 text-ink-3">
                {row.baseline_makespan_s === null ? UNAVAILABLE : `${row.baseline_makespan_s.toFixed(2)} s`}
              </td>
              <td className="num px-2 py-1 text-ink-3">
                {row.candidate_makespan_s === null ? UNAVAILABLE : `${row.candidate_makespan_s.toFixed(2)} s`}
              </td>
              <td
                className={`num px-2 py-1 text-right ${
                  row.eligible ? (row.improvement_pct != null && row.improvement_pct >= 20 ? "text-teal" : "text-ink") : "text-ink-4"
                }`}
              >
                {row.eligible && row.improvement_pct != null ? percent(row.improvement_pct) : "—"}
              </td>
              <td className="px-2 py-1">
                {row.eligible ? (
                  <Chip tone="teal">paired</Chip>
                ) : (
                  <Chip tone="amber" title={row.ineligible_reason ?? undefined}>
                    excluded
                  </Chip>
                )}
                {row.ineligible_reason !== null ? (
                  <span className="ml-1 text-[10px] text-ink-3">{row.ineligible_reason}</span>
                ) : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ReportView({
  markdown,
  csv,
  isLoading,
  error,
}: {
  markdown: string | null
  csv: string | null
  isLoading: boolean
  error: unknown
}) {
  if (isLoading) return <LoadingState what="the report bundle" rows={3} />
  if (error !== null) return <ErrorState error={error} what="The report bundle" />
  return (
    <div className="border-t border-rule">
      <div className="flex items-center gap-1.5 px-3 py-1.5">
        <span className="stencil text-[9px] text-ink-3">generated report</span>
        <Chip tone="muted">markdown + raw csv</Chip>
      </div>
      <pre className="num scroll-y max-h-[240px] whitespace-pre-wrap border-t border-rule bg-raised px-3 py-2 text-[10px] leading-relaxed text-ink-2">
        {markdown ?? UNAVAILABLE}
      </pre>
      {csv !== null && csv.length > 0 ? (
        <details className="border-t border-rule">
          <summary className="stencil cursor-pointer px-3 py-1 text-[9px] text-ink-3">raw csv</summary>
          <pre className="num scroll-y max-h-[180px] px-3 py-2 text-[10px] text-ink-3">{csv}</pre>
        </details>
      ) : null}
    </div>
  )
}
/**
 * Scenario workbench.
 *
 * This is a **semantic** editor, not a drawing canvas. The author picks an
 * entity type (obstacle, zone, stop line, berth, station, robot start, task,
 * route edge, fault) and edits its numbers; the map reflects the change
 * immediately. Nothing is silently repaired — an invalid draft is preserved and
 * explained, and launch is blocked with a specific list of problems.
 *
 * Severity is split on purpose:
 *   - `error`      structural invalidity: the document cannot be executed.
 *   - `warning`    including *intentionally infeasible workloads*, which are
 *                  legal only as an explicitly labelled expected-failure
 *                  experiment and are never eligible for a success comparison.
 */
import { useEffect, useState } from "react"
import { FilePlus2, History, Rocket, Save, Upload } from "lucide-react"
import type { Scenario } from "@niharamesh/contracts/generated"
import {
  useLaunchScenario,
  useSaveScenario,
  useScenarioDetail,
  useScenarioLibrary,
  useValidateScenario,
} from "../lib/api/queries"
import { UNAVAILABLE, titleCase } from "../lib/format"
import { useViewStore } from "../lib/view/store"
import { Button } from "../components/primitives/Button"
import { Chip } from "../components/primitives/Chip"
import { ControlField, Field } from "../components/primitives/Field"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../components/primitives/Panel"
import { DataTable, type Column } from "../components/primitives/DataTable"
import { EmptyState, ErrorState, LoadingState } from "../components/primitives/States"
import type { ValidationProblem, ValidationReport } from "../lib/api/types"
import { emptyValidation } from "../lib/api/mappers"

const EMPTY_SCENARIO: Scenario = {
  scenario_id: "draft",
  name: "Untitled scenario",
  intent: { goal: "Describe what this experiment is for." },
  map: {
    map_id: "draft-map",
    boundary: { min_x: 0, min_y: 0, max_x: 20, max_y: 12 },
    obstacles: [],
    stations: [],
    berths: [],
    stop_lines: [],
    zones: [],
  },
  robots: [],
  starts: [],
  tasks: [],
  faults: [],
}

/** Undo/redo over scenario documents. Snapshots are cheap and explicit. */
function useHistory(initial: Scenario) {
  const [past, setPast] = useState<Scenario[]>([])
  const [present, setPresent] = useState<Scenario>(initial)
  const [future, setFuture] = useState<Scenario[]>([])

  const commit = (next: Scenario) => {
    setPast((p) => [...p, present].slice(-40))
    setPresent(next)
    setFuture([])
  }
  const undo = () => {
    setPast((p) => {
      if (p.length === 0) return p
      const previous = p[p.length - 1]
      setPresent(previous as Scenario)
      setFuture((f) => [present, ...f].slice(0, 40))
      return p.slice(0, -1)
    })
  }
  const redo = () => {
    setFuture((f) => {
      if (f.length === 0) return f
      const next = f[0]
      setPresent(next as Scenario)
      setPast((p) => [...p, present].slice(-40))
      return f.slice(1)
    })
  }
  return { scenario: present, commit, undo, redo, canUndo: past.length > 0, canRedo: future.length > 0 }
}

export function ScenariosPage({ initialScenarioId }: { initialScenarioId: string | null }) {
  const library = useScenarioLibrary()
  const navigate = useViewStore((s) => s.navigate)
  const [selectedId, setSelectedId] = useState<string | null>(initialScenarioId)
  const detail = useScenarioDetail(selectedId)
  const validate = useValidateScenario()
  const save = useSaveScenario()
  const launch = useLaunchScenario()

  const history = useHistory(EMPTY_SCENARIO)
  const [loadedDigest, setLoadedDigest] = useState<string | null>(null)
  const [dirty, setDirty] = useState(false)
  const [validation, setValidation] = useState<ValidationReport>(emptyValidation())
  const [launchError, setLaunchError] = useState<string | null>(null)

  useEffect(() => {
    if (detail.data === undefined || detail.data.scenario === undefined) return
    const digest = `${detail.data.scenario_id}@r${detail.data.revision}`
    if (digest === loadedDigest) return
    history.commit(detail.data.scenario)
    setValidation(detail.data.validation)
    setLoadedDigest(digest)
    setDirty(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail.data, loadedDigest])

  const scenario = history.scenario

  const edit = (mutate: (draft: Scenario) => Scenario) => {
    history.commit(mutate(structuredClone(scenario)))
    setDirty(true)
  }

  const gridSnap = (value: number) => Math.round(value * 2) / 2

  const runValidation = async () => {
    try {
      const report = await validate.mutateAsync(scenario)
      setValidation(report)
      return report
    } catch {
      setValidation({
        ...emptyValidation(),
        valid: false,
        launchable: false,
        problems: [
          {
            code: "validation_unavailable",
            severity: "error",
            path: "",
            message:
              "The validation service could not be reached, so this draft has NOT been validated. It is preserved exactly as edited; launch is blocked until validation succeeds.",
          },
        ],
        counts: { error: 1, warning: 0, info: 0 },
      })
      return null
    }
  }

  const doLaunch = async () => {
    setLaunchError(null)
    const report = await runValidation()
    if (report === null || !report.launchable) return
    try {
      const result = await launch.mutateAsync({
        scenarioId: scenario.scenario_id,
        idempotencyKey: `cockpit-launch-${scenario.scenario_id}-r${scenario.revision ?? 0}-${Date.now().toString(36)}`,
      })
      navigate("operations", result.run_id)
    } catch (error: unknown) {
      setLaunchError(error instanceof Error ? error.message : "The launch was refused by the API.")
    }
  }

  const importJson = (text: string) => {
    try {
      const parsed: unknown = JSON.parse(text)
      if (typeof parsed !== "object" || parsed === null) throw new Error("not an object")
      history.commit(parsed as Scenario)
      setDirty(true)
      setLoadedDigest(null)
      setValidation(emptyValidation())
    } catch (error: unknown) {
      setLaunchError(
        `Import refused: ${error instanceof Error ? error.message : "the file is not a JSON scenario document"}. Nothing was replaced.`,
      )
    }
  }

  const exportJson = () => {
    const blob = new Blob([JSON.stringify(scenario, null, 2)], { type: "application/json" })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${scenario.scenario_id}-r${scenario.revision ?? 0}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const columns: Column<ScenarioSummaryRow>[] = [
    {
      key: "id",
      header: "scenario",
      mono: true,
      render: (row) => (
        <span>
          <span className="block">{row.scenario_id}</span>
          <span className="block text-[10px] text-ink-3">{row.name}</span>
        </span>
      ),
    },
    { key: "rev", header: "rev", mono: true, width: "52px", render: (row) => row.revision },
    { key: "kind", header: "kind", width: "96px", render: (row) => <Chip tone={row.kind === "fault" ? "amber" : "info"}>{row.kind}</Chip> },
    {
      key: "size",
      header: "robots / tasks / zones",
      width: "150px",
      mono: true,
      render: (row) => `${row.robot_count} / ${row.task_count} / ${row.zone_count}`,
    },
    {
      key: "action",
      header: "",
      width: "80px",
      render: (row) => (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation()
            setSelectedId(row.scenario_id)
          }}
          className="border border-rule px-1.5 py-0.5 text-[10px] text-ink-2 hover:border-rule-strong hover:text-ink"
        >
          open
        </button>
      ),
    },
  ]

  const summaries: ScenarioSummaryRow[] = library.data ?? []

  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_430px]">
      <div className="flex min-h-0 flex-col gap-2 overflow-auto border-r border-rule p-2">
        {/* -------- library -------- */}
        <Panel ticks className="shrink-0">
          <PanelHeader
            title="scenario library"
            subtitle="immutable revisions · editing never mutates a launched run"
            tone="info"
            right={
              <Chip tone="muted">{summaries.length} revisions</Chip>
            }
          />
          <PanelBody scroll={false}>
            {library.isError ? (
              <ErrorState error={library.error} what="The scenario library" onRetry={() => void library.refetch()} />
            ) : library.isPending ? (
              <LoadingState what="scenarios" />
            ) : summaries.length === 0 ? (
              <EmptyState
                title="No scenarios are installed yet"
                body="Add a scenario JSON to the library, or import one below. A scenario is the immutable authored experiment: a map, robot identities and footprints, starts, tasks and a fault schedule."
                action={
                  <Button onClick={() => history.commit(structuredClone(EMPTY_SCENARIO))}>
                    <FilePlus2 className="h-[12px] w-[12px]" aria-hidden />
                    Start a new draft
                  </Button>
                }
              />
            ) : (
              <DataTable
                caption="Saved scenario revisions"
                columns={columns}
                rows={summaries}
                rowKey={(r) => `${r.scenario_id}@r${r.revision}`}
                sort={null}
                onSort={() => {}}
                selectedKey={selectedId}
                onRowClick={(row) => setSelectedId(row.scenario_id)}
              />
            )}
          </PanelBody>
        </Panel>

        {/* -------- semantic editor -------- */}
        <Panel ticks className="min-h-0 flex-1">
          <PanelHeader
            title={`semantic editor — ${scenario.scenario_id} r${scenario.revision ?? 0}`}
            subtitle="edit entity numbers; the map follows. Nothing is repaired automatically."
            tone={dirty ? "amber" : "info"}
            right={
              <div className="flex items-center gap-1.5">
                <Button onClick={history.undo} disabled={!history.canUndo} aria-label="Undo last edit">
                  <History className="h-[11px] w-[11px]" aria-hidden />
                  Undo
                </Button>
                <Button onClick={history.redo} disabled={!history.canRedo} aria-label="Redo last edit">
                  Redo
                </Button>
              </div>
            }
          />
          <PanelBody>
            <div className="grid gap-3 p-3 min-[980px]:grid-cols-2">
              <ControlField label="scenario name">
                <input
                  value={scenario.name}
                  onChange={(event) => edit((d) => ({ ...d, name: event.target.value }))}
                  className="w-full border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </ControlField>
              <ControlField label="seed">
                <input
                  type="number"
                  value={scenario.seed ?? 0}
                  onChange={(event) => edit((d) => ({ ...d, seed: Number(event.target.value) }))}
                  className="num w-full border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </ControlField>
              <ControlField label="experiment goal" className="min-[980px]:col-span-2">
                <textarea
                  rows={2}
                  value={scenario.intent.goal}
                  onChange={(event) => edit((d) => ({ ...d, intent: { ...d.intent, goal: event.target.value } }))}
                  className="w-full resize-y border border-rule bg-raised px-1.5 py-1 text-[12px] text-ink"
                />
              </ControlField>

              <MapEditor scenario={scenario} edit={edit} gridSnap={gridSnap} />
              <EntityEditor scenario={scenario} edit={edit} gridSnap={gridSnap} />
            </div>

            <div className="flex flex-wrap items-center gap-1.5 border-t border-rule px-3 py-2">
              <Button onClick={() => void runValidation()} disabled={validate.isPending} data-testid="validate-scenario">
                {validate.isPending ? "Validating…" : "Validate draft"}
              </Button>
              <Button
                onClick={() => save.mutate(scenario)}
                disabled={save.isPending}
                data-testid="save-scenario"
              >
                <Save className="h-[12px] w-[12px]" aria-hidden />
                Save as new revision
              </Button>
              <Button variant="primary" onClick={() => void doLaunch()} disabled={launch.isPending} data-testid="launch-scenario">
                <Rocket className="h-[12px] w-[12px]" aria-hidden />
                {launch.isPending ? "Launching…" : "Validate and launch"}
              </Button>
              <Button onClick={exportJson}>Export JSON</Button>
              <label className="inline-flex cursor-pointer items-center gap-1.5 border border-rule bg-raised px-2.5 py-1 text-[12px] text-ink hover:border-rule-strong">
                <Upload className="h-[12px] w-[12px]" aria-hidden />
                Import JSON
                <input
                  type="file"
                  accept="application/json"
                  className="sr-only"
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file === undefined) return
                    void file.text().then(importJson)
                    event.target.value = ""
                  }}
                />
              </label>
              {dirty ? <Chip tone="amber">unvalidated draft</Chip> : null}
            </div>

            {launchError !== null ? (
              <HatchStrip tone="red">
                <span data-testid="launch-error">
                  <strong className="font-semibold">Launch blocked.</strong> {launchError}
                </span>
              </HatchStrip>
            ) : null}
            {save.isError ? (
              <HatchStrip tone="red">
                Save refused: {save.error instanceof Error ? save.error.message : "the API rejected the document."}
              </HatchStrip>
            ) : null}

            <ValidationPanel report={validation} />

            <pre className="num scroll-y max-h-[220px] border-t border-rule bg-raised px-3 py-2 text-[10px] leading-relaxed text-ink-3">
              {JSON.stringify(scenario, null, 2)}
            </pre>
          </PanelBody>
        </Panel>
      </div>

      {/* -------- right column: revisions + record -------- */}
      <aside className="flex min-h-0 flex-col gap-2 overflow-auto p-2">
        <Panel ticks className="shrink-0">
          <PanelHeader title="revision record" tone="info" />
          <PanelBody scroll={false}>
            <dl className="grid grid-cols-2 gap-2 px-3 py-2">
              <Field label="scenario id" mono>
                {scenario.scenario_id}
              </Field>
              <Field label="revision" mono>
                {scenario.revision ?? UNAVAILABLE}
              </Field>
              <Field label="map id" mono>
                {scenario.map.map_id}
              </Field>
              <Field label="map revision" mono>
                {scenario.map.revision ?? UNAVAILABLE}
              </Field>
              <Field label="grid snap">
                0.50 m (applied on numeric entry)
              </Field>
              <Field label="schema version" mono>
                {scenario.schema_version ?? UNAVAILABLE}
              </Field>
            </dl>
            <Strip tone="info" className="border-t">
              <span className="text-[10px]">
                Launching freezes this document into an immutable snapshot with its own digest. Editing here cannot
                change a run that is already going.
              </span>
            </Strip>
          </PanelBody>
        </Panel>

        {selectedId !== null ? (
          <Panel ticks className="min-h-0 flex-1">
            <PanelHeader title={`authored document — ${selectedId}`} tone="info" />
            <PanelBody>
              {detail.isPending ? (
                <LoadingState what="the authored document" />
              ) : detail.isError ? (
                <ErrorState error={detail.error} what="This scenario" onRetry={() => void detail.refetch()} />
              ) : (
                <pre className="num p-3 text-[10px] leading-relaxed text-ink-3">
                  {JSON.stringify(detail.data?.scenario ?? {}, null, 2)}
                </pre>
              )}
            </PanelBody>
          </Panel>
        ) : null}
      </aside>
    </div>
  )
}

interface ScenarioSummaryRow {
  scenario_id: string
  name: string
  revision: number
  kind: string
  robot_count: number
  task_count: number
  zone_count: number
}

/* -------------------------------------------------------------------------- */
/* Map entity editor                                                          */
/* -------------------------------------------------------------------------- */

function MapEditor({
  scenario,
  edit,
  gridSnap,
}: {
  scenario: Scenario
  edit: (mutate: (draft: Scenario) => Scenario) => void
  gridSnap: (value: number) => number
}) {
  const map = scenario.map
  const obstacles = map.obstacles ?? []
  const zones = map.zones ?? []
  const stations = map.stations ?? []
  const berths = map.berths ?? []
  const stopLines = map.stop_lines ?? []

  const addObstacle = () => {
    const id = `shelf-${obstacles.length + 1}`
    edit((d) => ({
      ...d,
      map: {
        ...d.map,
        obstacles: [
          ...(d.map.obstacles ?? []),
          { id, kind: "shelf", pose: { x: gridSnap(4), y: gridSnap(4), theta: 0 }, length_m: 4, width_m: 1.2 },
        ],
      },
    }))
  }

  const addZone = () => {
    const id = `Z-${String(zones.length + 1).padStart(2, "0")}`
    const x = gridSnap(2)
    const y = gridSnap(2)
    edit((d) => ({
      ...d,
      map: {
        ...d.map,
        zones: [
          ...(d.map.zones ?? []),
          {
            id,
            kind: "exclusive",
            protected_origin: [x, y],
            protected_extent: [4, 3],
            entry_pose: { x: x - 0.8, y: y + 1.5, theta: 0 },
            exit_pose: { x: x + 4.8, y: y + 1.5, theta: 0 },
            allowed_movement: ["forward"],
          },
        ],
      },
    }))
  }

  return (
    <section className="panel-ticks border border-rule p-2">
      <h3 className="stencil text-[10px] text-ink-2">map entities</h3>

      <div className="mt-1.5 grid grid-cols-4 gap-1.5">
        <ControlField label="min x">
          <NumInput
            value={map.boundary.min_x}
            onChange={(v) => edit((d) => ({ ...d, map: { ...d.map, boundary: { ...d.map.boundary, min_x: v } } }))}
          />
        </ControlField>
        <ControlField label="min y">
          <NumInput
            value={map.boundary.min_y}
            onChange={(v) => edit((d) => ({ ...d, map: { ...d.map, boundary: { ...d.map.boundary, min_y: v } } }))}
          />
        </ControlField>
        <ControlField label="max x">
          <NumInput
            value={map.boundary.max_x}
            onChange={(v) => edit((d) => ({ ...d, map: { ...d.map, boundary: { ...d.map.boundary, max_x: v } } }))}
          />
        </ControlField>
        <ControlField label="max y">
          <NumInput
            value={map.boundary.max_y}
            onChange={(v) => edit((d) => ({ ...d, map: { ...d.map, boundary: { ...d.map.boundary, max_y: v } } }))}
          />
        </ControlField>
      </div>

      <p className="stencil mt-2 text-[9px] text-ink-3">obstacles / shelves ({obstacles.length})</p>
      <ul className="mt-1 space-y-1">
        {obstacles.map((obstacle, index) => (
          <li key={obstacle.id} className="grid grid-cols-[1fr_52px_52px_52px_24px] items-end gap-1">
            <input
              value={obstacle.id}
              aria-label={`Obstacle ${index + 1} id`}
              onChange={(e) =>
                edit((d) => ({
                  ...d,
                  map: {
                    ...d.map,
                    obstacles: (d.map.obstacles ?? []).map((o, i) => (i === index ? { ...o, id: e.target.value } : o)),
                  },
                }))
              }
              className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
            />
            <NumInput
              label="len m"
              value={obstacle.length_m}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  map: {
                    ...d.map,
                    obstacles: (d.map.obstacles ?? []).map((o, i) => (i === index ? { ...o, length_m: v } : o)),
                  },
                }))
              }
            />
            <NumInput
              label="wid m"
              value={obstacle.width_m}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  map: {
                    ...d.map,
                    obstacles: (d.map.obstacles ?? []).map((o, i) => (i === index ? { ...o, width_m: v } : o)),
                  },
                }))
              }
            />
            <NumInput
              label="x"
              value={obstacle.pose.x}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  map: {
                    ...d.map,
                    obstacles: (d.map.obstacles ?? []).map((o, i) =>
                      i === index ? { ...o, pose: { ...o.pose, x: gridSnap(v) } } : o,
                    ),
                  },
                }))
              }
            />
            <button
              type="button"
              aria-label={`Remove obstacle ${obstacle.id}`}
              onClick={() =>
                edit((d) => ({
                  ...d,
                  map: { ...d.map, obstacles: (d.map.obstacles ?? []).filter((_, i) => i !== index) },
                }))
              }
              className="h-[20px] border border-rule text-[11px] text-ink-3 hover:border-red hover:text-red"
            >
              ×
            </button>
          </li>
        ))}
      </ul>
      <Button className="mt-1.5" onClick={addObstacle}>
        Add obstacle
      </Button>

      <p className="stencil mt-2.5 text-[9px] text-ink-3">exclusive zones ({zones.length})</p>
      <ul className="mt-1 space-y-1">
        {zones.map((zone, index) => {
          const origin = Array.isArray(zone.protected_origin) ? zone.protected_origin : [0, 0]
          const extent = Array.isArray(zone.protected_extent) ? zone.protected_extent : [0, 0]
          return (
            <li key={zone.id} className="grid grid-cols-[1fr_52px_52px_52px_52px_24px] items-end gap-1">
              <input
                value={zone.id}
                aria-label={`Zone ${index + 1} id`}
                onChange={(e) =>
                  edit((d) => ({
                    ...d,
                    map: { ...d.map, zones: (d.map.zones ?? []).map((z, i) => (i === index ? { ...z, id: e.target.value } : z)) },
                  }))
                }
                className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
              />
              <NumInput
                label="ox"
                value={typeof origin[0] === "number" ? origin[0] : 0}
                onChange={(v) =>
                  edit((d) => ({
                    ...d,
                    map: {
                      ...d.map,
                      zones: (d.map.zones ?? []).map((z, i) =>
                        i === index ? { ...z, protected_origin: [gridSnap(v), typeof origin[1] === "number" ? origin[1] : 0] } : z,
                      ),
                    },
                  }))
                }
              />
              <NumInput
                label="oy"
                value={typeof origin[1] === "number" ? origin[1] : 0}
                onChange={(v) =>
                  edit((d) => ({
                    ...d,
                    map: {
                      ...d.map,
                      zones: (d.map.zones ?? []).map((z, i) =>
                        i === index ? { ...z, protected_origin: [typeof origin[0] === "number" ? origin[0] : 0, gridSnap(v)] } : z,
                      ),
                    },
                  }))
                }
              />
              <NumInput
                label="w"
                value={typeof extent[0] === "number" ? extent[0] : 0}
                onChange={(v) =>
                  edit((d) => ({
                    ...d,
                    map: {
                      ...d.map,
                      zones: (d.map.zones ?? []).map((z, i) =>
                        i === index ? { ...z, protected_extent: [v, typeof extent[1] === "number" ? extent[1] : 0] } : z,
                      ),
                    },
                  }))
                }
              />
              <NumInput
                label="h"
                value={typeof extent[1] === "number" ? extent[1] : 0}
                onChange={(v) =>
                  edit((d) => ({
                    ...d,
                    map: {
                      ...d.map,
                      zones: (d.map.zones ?? []).map((z, i) =>
                        i === index ? { ...z, protected_extent: [typeof extent[0] === "number" ? extent[0] : 0, v] } : z,
                      ),
                    },
                  }))
                }
              />
              <button
                type="button"
                aria-label={`Remove zone ${zone.id}`}
                onClick={() =>
                  edit((d) => ({ ...d, map: { ...d.map, zones: (d.map.zones ?? []).filter((_, i) => i !== index) } }))
                }
                className="h-[20px] border border-rule text-[11px] text-ink-3 hover:border-red hover:text-red"
              >
                ×
              </button>
            </li>
          )
        })}
      </ul>
      <Button className="mt-1.5" onClick={addZone}>
        Add exclusive zone
      </Button>

      <dl className="mt-2.5 grid grid-cols-3 gap-1.5">
        <Field label="stations" mono>
          {stations.length}
        </Field>
        <Field label="berths" mono>
          {berths.length}
        </Field>
        <Field label="stop lines" mono>
          {stopLines.length}
        </Field>
      </dl>
      <p className="mt-1 text-[10px] text-ink-3">
        Zone protected geometry must be disjoint from every other exclusive zone. Where a traversal needs two
        adjacent resources with no safe berth between them, author one compound zone with <code className="num">members</code>.
      </p>
    </section>
  )
}

function EntityEditor({
  scenario,
  edit,
  gridSnap,
}: {
  scenario: Scenario
  edit: (mutate: (draft: Scenario) => Scenario) => void
  gridSnap: (value: number) => number
}) {
  const robots = scenario.robots
  const starts = scenario.starts
  const tasks = scenario.tasks ?? []
  const faults = scenario.faults ?? []
  const routes = scenario.map.directed_routes ?? []

  return (
    <section className="panel-ticks border border-rule p-2">
      <h3 className="stencil text-[10px] text-ink-2">robots, tasks, routes &amp; faults</h3>

      <p className="stencil mt-2 text-[9px] text-ink-3">robot identities &amp; finite footprints ({robots.length})</p>
      <ul className="mt-1 space-y-1">
        {robots.map((robot, index) => (
          <li key={robot.robot_id} className="grid grid-cols-[1fr_58px_58px_58px_58px] items-end gap-1">
            <input
              value={robot.robot_id}
              aria-label={`Robot ${index + 1} id`}
              onChange={(e) =>
                edit((d) => ({
                  ...d,
                  robots: d.robots.map((r, i) => (i === index ? { ...r, robot_id: e.target.value } : r)),
                }))
              }
              className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
            />
            <NumInput
              label="len m"
              value={robot.footprint.length_m}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  robots: d.robots.map((r, i) => (i === index ? { ...r, footprint: { ...r.footprint, length_m: v } } : r)),
                }))
              }
            />
            <NumInput
              label="wid m"
              value={robot.footprint.width_m}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  robots: d.robots.map((r, i) => (i === index ? { ...r, footprint: { ...r.footprint, width_m: v } } : r)),
                }))
              }
            />
            <NumInput
              label="vmax"
              value={robot.max_linear_mps ?? 0}
              onChange={(v) => edit((d) => ({ ...d, robots: d.robots.map((r, i) => (i === index ? { ...r, max_linear_mps: v } : r)) }))}
            />
            <NumInput
              label="turn r"
              value={robot.footprint.turning_radius_m ?? 0}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  robots: d.robots.map((r, i) =>
                    i === index ? { ...r, footprint: { ...r.footprint, turning_radius_m: v } } : r,
                  ),
                }))
              }
            />
          </li>
        ))}
      </ul>

      <p className="stencil mt-2 text-[9px] text-ink-3">robot starts ({starts.length})</p>
      <ul className="mt-1 space-y-1">
        {starts.map((start, index) => (
          <li key={start.robot_id} className="grid grid-cols-[1fr_58px_58px_58px] items-end gap-1">
            <span className="num truncate text-[11px] text-ink-2">{start.robot_id}</span>
            <NumInput
              label="x"
              value={start.pose.x}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  starts: d.starts.map((s, i) => (i === index ? { ...s, pose: { ...s.pose, x: gridSnap(v) } } : s)),
                }))
              }
            />
            <NumInput
              label="y"
              value={start.pose.y}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  starts: d.starts.map((s, i) => (i === index ? { ...s, pose: { ...s.pose, y: gridSnap(v) } } : s)),
                }))
              }
            />
            <NumInput
              label="θ"
              value={start.pose.theta}
              step={0.1}
              onChange={(v) =>
                edit((d) => ({
                  ...d,
                  starts: d.starts.map((s, i) => (i === index ? { ...s, pose: { ...s.pose, theta: v } } : s)),
                }))
              }
            />
          </li>
        ))}
      </ul>

      <p className="stencil mt-2 text-[9px] text-ink-3">
        tasks ({tasks.length}) · directed routes ({routes.length}) · scheduled faults ({faults.length})
      </p>
      <ul className="mt-1 max-h-[150px] space-y-1 scroll-y">
        {tasks.slice(0, 60).map((task, index) => (
          <li key={task.task_id} className="grid grid-cols-[1fr_1fr_58px_58px] items-end gap-1">
            <input
              value={task.task_id}
              aria-label={`Task ${index + 1} id`}
              onChange={(e) =>
                edit((d) => ({
                  ...d,
                  tasks: (d.tasks ?? []).map((t, i) => (i === index ? { ...t, task_id: e.target.value } : t)),
                }))
              }
              className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
            />
            <span className="num truncate text-[10px] text-ink-3">
              {task.pickup_station_id} → {task.drop_station_id}
            </span>
            <NumInput
              label="prio"
              value={task.priority ?? 0}
              onChange={(v) => edit((d) => ({ ...d, tasks: (d.tasks ?? []).map((t, i) => (i === index ? { ...t, priority: v } : t)) }))}
            />
            <NumInput
              label="kg"
              value={task.weight_kg ?? 0}
              onChange={(v) => edit((d) => ({ ...d, tasks: (d.tasks ?? []).map((t, i) => (i === index ? { ...t, weight_kg: v } : t)) }))}
            />
          </li>
        ))}
      </ul>
      {tasks.length > 60 ? (
        <p className="num mt-1 text-[10px] text-ink-3">
          showing the first 60 of {tasks.length} tasks · the full queue is in the exported JSON
        </p>
      ) : null}

      {faults.length > 0 ? (
        <>
          <p className="stencil mt-2 text-[9px] text-ink-3">scheduled faults</p>
          <ul className="mt-1 space-y-0.5">
            {faults.map((fault) => (
              <li key={fault.fault_id} className="num text-[10px] text-ink-2">
                {fault.fault_id}: {fault.target.kind} on {fault.target.channel}
                {fault.target.sender != null ? ` ${fault.target.sender}→${fault.target.receiver ?? "?"}` : ""}
                <span className="text-ink-3"> — {titleCase(fault.expected_invariant)}</span>
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <p className="mt-2 text-[10px] text-ink-3">
        Faults must be directed. A coordination fault with no sender or receiver is invalid, and the fault laboratory
        refuses to submit one.
      </p>
    </section>
  )
}

function NumInput({
  value,
  onChange,
  label,
  step = 0.1,
}: {
  value: number
  onChange: (value: number) => void
  label?: string
  step?: number
}) {
  return (
    <label className="block">
      {label !== undefined ? <span className="stencil block text-[8px] text-ink-4">{label}</span> : null}
      <input
        type="number"
        step={step}
        value={value}
        aria-label={label}
        onChange={(event) => {
          const next = Number(event.target.value)
          if (Number.isFinite(next)) onChange(next)
        }}
        className="num w-full border border-rule bg-raised px-1 py-0.5 text-[11px] text-ink"
      />
    </label>
  )
}

/* -------------------------------------------------------------------------- */
/* Validation panel                                                           */
/* -------------------------------------------------------------------------- */

export function ValidationPanel({ report }: { report: ValidationReport }) {
  const severityChip = (p: ValidationProblem) =>
    p.severity === "error" ? (
      <Chip tone="red">error</Chip>
    ) : p.severity === "warning" ? (
      <Chip tone="amber">warning</Chip>
    ) : (
      <Chip tone="info">info</Chip>
    )

  return (
    <section className="border-t border-rule" aria-label="Validation" data-testid="validation-panel">
      <div className="flex flex-wrap items-center gap-1.5 px-3 py-2">
        <h3 className="stencil text-[10px] text-ink-2">validation</h3>
        <Chip tone={!report.validated ? "amber" : report.launchable ? "teal" : "red"} data-testid="validation-verdict">
          {!report.validated ? "not validated yet" : report.launchable ? "launchable" : "launch blocked"}
        </Chip>
        <Chip tone="muted">{`${report.counts.error} error · ${report.counts.warning} warning · ${report.counts.info} info`}</Chip>
        {report.expected_failure ? <Chip tone="amber">expected-failure experiment</Chip> : null}
        {report.scenario_digest !== null ? (
          <span className="num text-[10px] text-ink-3">digest {report.scenario_digest.slice(0, 16)}</span>
        ) : null}
      </div>

      {report.expected_failure ? (
        <Strip tone="amber" className="mx-3 mb-2 border">
          <span className="text-[11px]">
            <strong className="font-semibold">Intentionally infeasible workload.</strong>{" "}
            {report.expected_failure_reason ?? "No reason was published."} This scenario may only run as an explicitly
            labelled expected-failure experiment, and it is never eligible for a success comparison.
          </span>
        </Strip>
      ) : null}

      {report.problems.length === 0 ? (
        <p className="px-3 pb-2 text-[11px] text-ink-3">
          {report.validated
            ? "No problems were reported by the validator."
            : "This draft has not been validated against the current schema. Run Validate draft before launching; launch is blocked until validation succeeds."}
        </p>
      ) : (
        <ul className="px-3 pb-2">
          {report.problems.map((problem, index) => (
            <li
              key={`${problem.code}-${problem.path}-${index}`}
              className={`mb-1 border-l-2 pl-2 ${
                problem.severity === "error" ? "border-red" : problem.severity === "warning" ? "border-amber" : "border-rule-strong"
              }`}
            >
              <div className="flex flex-wrap items-center gap-1.5">
                {severityChip(problem)}
                <span className="num text-[10px] text-ink-3">{problem.code}</span>
                {problem.path !== "" ? <span className="num text-[10px] text-ink-4">{problem.path}</span> : null}
              </div>
              <p className="text-[12px] text-ink">{problem.message}</p>
              {problem.hint !== undefined ? <p className="text-[11px] text-ink-3">{problem.hint}</p> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

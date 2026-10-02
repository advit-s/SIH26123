/**
 * Directed communication matrix.
 *
 * Rows are receivers, columns are senders, so a cell reads "<row> hears <column>".
 * `A hears B` and `B hears A` are different facts and are different cells. That
 * asymmetry is the whole reason this view exists: a partitioned one-way channel
 * looks perfectly healthy in the transposed view.
 *
 * Each cell carries three independent signals: a freshness glyph, the measured
 * age of the newest heard message, and the dropped count. Any of them can be
 * unavailable, and each says so.
 */
import type { CommunicationCell, FreshnessClass } from "../../lib/api/types"
import { UNAVAILABLE, age } from "../../lib/format"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"

const FRESHNESS_TONE: Record<FreshnessClass, Tone> = {
  fresh: "teal",
  aging: "amber",
  stale: "red",
  never: "muted",
  unknown: "amber",
}

const FRESHNESS_GLYPH: Record<FreshnessClass, string> = {
  fresh: "●",
  aging: "◐",
  stale: "▲",
  never: "○",
  unknown: "?",
}

const FRESHNESS_LABEL: Record<FreshnessClass, string> = {
  fresh: "fresh",
  aging: "aging",
  stale: "stale",
  never: "never heard",
  unknown: "unknown",
}

/** `row` receives, `column` sends. */
function cellFor(cells: CommunicationCell[], receiver: string, sender: string): CommunicationCell | null {
  return cells.find((c) => c.from === sender && c.to === receiver) ?? null
}

export function CommunicationMatrix({
  cells,
  robotIds,
}: {
  cells: CommunicationCell[]
  robotIds: string[]
}) {
  const select = useViewStore((s) => s.select)

  if (robotIds.length < 2) {
    return (
      <Panel className="min-h-0">
        <PanelHeader title="communication matrix" tone="muted" />
        <PanelBody scroll={false}>
          <p className="p-3 text-[12px] text-ink-3">
            A directed matrix needs at least two agents. This run has {robotIds.length}. With a single robot there
            is no peer channel to observe, and none is being invented.
          </p>
        </PanelBody>
      </Panel>
    )
  }

  const unheard = cells.filter((c) => !c.heard).length

  return (
    <Panel ticks className="min-h-0" aria-label="Directed peer communication matrix">
      <PanelHeader
        title="peer communication"
        subtitle="rows receive · columns send"
        tone={unheard > 0 ? "amber" : "teal"}
        right={
          <Chip tone={unheard > 0 ? "amber" : "teal"}>
            {cells.length} channel{cells.length === 1 ? "" : "s"}
            {unheard > 0 ? ` · ${unheard} silent` : ""}
          </Chip>
        }
      />
      <PanelBody>
        <div className="overflow-x-auto px-2 py-2">
          <table className="border-collapse text-[11px]" data-testid="communication-matrix">
            <caption className="sr-only">
              Directed peer communication. Each cell states whether the row robot hears the column robot, the age of
              the newest heard message, and how many messages were dropped.
            </caption>
            <thead>
              <tr>
                <th scope="col" className="stencil px-1.5 py-1 text-left text-[9px] text-ink-3">
                  hears ↓ / sends →
                </th>
                {robotIds.map((id) => (
                  <th key={id} scope="col" className="num px-1 py-1 text-right text-[10px] text-ink-3">
                    {id}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {robotIds.map((receiver) => (
                <tr key={receiver}>
                  <th scope="row" className="num px-1.5 py-1 text-left text-[10px] font-normal text-ink-2">
                    {receiver}
                  </th>
                  {robotIds.map((sender) => {
                    if (receiver === sender) {
                      return (
                        <td key={sender} className="px-1 py-1 text-center text-[10px] text-ink-4">
                          <span aria-label="own channel, not observed">—</span>
                        </td>
                      )
                    }
                    const cell = cellFor(cells, receiver, sender)
                    if (cell === null) {
                      return (
                        <td key={sender} className="px-1 py-1 text-center text-[10px] text-ink-4">
                          <span aria-label={`no observation published for ${receiver} hearing ${sender}`}>n/r</span>
                        </td>
                      )
                    }
                    const tone = FRESHNESS_TONE[cell.freshness]
                    return (
                      <td
                        key={sender}
                        className={`border px-1 py-1 text-center ${
                          cell.heard ? "border-rule" : "border-red"
                        } ${cell.heard ? "" : "hatch-red"}`}
                        title={
                          cell.note ?? `${receiver} hears ${sender}: ${FRESHNESS_LABEL[cell.freshness]}`
                        }
                      >
                        <button
                          type="button"
                          onClick={() => select("robot", receiver)}
                          className="flex w-full flex-col items-center gap-0.5"
                          aria-label={`${receiver} hears ${sender}: ${
                            cell.heard ? FRESHNESS_LABEL[cell.freshness] : "not heard"
                          }, ${cell.last_rx_age_s === null ? "age unavailable" : `newest ${age(cell.last_rx_age_s)} old`}, ${cell.dropped} dropped`}
                        >
                          <span aria-hidden="true" className={tone === "teal" ? "text-teal" : tone === "amber" ? "text-amber" : tone === "red" ? "text-red" : "text-ink-4"}>
                            {cell.heard ? FRESHNESS_GLYPH[cell.freshness] : "✕"}
                          </span>
                          <span className="num text-[9px] text-ink-3">
                            {cell.last_rx_age_s === null ? UNAVAILABLE : `${cell.last_rx_age_s.toFixed(1)}s`}
                          </span>
                          <span className="num text-[9px] text-ink-4">{`drop ${cell.dropped}`}</span>
                        </button>
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Strip tone="info" className="mx-2 mb-2 border">
          <span className="text-[10px]">
            A lost heartbeat removes permission to assume freshness. It does not free the aisle, and it does not make
            a dropped message disappear from this count.
          </span>
        </Strip>
      </PanelBody>
    </Panel>
  )
}
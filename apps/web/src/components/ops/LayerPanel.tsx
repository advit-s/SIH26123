/**
 * Layer switches and legend.
 *
 * Every layer states, in words, *whose knowledge* it draws. The evaluator-truth
 * layer is the one that matters most here: it is steel blue, it is off by
 * default, and its switch says it is not agent knowledge.
 */
import { Layers } from "lucide-react"
import { useViewStore, type LayerFlags } from "../../lib/view/store"
import { LayerToggle } from "../primitives/Button"
import { Panel, PanelHeader, Strip } from "../primitives/Panel"

const LAYER_COPY: { key: keyof LayerFlags; label: string; description: string; swatch: string }[] = [
  { key: "paint", label: "floor paint", description: "1 m survey grid and metre ticks", swatch: "border-paint" },
  {
    key: "zoneGeometry",
    label: "zone geometry",
    description: "protected extent, entry/exit, stop lines",
    swatch: "border-teal",
  },
  {
    key: "reservations",
    label: "reservations",
    description: "zone authority each agent believes it holds",
    swatch: "border-teal-dim",
  },
  {
    key: "uncertainty",
    label: "pose uncertainty",
    description: "the agent's own declared sigma, at true scale",
    swatch: "border-amber",
  },
  { key: "routes", label: "routes", description: "directed route edges and the selected robot's accepted intent", swatch: "border-paint" },
  {
    key: "observations",
    label: "local observations",
    description: "sensor rays of the selected robot only",
    swatch: "border-teal",
  },
  { key: "conflicts", label: "conflicts", description: "zones with more than one claim", swatch: "border-red" },
  {
    key: "evaluatorTruth",
    label: "evaluator truth",
    description: "the recorder's verdict — not agent knowledge",
    swatch: "border-steel hatch-steel",
  },
]

export function LayerPanel() {
  const layers = useViewStore((s) => s.layers)
  const toggleLayer = useViewStore((s) => s.toggleLayer)

  return (
    <Panel className="min-h-0 shrink-0" ticks>
      <PanelHeader title="layers" tone="info" right={<Layers className="h-[11px] w-[11px] text-ink-3" aria-hidden />} />
      <div className="min-h-0 flex-1 scroll-y py-1">
        {LAYER_COPY.map((layer) => (
          <LayerToggle
            key={layer.key}
            checked={layers[layer.key]}
            onChange={() => toggleLayer(layer.key)}
            label={layer.label}
            description={layer.description}
            swatch={layer.swatch}
          />
        ))}
      </div>
      {layers.evaluatorTruth ? (
        <Strip tone="steel" className="border-t">
          <span className="text-[10px]">
            Evaluator truth is the recorder&rsquo;s independent verdict. It is never fed back into an agent.
          </span>
        </Strip>
      ) : null}
    </Panel>
  )
}

/**
 * Map legend. Rendered as a paint key, not a colour swatch grid: each entry
 * shows the actual mark used on the floor.
 */
export function MapLegend({ robotIds }: { robotIds: string[] }) {
  return (
    <div className="border-t border-rule px-3 py-2">
      <p className="stencil text-[9px] text-ink-3">legend</p>
      <ul className="mt-1 space-y-1">
        <LegendItem mark="border border-teal bg-teal-wash" text="exclusive zone — authority held" />
        <LegendItem mark="hatch-amber border border-amber" text="zone — entry withheld / unknown" />
        <LegendItem mark="hatch-red border border-red" text="zone — contested or occupied" />
        <LegendItem mark="hatch-steel border border-steel" text="evaluator truth overlay" />
        <LegendItem mark="border border-paint" text="obstacle / shelf / wall" />
        <LegendItem mark="border border-ink-3" text="stop line (double bar)" />
        <LegendItem mark="border border-ink-3" text="station and holding berth" />
      </ul>
      {robotIds.length > 0 ? (
        <p className="mt-2 text-[10px] text-ink-3">
          Robot colour is derived from the robot id and is stable for the whole run. The number on each chassis is a
          second, colour-free identifier.
        </p>
      ) : null}
    </div>
  )
}

function LegendItem({ mark, text }: { mark: string; text: string }) {
  return (
    <li className="flex items-center gap-2 text-[10px] text-ink-2">
      <span aria-hidden="true" className={`inline-block h-[9px] w-[16px] shrink-0 ${mark}`} />
      <span>{text}</span>
    </li>
  )
}
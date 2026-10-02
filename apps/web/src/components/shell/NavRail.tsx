/**
 * Navigation rail.
 *
 * Five primary destinations, in the order an operator uses them during an
 * investigation: watch it, change it, compare it, re-read it, check it. Help and
 * research live at the bottom, visually subordinate, because they must not
 * compete with a live run.
 *
 * Keyboard: the rail is a real list of links with `aria-current`, so tab order
 * and screen-reader navigation are native.
 */
import { Activity, Boxes, FlaskConical, HelpCircle, History, Radio, ServerCog, Sun, Moon } from "lucide-react"
import type { ComponentType } from "react"
import { useViewStore, type Destination } from "../../lib/view/store"

interface Dest {
  id: Destination
  label: string
  hint: string
  Icon: ComponentType<{ className?: string; "aria-hidden"?: boolean }>
}

const DESTINATIONS: Dest[] = [
  { id: "operations", label: "Operations", hint: "live map and inspectors", Icon: Radio },
  { id: "scenarios", label: "Scenarios", hint: "author and launch", Icon: Boxes },
  { id: "experiments", label: "Experiments", hint: "paired matrix", Icon: FlaskConical },
  { id: "replays", label: "Replays", hint: "recorded evidence", Icon: History },
  { id: "system", label: "System", hint: "doctor and build", Icon: ServerCog },
]

export function NavRail({ runId, runCount }: { runId: string | null; runCount: number }) {
  const destination = useViewStore((s) => s.destination)
  const navigate = useViewStore((s) => s.navigate)
  const theme = useViewStore((s) => s.theme)
  const toggleTheme = useViewStore((s) => s.toggleTheme)

  return (
    <nav className="flex w-[188px] shrink-0 flex-col border-r border-rule bg-panel" aria-label="Primary">
      <div className="flex items-center gap-2 border-b border-rule px-3 py-3">
        <span aria-hidden="true" className="grid h-[26px] w-[26px] place-items-center border border-teal text-[12px] text-teal">
          <Activity className="h-[14px] w-[14px]" aria-hidden />
        </span>
        <div className="min-w-0">
          <p className="stencil text-[11px] leading-none text-ink">NĪHĀRAMESH</p>
          <p className="mt-0.5 text-[10px] leading-none text-ink-3">fleet coordination console</p>
        </div>
      </div>

      <ul className="min-h-0 flex-1 scroll-y py-1">
        {DESTINATIONS.map((dest) => {
          const active = destination === dest.id
          const Icon = dest.Icon
          return (
            <li key={dest.id}>
              <button
                type="button"
                onClick={() => navigate(dest.id)}
                aria-current={active ? "page" : undefined}
                data-testid={`nav-${dest.id}`}
                className={`flex w-full items-start gap-2 border-l-2 px-3 py-2 text-left ${
                  active
                    ? "border-teal bg-teal-wash text-ink"
                    : "border-transparent text-ink-2 hover:bg-raised hover:text-ink"
                }`}
              >
                <Icon className="mt-[2px] h-[13px] w-[13px] shrink-0" aria-hidden />
                <span className="min-w-0">
                  <span className="block text-[12px] font-medium leading-tight">{dest.label}</span>
                  <span className="block text-[10px] leading-tight text-ink-3">{dest.hint}</span>
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      {/* Run switcher: which artefact is currently open. */}
      <div className="border-t border-rule px-3 py-2">
        <p className="stencil text-[9px] text-ink-3">attached run</p>
        <p className="num mt-0.5 break-all text-[10px] text-ink-2" data-testid="rail-run-id">
          {runId ?? "none"}
        </p>
        <p className="num mt-0.5 text-[10px] text-ink-3">{`${runCount} run${runCount === 1 ? "" : "s"} on disk`}</p>
      </div>

      <div className="flex items-stretch border-t border-rule">
        <button
          type="button"
          onClick={() => navigate("welcome")}
          className="flex flex-1 items-center gap-1.5 px-3 py-2 text-[11px] text-ink-2 hover:bg-raised hover:text-ink"
        >
          <HelpCircle className="h-[13px] w-[13px]" aria-hidden />
          Quick start
        </button>
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "Switch to the light printed view" : "Switch to the dark operations view"}
          className="flex w-[34px] items-center justify-center border-l border-rule text-ink-2 hover:bg-raised hover:text-ink"
        >
          {theme === "dark" ? <Sun className="h-[13px] w-[13px]" aria-hidden /> : <Moon className="h-[13px] w-[13px]" aria-hidden />}
        </button>
      </div>
    </nav>
  )
}
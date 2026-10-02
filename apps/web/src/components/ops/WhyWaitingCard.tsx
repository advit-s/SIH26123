/**
 * "Why waiting" card.
 *
 * The cockpit's central promise: an operator must always be able to name the
 * thing that is blocking a robot, the evidence behind that belief, and the
 * condition that would clear it.
 *
 * The timer note is not decoration. Invariant 4 in AGENTS.md is conservative
 * occupancy: a timer expiring removes *permission to assume*, never physical
 * occupancy. So this card says that in words whenever a timer is involved.
 */
import { Clock, Hand, TimerReset } from "lucide-react"
import type { ReactNode } from "react"
import type { WhyWaiting } from "../../lib/api/types"
import { UNAVAILABLE, age } from "../../lib/format"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { HatchStrip, Strip } from "../primitives/Panel"

export function WhyWaitingCard({ why }: { why: WhyWaiting }) {
  const select = useViewStore((s) => s.select)

  if (!why.blocked) {
    return (
      <div className="px-3 py-2">
        <p className="text-[12px] text-teal">
          <span aria-hidden="true">● </span>
          Not blocked. The agent holds no outstanding coordination requirement.
        </p>
        {why.reason !== "" ? <p className="mt-0.5 text-[11px] text-ink-3">{why.reason}</p> : null}
      </div>
    )
  }

  return (
    <div className="px-3 py-2" data-testid="why-waiting">
      <HatchStrip tone="amber">
        <span>
          <strong className="font-semibold">Blocked.</strong> {why.reason}
        </span>
      </HatchStrip>

      <dl className="mt-2 space-y-1 text-[12px]">
        <Line label="blocking request">
          {why.blocking_request_id !== null ? (
            <span className="num text-ink">{why.blocking_request_id}</span>
          ) : (
            <span className="text-ink-3">{UNAVAILABLE}</span>
          )}
        </Line>
        <Line label="blocking peer">
          {why.blocking_peer !== null ? (
            <button
              type="button"
              onClick={() => select("robot", why.blocking_peer as string)}
              className="num text-teal underline underline-offset-2"
            >
              {why.blocking_peer}
            </button>
          ) : (
            <span className="text-ink-3">{UNAVAILABLE}</span>
          )}
        </Line>
        <Line label="blocking resource">
          {why.blocking_zone_id !== null ? (
            <button
              type="button"
              onClick={() => select("zone", why.blocking_zone_id as string)}
              className="num text-amber underline underline-offset-2"
            >
              {why.blocking_zone_id}
            </button>
          ) : why.blocking_resource !== null ? (
            <span className="num text-ink">{why.blocking_resource}</span>
          ) : (
            <span className="text-ink-3">{UNAVAILABLE}</span>
          )}
        </Line>
        <Line label="evidence age">
          <span className="num">
            {why.evidence_age_s === null ? UNAVAILABLE : age(why.evidence_age_s)}
          </span>
        </Line>
      </dl>

      <div className="mt-2 border border-rule bg-raised px-2 py-1.5">
        <p className="flex items-center gap-1 text-[10px] text-ink-3">
          <Hand className="h-[10px] w-[10px]" aria-hidden />
          recovery condition
        </p>
        <p className="mt-0.5 text-[12px] text-ink">
          {why.recovery_condition ?? "The API published no recovery condition for this block."}
        </p>
      </div>

      {why.timer_expires_permission_only ? (
        <Strip tone="info" className="mt-2 border">
          <span className="flex items-start gap-1.5">
            <TimerReset className="mt-[2px] h-[11px] w-[11px] shrink-0" aria-hidden />
            <span>
              A timer expiry here ends <em>permission to assume</em>. It does not free the aisle: conservative
              occupancy is retained until a release or a recovery completes.
            </span>
          </span>
        </Strip>
      ) : null}

      <p className="mt-1.5 flex items-center gap-1 text-[10px] text-ink-3">
        <Clock className="h-[10px] w-[10px]" aria-hidden />
        from the agent&rsquo;s own state only — the cockpit holds no global truth of its own.
      </p>
    </div>
  )
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="stencil shrink-0 text-[9px] text-ink-3">{label}</dt>
      <dd className="min-w-0 text-right text-[12px]">{children}</dd>
    </div>
  )
}

export function WhyWaitingChip({ why }: { why: WhyWaiting | null }) {
  if (why === null) return null
  if (!why.blocked) return <Chip tone="teal">moving</Chip>
  return <Chip tone="amber" title={why.reason}>waiting</Chip>
}
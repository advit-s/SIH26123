/**
 * Zone inspector.
 *
 * Shows the four states an operator must never confuse:
 *   - **authority**     — who holds the right to be there (or nobody)
 *   - **physical occupancy** — who is actually there, conservatively retained
 *   - **evaluator occupancy** — the recorder's independent verdict (steel blue)
 *   - **entry withheld** — and the exact reason entry is not permitted
 *
 * The request/response table is the protocol made visible: required peers
 * versus responses received, with the outstanding peers named.
 */
import { Lock, Unlock } from "lucide-react"
import type { ZoneInspection } from "../../lib/api/types"
import { UNAVAILABLE, age, heading, metres } from "../../lib/format"
import { useViewStore } from "../../lib/view/store"
import { Chip } from "../primitives/Chip"
import { Field, FieldGrid, Row } from "../primitives/Field"
import { HatchStrip, Panel, PanelBody, PanelHeader, Strip } from "../primitives/Panel"
import type { Tone } from "../primitives/tone"

const AUTHORITY_TONE: Record<ZoneInspection["authority"], Tone> = {
  held: "teal",
  granted_pending_entry: "teal",
  free: "muted",
  contested: "red",
  occupied: "red",
  unknown: "amber",
}

export function ZoneInspector({ zone }: { zone: ZoneInspection }) {
  const select = useViewStore((s) => s.select)

  return (
    <Panel ticks className="min-h-0" aria-label={`Inspector for zone ${zone.zone_id}`}>
      <PanelHeader
        title={<span className="num">{zone.zone_id}</span>}
        subtitle={zone.map_zone?.kind ?? "zone"}
        tone={AUTHORITY_TONE[zone.authority]}
        right={<Chip tone={AUTHORITY_TONE[zone.authority]}>{zone.authority.replace(/_/g, " ")}</Chip>}
      />
      <PanelBody>
        <section aria-label="Authority and occupancy" className="border-b border-rule">
          <FieldGrid cols={3}>
            <Field label="authority holder">
              {zone.authority_holder !== null ? (
                <button
                  type="button"
                  onClick={() => select("robot", zone.authority_holder as string)}
                  className="num text-teal underline underline-offset-2"
                >
                  {zone.authority_holder}
                </button>
              ) : (
                <span className="text-ink-3">nobody</span>
              )}
            </Field>
            <Field label="physical occupancy">
              <span className={zone.physical_occupancy === "occupied" ? "text-red" : "text-ink-2"}>
                {zone.physical_occupancy.replace(/_/g, " ")}
              </span>
            </Field>
            <Field label="occupant">
              {zone.occupant ?? <span className="text-ink-3">{UNAVAILABLE}</span>}
            </Field>
            <Field label="entries" mono>
              {zone.entries}
            </Field>
            <Field label="required peers" mono>
              {zone.required_peers.length === 0 ? <span className="text-ink-3">none</span> : zone.required_peers.join(", ")}
            </Field>
            <Field label="evaluator says occupied">
              {zone.evaluator_occupancy === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <Chip tone="steel" title="The recorder's independent verdict. Not agent knowledge.">
                  {zone.evaluator_occupancy ? "occupied" : "clear"}
                </Chip>
              )}
            </Field>
          </FieldGrid>

          {zone.physical_occupancy === "occupied" && zone.authority_holder === null ? (
            <Strip tone="amber" className="mx-3 mb-2">
              Occupied but ungranted. Occupancy is retained conservatively until a release or a recovery completes —
              a missing release never empties the zone.
            </Strip>
          ) : null}

          {zone.evaluator_occupancy === true && zone.authority === "free" ? (
            <Strip tone="steel" className="mx-3 mb-2">
              Evaluator truth: this zone is occupied while no agent holds authority. That disagreement is a finding,
              not a display glitch.
            </Strip>
          ) : null}
        </section>

        {/* ---------------- geometry ---------------- */}
        <section aria-label="Protected geometry" className="border-b border-rule">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">protected geometry</h3>
          <FieldGrid cols={3}>
            <Field label="origin" mono>
              {zone.protected_origin === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>{zone.protected_origin[0].toFixed(2)}, {zone.protected_origin[1].toFixed(2)}</>
              )}
            </Field>
            <Field label="extent" mono>
              {zone.protected_extent === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>
                  {metres(zone.protected_extent[0])}, {metres(zone.protected_extent[1])}
                </>
              )}
            </Field>
            <Field label="allowed movement">
              {zone.map_zone?.allowed_movement == null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                zone.map_zone.allowed_movement.join(", ")
              )}
            </Field>
            <Field label="entry pose" mono>
              {zone.entry_pose === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>
                  {zone.entry_pose.x.toFixed(2)}, {zone.entry_pose.y.toFixed(2)}{" "}
                  <span className="text-ink-3">{heading(zone.entry_pose.theta)}</span>
                </>
              )}
            </Field>
            <Field label="exit pose" mono>
              {zone.exit_pose === null ? (
                <span className="text-ink-3">{UNAVAILABLE}</span>
              ) : (
                <>
                  {zone.exit_pose.x.toFixed(2)}, {zone.exit_pose.y.toFixed(2)}{" "}
                  <span className="text-ink-3">{heading(zone.exit_pose.theta)}</span>
                </>
              )}
            </Field>
            <Field label="queue berth">
              {zone.queue_berth_id ?? <span className="text-ink-3">none</span>}
            </Field>
          </FieldGrid>
          <Row label="stop line in">{zone.stop_line_in ?? <span className="text-ink-3">none</span>}</Row>
          <Row label="stop line out">{zone.stop_line_out ?? <span className="text-ink-3">none</span>}</Row>
          {zone.map_zone?.description != null ? (
            <p className="border-t border-rule/60 px-3 py-1.5 text-[11px] leading-snug text-ink-2">
              {zone.map_zone.description}
            </p>
          ) : null}
        </section>

        {/* ---------------- entry decision ---------------- */}
        <section aria-label="Entry decision" className="border-b border-rule">
          <h3 className="flex items-center gap-1 px-3 pt-2 text-[9px] text-ink-3 stencil">
            {zone.entry_withheld ? (
              <Lock className="h-[10px] w-[10px]" aria-hidden />
            ) : (
              <Unlock className="h-[10px] w-[10px]" aria-hidden />
            )}
            entry decision
          </h3>
          <div className="px-3 pb-2">
            {zone.entry_withheld ? (
              <HatchStrip tone="amber">
                <span data-testid="zone-entry-withheld">
                  <strong className="font-semibold">Entry withheld.</strong>{" "}
                  {zone.entry_withheld_reason ?? "The API published no reason for withholding entry."}
                </span>
              </HatchStrip>
            ) : (
              <p className="text-[12px] text-teal">
                <span aria-hidden="true">● </span>
                Entry is permitted by the evidence the agent holds.
              </p>
            )}
          </div>
        </section>

        {/* ---------------- requests ---------------- */}
        <section aria-label="Requests" className="min-h-0">
          <h3 className="stencil px-3 pt-2 text-[9px] text-ink-3">
            requests ({zone.requests.length})
          </h3>
          {zone.requests.length === 0 ? (
            <p className="px-3 pb-2 text-[11px] text-ink-3">
              No request has been made for this zone in the retained window.
            </p>
          ) : (
            <ul>
              {zone.requests.map((request) => (
                <li key={request.request_id} className="border-b border-rule/60 px-3 py-2 last:border-b-0">
                  <div className="flex flex-wrap items-center justify-between gap-1.5">
                    <button
                      type="button"
                      onClick={() => select("robot", request.requester)}
                      className="num text-[12px] text-ink underline underline-offset-2"
                    >
                      {request.requester}
                    </button>
                    <div className="flex items-center gap-1.5">
                      {request.cancelled ? <Chip tone="muted">cancelled</Chip> : null}
                      <Chip
                        tone={
                          request.state === "granted"
                            ? "teal"
                            : request.state === "cancelled"
                              ? "muted"
                              : request.state === "refused"
                                ? "red"
                                : "amber"
                        }
                      >
                        {request.state}
                      </Chip>
                    </div>
                  </div>
                  <p className="num mt-0.5 break-all text-[10px] text-ink-3">request {request.request_id}</p>

                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    <span className="stencil text-[9px] text-ink-3">responses</span>
                    <span className="num text-[11px] text-ink" data-testid="zone-response-count">
                      {request.responses_received_count} of {request.responses_required} received
                    </span>
                    {request.outstanding.length > 0 ? (
                      <Chip tone="amber" title="No usable response yet from these peers.">
                        outstanding: {request.outstanding.join(", ")}
                      </Chip>
                    ) : (
                      <Chip tone="teal">all peers responded</Chip>
                    )}
                  </div>

                  {request.responses_received.length > 0 ? (
                    <ul className="mt-1 space-y-0.5">
                      {request.responses_received.map((response) => (
                        <li key={response.peer} className="flex items-center justify-between gap-2 text-[11px]">
                          <span className="flex items-center gap-1.5">
                            <Chip
                              tone={
                                response.response === "grant"
                                  ? "teal"
                                  : response.response === "refuse"
                                    ? "red"
                                    : "muted"
                              }
                            >
                              {response.peer}
                            </Chip>
                            <span className="text-ink-3">{response.response}</span>
                          </span>
                          <span className="num text-[10px] text-ink-3">
                            {response.age_s === null ? "age unavailable" : `${age(response.age_s)} old`}
                            {response.at_seq !== null ? ` · seq ${response.at_seq}` : ""}
                          </span>
                        </li>
                      ))}
                    </ul>
                  ) : null}

                  {request.note !== null ? (
                    <p className="mt-1 text-[11px] text-ink-2">{request.note}</p>
                  ) : null}
                  {request.granted_at_seq !== null ? (
                    <p className="num mt-0.5 text-[10px] text-ink-3">granted at seq {request.granted_at_seq}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
          {zone.entries > 0 ? (
            <p className="px-3 py-1.5 text-[10px] text-ink-3">
              {zone.entries} recorded entr{zone.entries === 1 ? "y" : "ies"} into this zone.
            </p>
          ) : null}
          <p className="px-3 pb-2 text-[10px] text-ink-3">
            Grants are acquired in canonical peer order by every requester, including its own local voter. A late
            grant can never revive a cancelled request.
          </p>
        </section>
      </PanelBody>
    </Panel>
  )
}

export function ZoneRow({ zone }: { zone: ZoneInspection }) {
  return (
    <span className="flex flex-wrap items-center gap-1">
      <span className="num">{zone.zone_id}</span>
      <Chip tone={AUTHORITY_TONE[zone.authority]}>{zone.authority.replace(/_/g, " ")}</Chip>
      {zone.evaluator_occupancy === true ? <Chip tone="steel">evaluator: occupied</Chip> : null}
      {zone.entry_withheld ? <Chip tone="amber">entry withheld</Chip> : null}
      <span className="num text-[10px] text-ink-3">
        {zone.entries} entr{zone.entries === 1 ? "y" : "ies"}
      </span>
    </span>
  )
}
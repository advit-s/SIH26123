/**
 * Execution-mode resolution.
 *
 * The single most important job in this cockpit is making it impossible to
 * confuse these five situations:
 *
 *   1. recorded playback of a finished run
 *   2. a paused simulation harness
 *   3. a deterministic logical-clock run
 *   4. a live run of separate OS processes over real sockets
 *   5. hardware-in-the-loop / physical operation
 *
 * They differ in more than a word, so each gets a distinct *treatment*: a
 * different plate colour, a different paint treatment (hatch / replay band),
 * and a different caption sentence. This module is pure so the mapping can be
 * asserted in tests without rendering.
 */
import type { RunStateSnapshot } from "../api/types"

export type ExecutionKind = "replay" | "paused" | "deterministic" | "processes" | "hardware" | "offline"

export interface ExecutionDescriptor {
  kind: ExecutionKind
  /** Short stencil label rendered on the plate. */
  plate: string
  /** One sentence that says what this mode does and does not mean. */
  caption: string
  tone: "teal" | "amber" | "steel" | "red" | "muted"
  /** Paint treatment, the non-colour signal. */
  paint: "none" | "replay" | "hatch"
  /** True when the world is not advancing under any circumstances. */
  frozen: boolean
}

export function resolveExecution(
  state: RunStateSnapshot | null | undefined,
  options: { physicalActuation: boolean; replaying: boolean },
): ExecutionDescriptor {
  if (state === null || state === undefined) {
    return {
      kind: "offline",
      plate: "NO RUN SELECTED",
      caption: "No run is attached. Pick a run, or open Scenarios to launch one.",
      tone: "muted",
      paint: "none",
      frozen: true,
    }
  }

  const mode = String(state.mode).toLowerCase()

  if (options.replaying || mode === "replay") {
    return {
      kind: "replay",
      plate: "RECORDED PLAYBACK",
      caption: "Replaying recorded events. Nothing is being simulated and no robot is being commanded.",
      tone: "steel",
      paint: "replay",
      frozen: true,
    }
  }

  if (options.physicalActuation) {
    return {
      kind: "hardware",
      plate: "PHYSICAL ACTUATION",
      caption: "Commands reach configured hardware. Stopping this browser does not stop the fleet.",
      tone: "red",
      paint: "hatch",
      frozen: false,
    }
  }

  if (state.paused || String(state.state).toLowerCase() === "paused") {
    return {
      kind: "paused",
      plate: "PAUSED HARNESS",
      caption: "The experiment harness is paused. The logical clock is frozen; robots hold their last commands.",
      tone: "amber",
      paint: "hatch",
      frozen: true,
    }
  }

  if (mode === "deterministic") {
    return {
      kind: "deterministic",
      plate: "DETERMINISTIC",
      caption: "Injected logical clock with seeded streams. Same seed and revision replay the same outcome.",
      tone: "teal",
      paint: "none",
      frozen: false,
    }
  }

  if (mode === "processes") {
    return {
      kind: "processes",
      plate: "LIVE PROCESSES",
      caption: "Independent robot processes exchanging direct peer messages over localhost sockets.",
      tone: "teal",
      paint: "none",
      frozen: false,
    }
  }

  return {
    kind: "offline",
    plate: `UNKNOWN MODE: ${mode}`,
    caption: "The API reported a mode this console does not recognise. Treat every value below as unverified.",
    tone: "amber",
    paint: "none",
    frozen: true,
  }
}
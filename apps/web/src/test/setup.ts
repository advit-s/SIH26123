/**
 * Vitest setup.
 *
 * Two jobs: install the jest-dom matchers, and make the environment honest.
 * jsdom has no WebGL and no WebSocket server, so `WebSocket` is replaced with a
 * stub that immediately reports "not connected" rather than hanging. That keeps
 * stream-dependent components honest in tests: they render their disconnected
 * state instead of pretending to be live.
 */
import "@testing-library/jest-dom/vitest"
import { afterEach, beforeEach, vi } from "vitest"
import { cleanup } from "@testing-library/react"

// jsdom does not implement matchMedia; the app reads prefers-reduced-motion.
if (typeof window.matchMedia !== "function") {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  })
}

class StubWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  readonly url: string
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  close(): void {
    this.onclose?.()
  }
  send(): void {}
  constructor(url: string) {
    this.url = url
  }
}

Object.defineProperty(globalThis, "WebSocket", { writable: true, value: StubWebSocket })

// jsdom has no canvas backend. uPlot asks for a 2D context, so make the absence
// *detectable* (and quiet) rather than letting it print "not implemented" once
// per render. The strip chart feature-detects and shows an honest unavailable
// note; the numeric readouts it sits under are unaffected.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement["getContext"]
}

beforeEach(() => {
  window.localStorage.clear()
  window.location.hash = ""
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})
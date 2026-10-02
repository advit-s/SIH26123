import { defineConfig } from "vitest/config"
import react from "@vitejs/plugin-react"

// Component tests assert behaviour, never snapshots. `jsdom` is used because
// the shell is real DOM; the Pixi canvas is never constructed in unit tests
// (see `src/lib/map/pixiRuntime.ts` guards).
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.tsx", "src/**/*.test.ts"],
    css: false,
    restoreMocks: true,
  },
})

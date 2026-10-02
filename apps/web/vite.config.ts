import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

// The cockpit is a static SPA. Everything it shows comes from the NĪHĀRAMESH
// application API at /api/v1 - the browser never advances robot truth.
const DEV_API_TARGET = "http://127.0.0.1:8100"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      // `/api` -> the FastAPI application API. The WebSocket stream is proxied
      // too so the browser sees one origin and no CORS negotiation is needed.
      "/api": {
        target: DEV_API_TARGET,
        changeOrigin: false,
        ws: true,
      },
    },
  },
  build: {
    target: "es2022",
    sourcemap: true,
    rollupOptions: {
      output: {
        // Pixi and uPlot are large and only needed on canvas routes. Keeping
        // them in their own chunk means the Scenarios/Experiments tables paint
        // without waiting for a WebGL runtime to be parsed.
        manualChunks: {
          pixi: ["pixi.js"],
          charts: ["uplot"],
        },
      },
    },
  },
  optimizeDeps: {
    // The contracts package is workspace TypeScript source, not a built bundle.
    exclude: ["@niharamesh/contracts"],
  },
})

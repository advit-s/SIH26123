import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { App } from "./App"
import "./styles/index.css"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A failed request must surface as an error, never as a silent retry that
      // eventually resolves to zeros. One retry, then the error state is shown.
      retry: 1,
      staleTime: 1000,
      refetchOnWindowFocus: true,
    },
    mutations: { retry: 0 },
  },
})

const container = document.getElementById("root")
if (container === null) throw new Error("#root is missing from index.html")

createRoot(container).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
/**
 * Shared test render helper.
 *
 * Components that own server state must be rendered inside a
 * `QueryClientProvider`, so tests use this rather than the raw `render`.
 * `retry: false` is deliberate: a failing request must surface as an error state
 * in the very first attempt, otherwise a test could pass while the UI was still
 * showing its loading skeleton.
 */
import type { ReactElement } from "react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, type RenderResult } from "@testing-library/react"

export function testQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export function renderWithProviders(ui: ReactElement): RenderResult {
  const client = testQueryClient()
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}
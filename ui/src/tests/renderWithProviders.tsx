import { type ReactNode } from 'react'
import { render } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient } from '@tanstack/react-query'

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
}

interface Options {
  initialPath?: string
  routePath?: string
}

export function renderWithProviders(ui: ReactNode, options: Options = {}) {
  const { initialPath = '/', routePath = '/' } = options
  const client = makeClient()

  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path={routePath} element={ui} />
          {/* catch-all for navigation assertions */}
          <Route path="*" element={<div data-testid="navigated-page" />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

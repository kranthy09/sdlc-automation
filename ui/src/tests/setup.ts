import '@testing-library/jest-dom'
import { setupServer } from 'msw/node'
import { handlers } from './handlers'

// Recharts / layout utilities use ResizeObserver; jsdom doesn't include it
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// TanStack Virtual measures offsetHeight to calculate visible rows.
// In jsdom there is no layout engine so offsetHeight is always 0, which
// means 0 items render. Return a realistic scroll-container height so
// virtualizer tests can find rows.
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
  configurable: true,
  get() {
    return 500
  },
})

export const server = setupServer(...handlers)

beforeAll(() => server.listen({ onUnhandledRequest: 'warn' }))
afterEach(() => server.resetHandlers())
afterAll(() => server.close())

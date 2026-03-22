import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../renderWithProviders'
import ResultsPage from '@/pages/ResultsPage'

describe('ResultsPage', () => {
  const path = '/results/bat_test001'
  const routePath = '/results/:batchId'

  it('renders page title with batch ID', () => {
    renderWithProviders(<ResultsPage />, { initialPath: path, routePath })
    expect(screen.getByText('Fitment Results')).toBeInTheDocument()
    expect(screen.getByText('Batch bat_test001')).toBeInTheDocument()
  })

  it('shows summary cards after load', async () => {
    renderWithProviders(<ResultsPage />, { initialPath: path, routePath })

    // 'Total' card is unique; 'Fit'/'Gap' also appear in filter <option>s
    // so we use getAllByText and assert at least one match
    await waitFor(() => {
      expect(screen.getByText('Total')).toBeInTheDocument()
    })
    expect(screen.getAllByText('Fit').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Partial Fit').length).toBeGreaterThan(0)
    expect(screen.getAllByText('Gap').length).toBeGreaterThan(0)
  })

  it('shows results table rows', async () => {
    renderWithProviders(<ResultsPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByText('REQ-AP-001')).toBeInTheDocument()
    })
    expect(screen.getByText('REQ-AP-002')).toBeInTheDocument()
    expect(screen.getByText('REQ-GL-001')).toBeInTheDocument()
  })

  it('expands row evidence panel on click', async () => {
    renderWithProviders(<ResultsPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByText('REQ-AP-001')).toBeInTheDocument()
    })

    // Click the row to expand
    await userEvent.click(screen.getByText('Three-way matching for AP invoices'))
    expect(await screen.findByText('AI Rationale')).toBeInTheDocument()
    expect(screen.getByText('D365 Capability')).toBeInTheDocument()
  })

  it('shows Download Excel button', async () => {
    renderWithProviders(<ResultsPage />, { initialPath: path, routePath })
    expect(screen.getByRole('button', { name: /download excel/i })).toBeInTheDocument()
  })
})

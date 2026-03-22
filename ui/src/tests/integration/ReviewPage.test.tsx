import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../renderWithProviders'
import ReviewPage from '@/pages/ReviewPage'

describe('ReviewPage', () => {
  const path = '/review/bat_test001'
  const routePath = '/review/:batchId'

  it('renders page title', () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })
    expect(screen.getByText('Human Review Queue')).toBeInTheDocument()
  })

  it('shows review item after load', async () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(
        screen.getByText('Custom vendor scorecard with weighted multi-factor rating'),
      ).toBeInTheDocument()
    })
  })

  it('shows Approve, Override, Flag buttons', async () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /approve/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /override/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /flag/i })).toBeInTheDocument()
  })

  it('shows override form when Override is clicked', async () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /override/i })).toBeInTheDocument()
    })
    await userEvent.click(screen.getByRole('button', { name: /override/i }))

    expect(screen.getByText('Override classification')).toBeInTheDocument()
    expect(screen.getByPlaceholderText(/Why does the AI/)).toBeInTheDocument()
  })

  it('shows evidence accordion', async () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByText(/Evidence & capabilities/)).toBeInTheDocument()
    })
    await userEvent.click(screen.getByText(/Evidence & capabilities/))
    expect(await screen.findByText('Top D365 capabilities')).toBeInTheDocument()
  })

  it('shows review progress indicator', async () => {
    renderWithProviders(<ReviewPage />, { initialPath: path, routePath })

    await waitFor(() => {
      expect(screen.getByText(/0 of 1 reviewed/)).toBeInTheDocument()
    })
  })
})

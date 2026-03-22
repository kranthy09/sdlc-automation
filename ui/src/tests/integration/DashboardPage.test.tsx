import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '../renderWithProviders'
import DashboardPage from '@/pages/DashboardPage'

describe('DashboardPage', () => {
  it('renders page title', () => {
    renderWithProviders(<DashboardPage />, { initialPath: '/dashboard', routePath: '/dashboard' })
    expect(screen.getByText('Dashboard')).toBeInTheDocument()
  })

  it('shows batch history after load', async () => {
    renderWithProviders(<DashboardPage />, { initialPath: '/dashboard', routePath: '/dashboard' })

    await waitFor(() => {
      expect(screen.getByText('DE_AP_Wave1.xlsx')).toBeInTheDocument()
    })
    expect(screen.getByText('FR_GL_Wave2.xlsx')).toBeInTheDocument()
  })

  it('shows aggregate metrics', async () => {
    renderWithProviders(<DashboardPage />, { initialPath: '/dashboard', routePath: '/dashboard' })

    await waitFor(() => {
      expect(screen.getByText('Total requirements')).toBeInTheDocument()
    })
    expect(screen.getByText('Overall fit rate')).toBeInTheDocument()
    expect(screen.getByText('Gap rate')).toBeInTheDocument()
  })

  it('has New analysis button', () => {
    renderWithProviders(<DashboardPage />, { initialPath: '/dashboard', routePath: '/dashboard' })
    expect(screen.getByRole('button', { name: /new analysis/i })).toBeInTheDocument()
  })
})

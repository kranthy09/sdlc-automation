import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../renderWithProviders'
import UploadPage from '@/pages/UploadPage'

describe('UploadPage', () => {
  it('renders drop zone and config form', () => {
    renderWithProviders(<UploadPage />, { initialPath: '/upload', routePath: '/upload' })

    expect(screen.getByText('Upload Requirements')).toBeInTheDocument()
    expect(screen.getByText(/Drop file here/)).toBeInTheDocument()
    expect(screen.getByText('Analysis configuration')).toBeInTheDocument()
  })

  it('Start analysis button is disabled with no file', () => {
    renderWithProviders(<UploadPage />, { initialPath: '/upload', routePath: '/upload' })

    const btn = screen.getByRole('button', { name: /start analysis/i })
    expect(btn).toBeDisabled()
  })

  it('shows file name after drop', async () => {
    renderWithProviders(<UploadPage />, { initialPath: '/upload', routePath: '/upload' })

    const file = new File(['content'], 'requirements.xlsx', {
      type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    })
    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    await userEvent.upload(input, file)

    expect(await screen.findByText('requirements.xlsx')).toBeInTheDocument()
  })

  it('shows advanced overrides when toggled', async () => {
    renderWithProviders(<UploadPage />, { initialPath: '/upload', routePath: '/upload' })

    await userEvent.click(screen.getByText('Advanced overrides'))
    expect(screen.getByText(/Fit confidence threshold/)).toBeInTheDocument()
    expect(screen.getByText(/Auto-approve/)).toBeInTheDocument()
  })

  it('wave input accepts numeric values', async () => {
    renderWithProviders(<UploadPage />, { initialPath: '/upload', routePath: '/upload' })

    const waveInput = screen.getByDisplayValue('1')
    await userEvent.tripleClick(waveInput)
    await userEvent.keyboard('3')

    expect(waveInput).toHaveValue(3)
  })
})

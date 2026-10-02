import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const forgot = vi.fn()
vi.mock('../../../generated/sdk.gen', () => ({
  forgotPasswordAuthForgotPasswordPost: (...args: unknown[]) => forgot(...args),
}))

const { ForgotPasswordPage } = await import('./ForgotPasswordPage')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

const SENT = 'If an account exists for that address, a reset link is on its way'

afterEach(cleanup)

function renderPage() {
  return render(
    <ThemeProvider>
      <ForgotPasswordPage />
    </ThemeProvider>,
  )
}

function submit(email = 'someone@example.com') {
  fireEvent.change(screen.getByLabelText('Email'), { target: { value: email } })
  fireEvent.click(screen.getByRole('button', { name: 'Send reset link' }))
}

describe('ForgotPasswordPage', () => {
  it('confirms only a successful request', async () => {
    forgot.mockResolvedValue({ data: {} })
    renderPage()

    submit()

    expect(await screen.findByText(SENT, { exact: false })).toBeTruthy()
  })

  it('shows an error and keeps the form when the request fails', async () => {
    forgot.mockResolvedValue({ data: undefined, error: { message: 'boom' } })
    renderPage()

    submit()

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText(SENT, { exact: false })).toBeNull()
    // The form is still there to retry, with the address intact.
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe(
      'someone@example.com',
    )
  })

  it('shows an error when the request rejects outright', async () => {
    forgot.mockRejectedValue(new Error('offline'))
    renderPage()

    submit()

    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(screen.queryByText(SENT, { exact: false })).toBeNull()
  })
})
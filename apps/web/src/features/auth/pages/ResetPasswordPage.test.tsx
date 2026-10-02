import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const reset = vi.fn()
vi.mock('../../../generated/sdk.gen', () => ({
  resetPasswordAuthResetPasswordPost: (...args: unknown[]) => reset(...args),
}))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: React.ReactNode }) => children,
}))

const { ResetPasswordPage } = await import('./ResetPasswordPage')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

const OFFLINE = 'Could not reach the server'

afterEach(cleanup)

describe('ResetPasswordPage', () => {
  it('a rejected request shows an error and keeps the new password', async () => {
    reset.mockRejectedValue(new Error('offline'))
    render(
      <ThemeProvider>
        <ResetPasswordPage token="tok" />
      </ThemeProvider>,
    )

    fireEvent.change(screen.getByLabelText('New password'), {
      target: { value: 'brandnewpass' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Reset password' }))

    expect(await screen.findByText(OFFLINE, { exact: false })).toBeTruthy()
    expect((screen.getByLabelText('New password') as HTMLInputElement).value).toBe(
      'brandnewpass',
    )
    // Busy is released, so the reset can be retried without retyping.
    expect(
      (screen.getByRole('button', { name: 'Reset password' }) as HTMLButtonElement).disabled,
    ).toBe(false)
  })
})
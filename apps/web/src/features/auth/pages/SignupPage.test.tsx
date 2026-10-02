import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const signup = vi.fn()
vi.mock('../../../generated/sdk.gen', () => ({
  signupAuthSignupPost: (...args: unknown[]) => signup(...args),
}))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: React.ReactNode }) => children,
}))

const { SignupPage } = await import('./SignupPage')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

const OFFLINE = 'Could not reach the server'

afterEach(cleanup)

describe('SignupPage', () => {
  it('a rejected request shows an error and keeps what was typed', async () => {
    signup.mockRejectedValue(new Error('offline'))
    render(
      <ThemeProvider>
        <SignupPage />
      </ThemeProvider>,
    )

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'new@example.com' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'longenough1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign up' }))

    expect(await screen.findByText(OFFLINE, { exact: false })).toBeTruthy()
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe('new@example.com')
    expect((screen.getByLabelText('Password') as HTMLInputElement).value).toBe('longenough1')
  })
})
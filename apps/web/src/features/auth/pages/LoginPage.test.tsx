import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const login = vi.fn()
vi.mock('../../../generated/sdk.gen', () => ({
  loginAuthLoginPost: (...args: unknown[]) => login(...args),
}))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
  Link: ({ children }: { children: React.ReactNode }) => children,
}))

const { LoginPage } = await import('./LoginPage')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

const OFFLINE = 'Could not reach the server'

afterEach(cleanup)

describe('LoginPage', () => {
  it('a rejected request shows an error and keeps what was typed', async () => {
    login.mockRejectedValue(new Error('offline'))
    render(
      <ThemeProvider>
        <LoginPage />
      </ThemeProvider>,
    )

    fireEvent.change(screen.getByLabelText('Email'), {
      target: { value: 'someone@example.com' },
    })
    fireEvent.change(screen.getByLabelText('Password'), {
      target: { value: 'hunter2hunter2' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByText(OFFLINE, { exact: false })).toBeTruthy()
    expect((screen.getByLabelText('Email') as HTMLInputElement).value).toBe(
      'someone@example.com',
    )
    expect((screen.getByLabelText('Password') as HTMLInputElement).value).toBe(
      'hunter2hunter2',
    )
    // Busy is released, so the user can just press Sign in again.
    expect((screen.getByRole('button', { name: 'Sign in' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  })
})
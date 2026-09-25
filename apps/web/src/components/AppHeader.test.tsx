import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

vi.mock('../features/auth/hooks/useMe', () => ({
  useMe: () => ({ data: { email: 'demo@example.com', role: 'user' } }),
}))
vi.mock('../features/chat/hooks/useQuota', () => ({
  useQuota: () => ({
    data: {
      remaining_5h: 40,
      limit_5h: 100,
      reset_at_5h: '2026-10-01T00:00:00Z',
      remaining_month: 300,
      limit_month: 1000,
      reset_at_month: '2026-10-01T00:00:00Z',
      blocked: false,
    },
  }),
}))
vi.mock('./lib/auth', () => ({ logout: vi.fn(async () => undefined) }))
vi.mock('./lib/queryClient', () => ({ queryClient: { clear: vi.fn() } }))

const { ProfileMenu } = await import('./ProfileMenu')
const { AppHeader } = await import('./AppHeader')
const { ThemeProvider } = await import('./ThemeToggle')

Element.prototype.scrollIntoView = () => undefined
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => undefined
Element.prototype.releasePointerCapture = () => undefined

afterEach(cleanup)

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme')
  window.localStorage.clear()
})

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider>{ui}</ThemeProvider>)
}

async function openProfileMenu() {
  const trigger = screen.getByRole('button', { name: 'Profile menu' })
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false })
  return screen.findByRole('menu')
}

describe('ProfileMenu', () => {
  it('has no theme items but keeps the quota block', async () => {
    renderWithTheme(<ProfileMenu />)
    const menu = await openProfileMenu()

    expect(menu.textContent).not.toMatch(/Light/)
    expect(menu.textContent).not.toMatch(/Dark/)
    expect(menu.textContent).not.toMatch(/System/)
    expect(screen.queryByRole('menuitemradio')).toBeNull()
    expect(screen.queryByRole('button', { name: /Switch to .* theme/ })).toBeNull()

    expect(menu.textContent).toContain('Credits')
    expect(screen.getByRole('group', { name: '5h quota' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'month quota' })).toBeTruthy()
  })
})

describe('theme toggle', () => {
  it('sits in the app header and flips data-theme', async () => {
    renderWithTheme(<AppHeader />)

    const toggle = await waitFor(() => screen.getByRole('button', { name: /Switch to .* theme/ }))
    expect(toggle.closest('header')).toBeTruthy()

    const before = document.documentElement.getAttribute('data-theme')
    fireEvent.click(toggle)
    await waitFor(() =>
      expect(document.documentElement.getAttribute('data-theme')).not.toBe(before),
    )
    expect(['light', 'dark']).toContain(document.documentElement.getAttribute('data-theme'))
  })
})

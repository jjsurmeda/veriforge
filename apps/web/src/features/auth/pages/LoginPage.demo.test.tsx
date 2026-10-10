import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  startDemo: vi.fn(),
  login: vi.fn(),
  navigate: vi.fn(),
  setAccessToken: vi.fn(),
  limits: vi.fn(),
}))

vi.mock('../../../generated/sdk.gen', () => ({
  startDemoAuthDemoPost: mocks.startDemo,
  loginAuthLoginPost: mocks.login,
  demoLimitsAuthDemoLimitsGet: mocks.limits,
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents: [], starter_questions: [] } })),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async () => ({ data: {} })),
  deleteDocumentDocumentsDocumentIdDelete: vi.fn(async () => ({ data: undefined })),
  reindexDocumentDocumentsDocumentIdReindex: vi.fn(async () => ({ data: undefined })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(async () => ({ data: undefined })),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
  // `useNavigate()` returns the navigate function itself, not an object
  // holding one. Returning an object here made the component's
  // `navigate({ to: '/' })` throw, which its own catch turned into an error
  // message — a green test for the wrong reason.
  useNavigate: () => mocks.navigate,
}))

vi.mock('../../../lib/auth', () => ({ setAccessToken: mocks.setAccessToken }))

const { LoginPage } = await import('./LoginPage')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ThemeProvider>
        <LoginPage />
      </ThemeProvider>
    </QueryClientProvider>,
  )
}

function demoToken() {
  return {
    access_token: 'demo-token',
    user: {
      id: 'u1',
      email: 'demo-ab12@demo.veriforge.test',
      role: 'demo',
      plan: { name: 'demo', credits_5h: 12_000, credits_month: 400_000 },
    },
  }
}

describe('Try the demo', () => {
  it('starts an ephemeral demo and signs in with the returned token', async () => {
    mocks.startDemo.mockResolvedValue({ data: demoToken() })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => expect(mocks.setAccessToken).toHaveBeenCalledWith('demo-token'))
    // Two separate awaits: the token is set before the navigation is issued,
    // so waiting on the first does not prove the second happened yet.
    await waitFor(() => expect(mocks.navigate).toHaveBeenCalled())
    expect(mocks.navigate.mock.calls[0]?.[0]).toMatchObject({ to: '/' })
  })

  it('says something useful when the per-IP limit refuses it', async () => {
    // "Try again" is the one thing that does not help here, and it is what
    // KI-23 is about: the message has to name the actual obstacle.
    mocks.startDemo.mockResolvedValue({
      error: { error_code: 'rate_limited', message: 'Too many attempts.' },
    })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('this network')
    })
    expect(mocks.setAccessToken).not.toHaveBeenCalled()
  })

  it('says the demo is not set up when the plan is missing', async () => {
    mocks.startDemo.mockResolvedValue({
      error: { error_code: 'demo_unavailable', message: 'run `make seed-demo`' },
    })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toContain('not set up')
    })
  })

  it('says the demo is not available when the kill switch is off', async () => {
    // KI-63: DEMO_ENABLED defaults to false, so on any deployment that has
    // not turned it on this button is the first thing a visitor presses. A
    // generic "could not start the demo" reads as a broken product, not a
    // switched-off one.
    mocks.startDemo.mockResolvedValue({
      error: { error_code: 'demo_disabled', message: 'The demo is not available on this deployment.' },
    })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('The demo is not available right now.')
    })
    expect(mocks.setAccessToken).not.toHaveBeenCalled()
    // The form is untouched: a visitor who came to sign in must still be able
    // to.
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
  })

  it('says the demo is full for today when the daily cap is spent', async () => {
    mocks.startDemo.mockResolvedValue({
      error: { error_code: 'demo_capacity', message: '2 demo account(s) already created in the last 24h; the cap is 2' },
    })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => {
      expect(screen.getByRole('alert').textContent).toBe('The demo is full for today. Try again tomorrow.')
    })
    expect(mocks.setAccessToken).not.toHaveBeenCalled()
  })

  it('leaves the sign-in form alone when the demo fails', async () => {
    mocks.startDemo.mockResolvedValue({ error: { error_code: 'internal_error' } })
    renderPage()

    await screen.getByRole('button', { name: 'Try the demo' }).click()

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    // Sign in is still there and still enabled: a failed demo must not lock a
    // visitor out of the page they came to.
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeTruthy()
  })

  it('lists what the demo shows, so a visitor knows before starting', () => {
    renderPage()
    // The tour is on the login page as well as in the demo chat, built from
    // the same list, so the two cannot disagree.
    expect(screen.getByText('What the demo shows')).toBeTruthy()
    expect(screen.getByText('A cited answer.')).toBeTruthy()
    expect(screen.getByText('An abstention.')).toBeTruthy()
  })
})
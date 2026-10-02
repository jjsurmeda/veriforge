import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const me = { email: 'someone@example.com', role: 'user' as 'user' | 'admin' }
type SettingsPatchBody = { thresholds: { sufficient_abstain: Record<string, number> } }
const patchSettings = vi.fn(async (_args: { body: SettingsPatchBody }) => ({ data: {} }))
const providersGet = vi.fn(async () => ({ data: [] as unknown[] }))
const emptyOk = async () => ({ data: [] })
const emptySettings = async () => ({ data: { data: {}, version: 1 } })

vi.mock('../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  activeSettingsAdminSettingsGet: vi.fn(emptySettings),
  updateSettingsAdminSettingsPatch: patchSettings,
  providersAdminProvidersGet: providersGet,
  modelsAdminModelsGet: vi.fn(emptyOk),
  rolesAdminRolesGet: vi.fn(emptyOk),
  settingsVersionsAdminSettingsVersionsGet: vi.fn(emptyOk),
  plansAdminPlansGet: vi.fn(emptyOk),
  usersAdminUsersGet: vi.fn(emptyOk),
  auditAdminAuditGet: vi.fn(emptyOk),
  listDocumentsLibraryDocumentsGet: vi.fn(emptyOk),
}))

const { AdminPage } = await import('./AdminPage')

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <AdminPage />
    </QueryClientProvider>,
  )
}

afterEach(cleanup)

describe('admin route guard', () => {
  it('a non-admin cannot reach the page or the Shared library tab', async () => {
    me.role = 'user'
    renderPage()

    expect(await screen.findByText('Administrator access required.')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Shared library' })).toBeNull()
  })
})

describe('failed reads', () => {
  it('a failed provider query shows an error with retry, not an empty list', async () => {
    me.role = 'admin'
    providersGet.mockResolvedValueOnce({
      data: undefined,
      error: { message: 'boom' },
    } as never)
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Providers' }))

    expect(await screen.findByText('Providers could not be loaded.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy()
    // Retry re-issues the request rather than leaving an empty table.
    providersGet.mockResolvedValueOnce({ data: [] })
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(providersGet.mock.calls.length).toBeGreaterThan(1))
    await waitFor(() => expect(screen.queryByText('Providers could not be loaded.')).toBeNull())
  })
})

describe('sufficient thresholds', () => {
  it('the abstention threshold is editable and saved per engine (AD-4)', async () => {
    me.role = 'admin'
    renderPage()

    const field = await screen.findByLabelText('Abstention threshold')
    fireEvent.change(field, { target: { value: '0.42' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create version' }))

    await waitFor(() => expect(patchSettings).toHaveBeenCalled())
    const { thresholds } = patchSettings.mock.calls[0]![0].body
    expect(thresholds.sufficient_abstain).toEqual({ jev: 0.42, fallback: 0.42 })
  })
})

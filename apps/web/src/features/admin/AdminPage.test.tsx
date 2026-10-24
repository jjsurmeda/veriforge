import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const me = { email: 'someone@example.com', role: 'user' as 'user' | 'admin' }
type SettingsPatchBody = { thresholds: { evidence_floor: Record<string, number> } }
const patchSettings = vi.fn(async (_args: { body: SettingsPatchBody }) => ({ data: {} }))
const providersGet = vi.fn(async () => ({ data: [] as unknown[] }))
const rerankerList = [
  { id: 'jev', label: 'Jev', kind: 'decision-model', calibrated: true, cost_per_1k_queries_usd: 1.16, cost_note: '', is_default: true, key_present: true },
  { id: 'cohere', label: 'Cohere', kind: 'api', calibrated: false, cost_per_1k_queries_usd: 2, cost_note: '', is_default: false, key_present: true },
]
const emptyOk = async () => ({ data: [] })
const emptySettings = async () => ({ data: { data: {}, version: 1 } })

vi.mock('../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  activeSettingsAdminSettingsGet: vi.fn(emptySettings),
  updateSettingsAdminSettingsPatch: patchSettings,
  providersAdminProvidersGet: providersGet,
  modelsAdminModelsGet: vi.fn(emptyOk),
  listRerankersRerankersGet: vi.fn(async () => ({ data: rerankerList })),
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

describe('gate threshold', () => {
  it('the evidence_floor floor is editable and saved per engine (AD-4)', async () => {
    me.role = 'admin'
    renderPage()

    const field = await screen.findByLabelText('Gate floor (mean top-3)')
    fireEvent.change(field, { target: { value: '0.42' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create version' }))

    await waitFor(() => expect(patchSettings).toHaveBeenCalled())
    const { thresholds } = patchSettings.mock.calls[0]![0].body
    expect(thresholds.evidence_floor).toEqual({ jev: 0.42, fallback: 0.42 })
  })
})

describe('reranker picker and benchmarks', () => {
  it('lists /rerankers and saves the choice to retrieval.reranker', async () => {
    me.role = 'admin'
    patchSettings.mockClear()
    renderPage()

    const picker = await screen.findByLabelText('Reranker')
    await waitFor(() => expect(screen.getByRole('option', { name: 'Cohere' })).toBeTruthy())
    fireEvent.change(picker, { target: { value: 'cohere' } })
    expect(screen.getByText(/not calibrated, \$2\/1k queries/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Create version' }))

    await waitFor(() => expect(patchSettings).toHaveBeenCalled())
    const body = patchSettings.mock.calls[0]![0].body as unknown as { retrieval: { reranker?: string } }
    expect(body.retrieval.reranker).toBe('cohere')
  })

  it('renders the stored benchmark numbers with their source run', async () => {
    me.role = 'admin'
    renderPage()

    fireEvent.click(await screen.findByRole('button', { name: 'Benchmarks' }))
    expect(await screen.findByText(/20261018-195514\.json/)).toBeTruthy()
    expect(screen.getByText('31/33 (0.939)')).toBeTruthy()
    expect(screen.getByText(/openai\/gpt-4o-mini/)).toBeTruthy()
  })

  it('a non-admin gets a way home', async () => {
    me.role = 'user'
    renderPage()
    expect((await screen.findByRole('link', { name: 'Back to chats' })).getAttribute('href')).toBe('/')
  })
})

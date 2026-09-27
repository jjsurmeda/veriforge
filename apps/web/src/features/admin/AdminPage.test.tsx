import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const me = { email: 'someone@example.com', role: 'user' as 'user' | 'admin' }
type SettingsPatchBody = { thresholds: { sufficient_abstain: Record<string, number> } }
const patchSettings = vi.fn(async (_args: { body: SettingsPatchBody }) => ({ data: {} }))

vi.mock('../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  activeSettingsAdminSettingsGet: vi.fn(async () => ({ data: { data: {} } })),
  updateSettingsAdminSettingsPatch: patchSettings,
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

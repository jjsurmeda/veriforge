import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

const me = { email: 'someone@example.com', role: 'user' as 'user' | 'admin' }

vi.mock('../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  activeSettingsAdminSettingsGet: vi.fn(async () => ({ data: { data: {} } })),
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

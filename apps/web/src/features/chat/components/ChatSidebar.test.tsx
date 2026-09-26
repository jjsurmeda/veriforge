import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

const me = { email: 'demo@example.com', role: 'user' as 'user' | 'admin' }

vi.mock('../../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  listChatsChatsGet: vi.fn(async () => ({
    data: [
      { id: 'c1', title: 'Pinned chat', pinned: true, model_id: null, starter_questions: [] },
      { id: 'c2', title: 'Other chat', pinned: false, model_id: null, starter_questions: [] },
    ],
  })),
  createChatChatsPost: vi.fn(async () => ({ data: { id: 'c1' } })),
  deleteChatChatsChatIdDelete: vi.fn(async () => ({ data: undefined })),
  patchChatChatsChatIdPatch: vi.fn(async () => ({ data: undefined })),
}))

const { ChatSidebar } = await import('./ChatSidebar')
const { TooltipProvider } = await import('../../../components/ui/primitives')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

function renderSidebar() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <ThemeProvider>
      <TooltipProvider>
        <QueryClientProvider client={client}>
          <ChatSidebar currentChatId="c1" />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>,
  )
}

afterEach(cleanup)
beforeEach(() => window.localStorage.clear())

describe('ChatSidebar', () => {
  it('renders only chat rows and the header controls', async () => {
    renderSidebar()

    await waitFor(() => expect(screen.getByText('Pinned chat')).toBeTruthy())
    expect(screen.getByText('Other chat')).toBeTruthy()
    expect(screen.getByText('Pinned')).toBeTruthy()
    expect(screen.getAllByRole('button', { name: 'New chat' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Search chats' })).toHaveLength(1)
  })

  it('has no Library section and no source UI, even on the active chat', async () => {
    renderSidebar()

    await waitFor(() => expect(screen.getByText('Pinned chat')).toBeTruthy())
    expect(screen.queryByRole('button', { name: /^Library$/ })).toBeNull()
    expect(screen.queryByText('Library')).toBeNull()
    expect(screen.queryByText('Include Library')).toBeNull()
    expect(screen.queryByRole('button', { name: /Add sources/ })).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
  })

  it('has no open-section state to remember', async () => {
    renderSidebar()
    await waitFor(() => expect(screen.getByText('Pinned chat')).toBeTruthy())
    expect(window.localStorage.getItem('veriforge-sidebar-section')).toBeNull()
  })
})

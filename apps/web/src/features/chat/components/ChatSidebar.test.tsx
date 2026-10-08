import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

const me = { email: 'demo@example.com', role: 'user' as 'user' | 'admin' }

let chatsFail = false

vi.mock('../../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  listChatsChatsGet: vi.fn(async () =>
    chatsFail
      ? { error: { error_code: 'server_error', message: 'boom' } }
      : {
          data: [
            { id: 'c1', title: 'Pinned chat', pinned: true, model_id: null, starter_questions: [] },
            { id: 'c2', title: 'Other chat', pinned: false, model_id: null, starter_questions: [] },
          ],
        },
  ),
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
beforeEach(() => {
  window.localStorage.clear()
  chatsFail = false
})

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

  // Item 6: "No chats yet." on a failed read claims the account is empty.
  it('a failed chat list is an error, never "No chats yet."', async () => {
    chatsFail = true
    renderSidebar()

    expect(await screen.findByText('Your chats could not be read.')).toBeTruthy()
    expect(screen.queryByText('No chats yet.')).toBeNull()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('an empty account still gets "No chats yet."', async () => {
    const { listChatsChatsGet } = await import('../../../generated/sdk.gen')
    vi.mocked(listChatsChatsGet).mockResolvedValueOnce({ data: [] } as never)
    renderSidebar()

    expect(await screen.findByText('No chats yet.')).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

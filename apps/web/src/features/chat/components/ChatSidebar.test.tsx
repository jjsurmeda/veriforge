import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => vi.fn(),
}))

const me = { email: 'demo@example.com', role: 'user' as 'user' | 'admin' }

vi.mock('../../../generated/sdk.gen', () => ({
  meMeGet: vi.fn(async () => ({ data: me })),
  listChatsChatsGet: vi.fn(async () => ({ data: [] })),
  createChatChatsPost: vi.fn(async () => ({ data: { id: 'c1' } })),
  deleteChatChatsChatIdDelete: vi.fn(async () => ({ data: undefined })),
  patchChatChatsChatIdPatch: vi.fn(async () => ({ data: undefined })),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async () => ({ data: undefined })),
  getLibraryLibraryGet: vi.fn(async () => ({
    data: { documents: [], starter_questions: [] },
  })),
  uploadLibraryDocumentLibraryDocumentsPost: vi.fn(async () => ({ data: undefined })),
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
          <ChatSidebar currentChatId={null} />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>,
  )
}

const librarySection = () => screen.getByRole('button', { name: /^Library$/ })
const chatsSection = () => screen.getByRole('button', { name: /^Chats$/ })
const chatsBody = () => screen.queryByText('No chats yet.')
const libraryBody = () => screen.queryByText('Drop files or browse')

describe('ChatSidebar section accordion', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  afterEach(cleanup)

  it('opens Chats and collapses Library when the Chats header is clicked', async () => {
    renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())

    expect(chatsBody()).toBeTruthy()
    expect(libraryBody()).toBeNull()

    fireEvent.click(librarySection())
    await waitFor(() => expect(libraryBody()).toBeTruthy())
    expect(chatsBody()).toBeNull()

    fireEvent.click(chatsSection())
    await waitFor(() => expect(chatsBody()).toBeTruthy())
    expect(libraryBody()).toBeNull()
  })

  it('marks exactly one section as expanded at a time', async () => {
    renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())
    expect(chatsSection().getAttribute('aria-expanded')).toBe('true')
    expect(librarySection().getAttribute('aria-expanded')).toBe('false')

    fireEvent.click(librarySection())
    await waitFor(() => expect(libraryBody()).toBeTruthy())
    expect(chatsSection().getAttribute('aria-expanded')).toBe('false')
    expect(librarySection().getAttribute('aria-expanded')).toBe('true')
  })

  it('offers exactly one search and one new-chat control', async () => {
    renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())
    expect(screen.getAllByRole('button', { name: 'New chat' })).toHaveLength(1)
    expect(screen.getAllByRole('button', { name: 'Search chats' })).toHaveLength(1)
  })

  it('remembers the open section across mounts', async () => {
    const first = renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())
    fireEvent.click(librarySection())
    await waitFor(() => expect(screen.getByText('Drop files or browse')).toBeTruthy())
    first.unmount()

    renderSidebar()
    await waitFor(() => expect(libraryBody()).toBeTruthy())
    expect(chatsBody()).toBeNull()
  })

  it('shows the upload target toggle only to admins', async () => {
    me.role = 'user'
    const user = renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())
    fireEvent.click(librarySection())
    await waitFor(() => expect(libraryBody()).toBeTruthy())
    expect(screen.queryByRole('group', { name: 'Upload target' })).toBeNull()
    user.unmount()

    me.role = 'admin'
    renderSidebar()
    await waitFor(() => expect(librarySection()).toBeTruthy())
    fireEvent.click(librarySection())
    await waitFor(() => expect(screen.getByRole('group', { name: 'Upload target' })).toBeTruthy())
  })
})

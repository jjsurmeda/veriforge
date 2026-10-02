import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const navigate = vi.fn()
const uploadMock = vi.fn()
vi.mock('@tanstack/react-router', () => ({ useNavigate: () => navigate }))

vi.mock('../../../generated/sdk.gen', () => ({
  listChatsChatsGet: vi.fn(async () => ({ data: [] })),
  createChatChatsPost: vi.fn(async () => ({ data: { id: 'chat-new' } })),
  patchChatChatsChatIdPatch: vi.fn(async () => ({ data: undefined })),
  deleteChatChatsChatIdDelete: vi.fn(async () => ({ data: undefined })),
  meMeGet: vi.fn(async () => ({ data: { email: 'demo@example.com', role: 'user' } })),
  getQuotaMeQuotaGet: vi.fn(async () => ({ data: null })),
  getLibraryLibraryGet: vi.fn(async () => ({
    data: { documents: [], starter_questions: [] },
  })),
  listModelsModelsGet: vi.fn(async () => ({ data: [] })),
  createRunChatsChatIdRunsPost: vi.fn(async () => ({ data: { run_id: 'run-1' } })),
  uploadChatDocumentChatsChatIdDocumentsPost: uploadMock,
}))

const { ChatIndexPage } = await import('./ChatIndexPage')
const { TooltipProvider } = await import('../../../components/ui/primitives')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <ThemeProvider>
      <TooltipProvider>
        <QueryClientProvider client={client}>
          <ChatIndexPage />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>,
  )
}

afterEach(cleanup)

beforeEach(() => {
  navigate.mockClear()
  uploadMock.mockClear()
})

describe('new-chat entry flow', () => {
  it('keeps a failed upload queued and does not navigate', async () => {
    uploadMock.mockResolvedValue({ error: { message: 'boom' } })
    renderPage()

    fireEvent.change(await screen.findByLabelText('Add sources to the chat'), {
      target: { files: [new File(['x'], 'note.txt', { type: 'text/plain' })] },
    })

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1))
    expect(await screen.findByRole('alert')).toBeTruthy()
    expect(navigate).not.toHaveBeenCalled()

    // The next upload — the user's follow-up question — must carry the file
    // that never landed, so the queue is drained only on success.
    uploadMock.mockResolvedValue({ data: {} })
    fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'and now?' } })
    fireEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(2))
    expect(uploadMock.mock.calls[1]![0].body.file.name).toBe('note.txt')
    await waitFor(() => expect(navigate).toHaveBeenCalled())
  })
})
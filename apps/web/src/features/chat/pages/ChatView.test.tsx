import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { MessageOut } from '../../../generated/types.gen'
import { setAccessToken } from '../../../lib/auth'
import { useChatRunStore } from '../store'

Element.prototype.scrollTo = () => undefined
Element.prototype.scrollIntoView = () => undefined
window.matchMedia = (query: string) =>
  ({ matches: true, media: query, onchange: null, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, dispatchEvent: () => false }) as unknown as MediaQueryList

const streams: string[] = []

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: vi.fn(async (url: string) => {
    streams.push(url)
  }),
}))

const navigate = vi.fn()
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigate,
  useRouterState: () => '/chat/chat-1',
}))

const CHAT_ID = 'chat-1'
const LIVE_RUN = 'run-live'
const OLD_RUN = 'run-old'

function assistantMessage(id: string, runId: string, content: string): MessageOut {
  return {
    id,
    chat_id: CHAT_ID,
    role: 'assistant',
    content,
    status: 'complete',
    created_at: '2026-09-26T00:00:00Z',
    citations: [],
    metrics: null,
    run_id: runId,
  }
}

const MESSAGES: MessageOut[] = [
  {
    id: 'm-q',
    chat_id: CHAT_ID,
    role: 'user',
    content: 'what does the red LED mean?',
    status: 'complete',
    created_at: '2026-09-26T00:00:00Z',
    citations: [],
    metrics: null,
    run_id: null,
  },
  { ...assistantMessage('m-old', OLD_RUN, 'the first answer'), created_at: '2026-09-26T00:00:01Z' },
  { ...assistantMessage('m-new', LIVE_RUN, 'the second answer [1]'), created_at: '2026-09-26T00:00:02Z' },
  {
    ...assistantMessage('m-abstain', LIVE_RUN, 'I could not answer that. Searching the web.'),
    status: 'abstained',
    created_at: '2026-09-26T00:00:03Z',
  },
]

const CITATION = {
  n: 1,
  chunk_id: 'chunk-1',
  document_id: 'doc-1',
  document_name: 'notes.txt',
  page: 1,
  excerpt: 'excerpt',
  rerank_score: 0.9,
  verdict: null,
  p_supported: null,
}

vi.mock('../../../generated/sdk.gen', () => ({
  getChatChatsChatIdGet: vi.fn(async () => ({
    data: { id: CHAT_ID, title: 'A chat', pinned: false, active_run_id: null },
  })),
  listMessagesChatsChatIdMessagesGet: vi.fn(async () => ({
    data: MESSAGES.map((message) =>
      message.id === 'm-new' ? { ...message, citations: [CITATION] } : message,
    ),
  })),
  createRunChatsChatIdRunsPost: vi.fn(),
  cancelRunRunsRunIdCancelPost: vi.fn(),
  getRunRunsRunIdGet: vi.fn(),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents: [], starter_questions: [] } })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async () => ({ data: {} })),
  meMeGet: vi.fn(async () => ({ data: { email: 'demo@example.com', role: 'user' } })),
  getQuotaQuotaGet: vi.fn(async () => ({ data: null })),
  listModelsModelsGet: vi.fn(async () => ({ data: [] })),
  listChatsChatsGet: vi.fn(async () => ({ data: [] })),
  patchChatChatsChatIdPatch: vi.fn(),
  deleteChatChatsChatIdDelete: vi.fn(),
  createChatChatsPost: vi.fn(),
}))

const { ChatView } = await import('./ChatView')
const { TooltipProvider } = await import('../../../components/ui/primitives')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <ThemeProvider>
      <TooltipProvider>
        <QueryClientProvider client={client}>
          <ChatView chatId={CHAT_ID} />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>,
  )
}

const traceRunIds = () =>
  Object.keys(useChatRunStore.getState().runs).filter((id) =>
    streams.some((url) => url.startsWith(`/runs/${id}/`)),
  )

afterEach(cleanup)

beforeEach(() => {
  streams.length = 0
  setAccessToken('test-token')
  useChatRunStore.setState({ runs: {} })
})

describe('Show steps', () => {
  it('points the trace at the clicked message run, not the latest one', async () => {
    renderView()

    const buttons = await screen.findAllByRole('button', { name: 'Show steps' })
    expect(buttons).toHaveLength(3)

    fireEvent.click(buttons[0])

    await waitFor(() => expect(traceRunIds()).toContain(OLD_RUN))
    expect(traceRunIds()).not.toContain(LIVE_RUN)
  })

  it('replays a finished run from run_events so its trace reaches the store', async () => {
    renderView()
    const buttons = await screen.findAllByRole('button', { name: 'Show steps' })

    fireEvent.click(buttons[0])

    await waitFor(() =>
      expect(streams.some((url) => url.startsWith(`/runs/${OLD_RUN}/stream?after_seq=0`))).toBe(true),
    )
  })
})

describe('citation chips', () => {
  it('a chip click selects the Citations tab, not Sources', async () => {
    renderView()

    fireEvent.click(await screen.findByRole('button', { name: /^Citation 1:/ }))

    await waitFor(() =>
      expect(screen.getByRole('tab', { name: /^Citations/ }).getAttribute('aria-selected')).toBe(
        'true',
      ),
    )
    expect(screen.getByRole('tab', { name: 'Sources' }).getAttribute('aria-selected')).toBe('false')
  })
})

describe('composer', () => {
  it('uploads the chosen file and opens the panel on Sources', async () => {
    const { uploadChatDocumentChatsChatIdDocumentsPost } = await import(
      '../../../generated/sdk.gen'
    )
    renderView()

    fireEvent.change(await screen.findByLabelText('Add sources to the chat'), {
      target: { files: [new File(['x'], 'note.txt', { type: 'text/plain' })] },
    })

    await waitFor(() => expect(uploadChatDocumentChatsChatIdDocumentsPost).toHaveBeenCalled())
    await waitFor(() =>
      expect(screen.getByRole('tab', { name: 'Sources' }).getAttribute('aria-selected')).toBe(
        'true',
      ),
    )
  })

  it('the abstain "Try Web" action turns Web on and resends with source both', async () => {
    const { createRunChatsChatIdRunsPost } = await import('../../../generated/sdk.gen')
    renderView()

    expect(screen.getByRole('button', { name: 'Web' }).getAttribute('aria-pressed')).toBe('false')
    fireEvent.click(await screen.findByRole('button', { name: /Searching the web/ }))

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Web' }).getAttribute('aria-pressed')).toBe('true'),
    )
    expect(createRunChatsChatIdRunsPost).toHaveBeenCalledWith(
      expect.objectContaining({
        body: expect.objectContaining({ mode: 'auto', source: 'both' }),
      }),
    )
  })
})

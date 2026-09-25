import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { MessageOut } from '../../../generated/types.gen'
import { setAccessToken } from '../../../lib/auth'
import { useChatRunStore } from '../store'

Element.prototype.scrollTo = () => undefined
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
  { ...assistantMessage('m-old', OLD_RUN, 'the first answer'), created_at: '2026-09-26T00:00:01Z' },
  { ...assistantMessage('m-new', LIVE_RUN, 'the second answer'), created_at: '2026-09-26T00:00:02Z' },
]

vi.mock('../../../generated/sdk.gen', () => ({
  getChatChatsChatIdGet: vi.fn(async () => ({
    data: { id: CHAT_ID, title: 'A chat', pinned: false, include_library: true, active_run_id: null },
  })),
  listMessagesChatsChatIdMessagesGet: vi.fn(async () => ({ data: MESSAGES })),
  createRunChatsChatIdRunsPost: vi.fn(),
  cancelRunRunsRunIdCancelPost: vi.fn(),
  getRunRunsRunIdGet: vi.fn(),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents: [], starter_questions: [] } })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
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
    expect(buttons).toHaveLength(2)

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

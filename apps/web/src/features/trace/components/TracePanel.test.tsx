import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../generated/sdk.gen', () => ({
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents: [], starter_questions: [] } })),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async () => ({ data: {} })),
  deleteDocumentDocumentsDocumentIdDelete: vi.fn(async () => ({ data: undefined })),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(async () => ({ data: undefined })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(async () => ({ data: undefined })),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
}))

const { TracePanel } = await import('./TracePanel')
const { TooltipProvider } = await import('../../../components/ui/primitives')

Element.prototype.scrollIntoView = () => undefined

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <TooltipProvider>
      <QueryClientProvider client={client}>
        <TracePanel
          steps={[]}
          decisions={[]}
          thinking=""
          streaming={false}
          chunks={[]}
          metrics={null}
          hold={false}
          chatId="chat-1"
          viewerDocumentId={null}
          open
        />
      </QueryClientProvider>
    </TooltipProvider>,
  )
}

afterEach(cleanup)

describe('workspace panel empty states', () => {
  it('Sources uses PanelEmpty when the chat has no documents', () => {
    renderPanel()

    fireEvent.click(screen.getByRole('tab', { name: 'Sources' }))

    expect(screen.getByText('Add sources to this chat.')).toBeTruthy()
    expect(screen.getByText('PDF, DOCX, MD, TXT, up to 20 MB.')).toBeTruthy()
  })

  it('Citations, Trace and Metrics each use PanelEmpty', () => {
    renderPanel()

    fireEvent.click(screen.getByRole('tab', { name: /^Citations/ }))
    expect(screen.getByText('No citations yet.')).toBeTruthy()
    expect(
      screen.getByText('The evidence behind an answer appears here once a run retrieves it.'),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Trace' }))
    expect(screen.getByText('No run yet.')).toBeTruthy()
    expect(
      screen.getByText('Decisions and reasoning stream here while a run is in flight.'),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Metrics' }))
    expect(screen.getByText('No metrics yet.')).toBeTruthy()
    expect(
      screen.getByText('Latency, tokens, credits and scores land when the run completes.'),
    ).toBeTruthy()
  })
})

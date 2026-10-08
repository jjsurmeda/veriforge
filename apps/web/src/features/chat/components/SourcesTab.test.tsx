import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DocumentOut } from '../../../generated/types.gen'

const uploads: string[] = []
let documents: DocumentOut[] = []
let chatDocumentsFail = false
let libraryFail = false

function makeDocument(id: string, name: string, status = 'queued'): DocumentOut {
  return {
    id,
    name,
    mime: 'text/plain',
    sha256: 'a'.repeat(64),
    status,
    page_flags: null,
    error: null,
    tags: [],
    created_at: '2026-09-26T00:00:00Z',
  }
}

vi.mock('../../../generated/sdk.gen', () => ({
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () =>
    chatDocumentsFail
      ? { error: { error_code: 'server_error', message: 'boom' } }
      : { data: documents },
  ),
  getLibraryLibraryGet: vi.fn(async () =>
    libraryFail
      ? { error: { error_code: 'server_error', message: 'boom' } }
      : { data: { documents: [], starter_questions: [] } },
  ),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async ({ body }: { body: { file: File } }) => {
    uploads.push(body.file.name)
    return { data: makeDocument('new', body.file.name) }
  }),
  deleteDocumentDocumentsDocumentIdDelete: vi.fn(async () => ({ data: undefined })),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(async () => ({ data: undefined })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(async () => ({ data: undefined })),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
}))

const { SourcesTab } = await import('./SourcesTab')
const { TooltipProvider } = await import('../../../components/ui/primitives')
const { ThemeProvider } = await import('../../../components/ThemeToggle')

Element.prototype.scrollIntoView = () => undefined
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => undefined
Element.prototype.releasePointerCapture = () => undefined

function renderTab(viewerDocumentId: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const onCloseViewer = vi.fn()
  const onViewDocument = vi.fn()
  const view = render(
    <ThemeProvider>
      <TooltipProvider>
        <QueryClientProvider client={client}>
          <SourcesTab
            chatId="chat-1"
            viewerDocumentId={viewerDocumentId}
            onViewDocument={onViewDocument}
            onCloseViewer={onCloseViewer}
          />
        </QueryClientProvider>
      </TooltipProvider>
    </ThemeProvider>,
  )
  return { ...view, onCloseViewer, onViewDocument }
}

afterEach(() => {
  cleanup()
  uploads.length = 0
  documents = []
  chatDocumentsFail = false
  libraryFail = false
})

describe('SourcesTab', () => {
  it('uploads through the chat documents endpoint and shows a status row', async () => {
    documents = [makeDocument('d1', 'notes.txt', 'ready')]
    renderTab()

    const picker = await screen.findByLabelText('Add sources to this chat')
    fireEvent.change(picker, { target: { files: [new File(['x'], 'extra.md')] } })

    await waitFor(() => expect(uploads).toEqual(['extra.md']))
    await waitFor(() => expect(screen.getByText('notes.txt')).toBeTruthy())
    expect(screen.getByText('ready')).toBeTruthy()
  })

  it('shows the empty dropzone and the Shared row when the chat has no documents', async () => {
    renderTab()

    expect(await screen.findByText('Add sources to this chat.')).toBeTruthy()
    expect(screen.getByText('PDF, DOCX, MD, TXT, up to 20 MB.')).toBeTruthy()
    expect(screen.getByText(/always searched/)).toBeTruthy()
  })

  it('reports the viewed document from its row menu', async () => {
    documents = [makeDocument('d1', 'notes.txt', 'ready')]
    const { onViewDocument } = renderTab()

    fireEvent.pointerDown(await screen.findByRole('button', { name: 'Actions for notes.txt' }), {
      button: 0,
      ctrlKey: false,
    })
    fireEvent.click(await screen.findByRole('menuitem', { name: 'View' }))

    expect(onViewDocument).toHaveBeenCalledWith('d1')
  })

  it('replaces the list with the viewer and closes it again', async () => {
    documents = [makeDocument('d1', 'notes.txt', 'ready')]
    const { onCloseViewer } = renderTab('d1')

    await waitFor(() => expect(screen.getByRole('heading', { name: 'notes.txt' })).toBeTruthy())
    expect(screen.queryByText('This chat')).toBeNull()

    fireEvent.click(screen.getByLabelText('Back to Sources'))
    expect(onCloseViewer).toHaveBeenCalled()
  })

  // Item 6: a failed read used to render as an empty corpus, which is a
  // statement about the user's documents rather than about the request.
  it('a failed chat read is an error, never "add sources to this chat"', async () => {
    chatDocumentsFail = true
    renderTab()

    expect(
      await screen.findByText('This chat’s sources could not be read.'),
    ).toBeTruthy()
    expect(screen.queryByText('Add sources to this chat.')).toBeNull()
    expect(screen.queryByText('PDF, DOCX, MD, TXT, up to 20 MB.')).toBeNull()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('a failed library read is an error, never "the Shared library is empty"', async () => {
    libraryFail = true
    renderTab()

    fireEvent.click(await screen.findByRole('button', { expanded: false, name: /Shared library/ }))

    expect(await screen.findByText('The Shared library could not be read.')).toBeTruthy()
    expect(screen.queryByText('The Shared library is empty.')).toBeNull()
  })

  it('a genuinely empty library still gets the empty state', async () => {
    renderTab()

    fireEvent.click(await screen.findByRole('button', { expanded: false, name: /Shared library/ }))

    expect(await screen.findByText('The Shared library is empty.')).toBeTruthy()
  })

  // The chat query is disabled without a chat, and a disabled query never
  // leaves `isPending` — so this must read as "no chat yet", not "reading…".
  it('with no chat selected it says so rather than reading forever', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <ThemeProvider>
        <TooltipProvider>
          <QueryClientProvider client={client}>
            <SourcesTab
              chatId={null}
              viewerDocumentId={null}
              onViewDocument={vi.fn()}
              onCloseViewer={vi.fn()}
            />
          </QueryClientProvider>
        </TooltipProvider>
      </ThemeProvider>,
    )

    expect(await screen.findByText('No chat to add sources to yet.')).toBeTruthy()
    expect(screen.queryByText('Reading this chat’s sources…')).toBeNull()
  })
})

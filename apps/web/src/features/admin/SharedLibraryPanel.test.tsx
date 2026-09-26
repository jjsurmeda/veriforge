import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { LibraryDocumentOut } from '../../generated/types.gen'

function sharedDocument(name: string, status: string): LibraryDocumentOut {
  return {
    id: `doc-${name}`,
    name,
    mime: 'text/plain',
    sha256: 'a'.repeat(64),
    status,
    page_flags: null,
    error: null,
    tags: ['gutenberg'],
    created_at: '2026-09-26T00:00:00Z',
    shared: true,
    editable: true,
  }
}

let documents: LibraryDocumentOut[] = []

vi.mock('../../generated/sdk.gen', () => ({
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents, starter_questions: [] } })),
  uploadLibraryDocumentLibraryDocumentsPost: vi.fn(async () => ({ data: {} })),
  deleteDocumentDocumentsDocumentIdDelete: vi.fn(async () => ({ data: undefined })),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(async () => ({ data: undefined })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(async () => ({ data: undefined })),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
}))

const { SharedLibraryPanel } = await import('./SharedLibraryPanel')

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <SharedLibraryPanel />
    </QueryClientProvider>,
  )
}

afterEach(cleanup)
beforeEach(() => {
  documents = []
})

describe('SharedLibraryPanel', () => {
  it('lists every Shared document with its status and tags', async () => {
    documents = [
      sharedDocument('pride-and-prejudice.txt', 'ready'),
      sharedDocument('frankenstein.txt', 'parsing'),
    ]
    renderPanel()

    expect(await screen.findByText('pride-and-prejudice.txt')).toBeTruthy()
    expect(screen.getByText('frankenstein.txt')).toBeTruthy()
    expect(screen.getByText('ready')).toBeTruthy()
    expect(screen.getByText('parsing')).toBeTruthy()
    expect(screen.getAllByText('gutenberg')).toHaveLength(2)
  })

  it('publishes through the admin-only route and says so when empty', async () => {
    renderPanel()

    expect(await screen.findByText('Nothing published yet.')).toBeTruthy()
    expect(
      screen.getByText('Drop files here, or click to publish to Shared'),
    ).toBeTruthy()
  })
})

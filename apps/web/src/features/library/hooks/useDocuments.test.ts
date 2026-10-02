import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { DocumentOut } from '../../../generated/types.gen'
import { shouldPoll, useChatDocuments, useLibrary } from './useDocuments'

const libraryGet = vi.fn()
const chatDocumentsGet = vi.fn()
vi.mock('../../../generated/sdk.gen', () => ({
  getLibraryLibraryGet: (...args: unknown[]) => libraryGet(...args),
  listChatDocumentsChatsChatIdDocumentsGet: (...args: unknown[]) => chatDocumentsGet(...args),
}))

function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client }, children)
}

function doc(status: string): DocumentOut {
  return {
    id: 'd1',
    name: 'doc.pdf',
    mime: 'application/pdf',
    sha256: 'ab',
    status,
    page_flags: null,
    error: null,
    tags: [],
    created_at: '2026-09-23T00:00:00Z',
  }
}

describe('shouldPoll', () => {
  it('polls while any document is live', () => {
    for (const status of ['queued', 'parsing', 'embedding']) {
      expect(shouldPoll([doc('ready'), doc(status)])).toBe(true)
    }
  })

  it('stops polling when every document is terminal', () => {
    expect(shouldPoll([doc('ready'), doc('failed')])).toBe(false)
  })

  it('does not poll an empty or missing list', () => {
    expect(shouldPoll([])).toBe(false)
    expect(shouldPoll(undefined)).toBe(false)
  })
})

describe('useLibrary', () => {
  beforeEach(() => {
    libraryGet.mockReset()
    chatDocumentsGet.mockReset()
  })

  it('reports a failed library read as an error, not as an empty library', async () => {
    libraryGet.mockResolvedValue({ data: undefined, error: { message: 'boom' } })

    const { result } = renderHook(() => useLibrary(), { wrapper: makeWrapper() })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
    expect(libraryGet).toHaveBeenCalled()
  })

  it('reports an empty library as empty, with no error', async () => {
    libraryGet.mockResolvedValue({ data: { documents: [], starter_questions: [] } })

    const { result } = renderHook(() => useLibrary(), { wrapper: makeWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.isError).toBe(false)
    expect(result.current.data?.documents).toEqual([])
  })
})

describe('useChatDocuments', () => {
  beforeEach(() => {
    libraryGet.mockReset()
    chatDocumentsGet.mockReset()
  })

  it('reports a failed document read as an error, not as no sources', async () => {
    chatDocumentsGet.mockResolvedValue({ data: undefined, error: { message: 'boom' } })

    const { result } = renderHook(() => useChatDocuments('chat-1'), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})

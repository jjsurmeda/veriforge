// Replays a recorded SSE fixture through useRunStream and asserts on the
// resulting Zustand state (testing.md: mock fetch-event-source, no real
// stream; fixture format is shared with the playwright e2e suite).
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { createElement, type ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { readFileSync } from 'node:fs'
import { setAccessToken } from '../../../lib/auth'
import { useChatRunStore } from '../store'
import type { StreamEvent } from '../types'
import { useRunStream } from './useRunStream'

type FetchEventSourceArgs = Parameters<typeof fetchEventSource>
type Handlers = FetchEventSourceArgs[1]

const calls: { url: string; handlers: Handlers }[] = []

vi.mock('@microsoft/fetch-event-source', () => ({
  fetchEventSource: vi.fn(async (url: string, handlers: Handlers) => {
    calls.push({ url, handlers })
  }),
}))

const events = JSON.parse(
  readFileSync('e2e/fixtures/runs/basic-stream.json', 'utf-8'),
) as StreamEvent[]
const RUN_ID = 'run-fixture-1'
const CHAT_ID = 'chat-fixture-1'

function message(event: StreamEvent) {
  return { event: event.type, data: JSON.stringify(event) }
}

function makeWrapper(queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: queryClient }, children)
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
  })
}

describe('useRunStream', () => {
  beforeEach(() => {
    calls.length = 0
    setAccessToken('test-token')
    useChatRunStore.setState({ runs: {} })
  })

  it('applies a fixture stream into the store and clears it on completion', async () => {
    const queryClient = new QueryClient()
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    const { result, unmount } = renderHook(() => useRunStream(RUN_ID, CHAT_ID), {
      wrapper: makeWrapper(queryClient),
    })
    await flush()

    expect(calls).toHaveLength(1)
    const handlers = calls[0].handlers
    await act(async () => {
      await handlers.onopen?.(new Response())
      for (const event of events.slice(0, 3)) handlers.onmessage?.(message(event) as never)
    })

    const midRun = useChatRunStore.getState().runs[RUN_ID]
    expect(midRun.status).toBe('streaming')
    expect(midRun.text).toBe('Hello ')
    expect(midRun.lastSeq).toBe(3)

    await act(async () => {
      for (const event of events.slice(3)) handlers.onmessage?.(message(event) as never)
    })

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['messages', CHAT_ID] })
    expect(useChatRunStore.getState().runs[RUN_ID]).toBeUndefined()

    unmount()
    expect(result.current.resume).toBeTypeOf('function')
  })

  it('surfaces connection_lost after three failed retries, then resumes', async () => {
    const queryClient = new QueryClient()
    const { result } = renderHook(() => useRunStream(RUN_ID, CHAT_ID), {
      wrapper: makeWrapper(queryClient),
    })
    await flush()

    const handlers = calls[0].handlers
    await act(async () => {
      handlers.onmessage?.(message(events[1]) as never)
    })
    for (let i = 0; i < 3; i++) {
      await act(async () => {
        try {
          handlers.onerror?.(new Error('boom'))
        } catch {
          // third throw is how the hook stops fetch-event-source retrying
        }
      })
    }
    await flush()

    expect(useChatRunStore.getState().runs[RUN_ID].status).toBe('connection_lost')

    await act(async () => {
      result.current.resume()
    })
    await flush()
    expect(calls).toHaveLength(2)
    expect(useChatRunStore.getState().runs[RUN_ID].status).toBe('connecting')
  })

  it('resumes from the last seen sequence number', async () => {
    const queryClient = new QueryClient()
    useChatRunStore.setState({
      runs: {
        [RUN_ID]: {
          status: 'streaming',
          text: 'Hello ',
          lastSeq: 2,
          messageId: null,
          error: null,
          chunks: [],
          metrics: null,
        },
      },
    })
    renderHook(() => useRunStream(RUN_ID, CHAT_ID), { wrapper: makeWrapper(queryClient) })
    await flush()

    expect(calls[0].url).toContain('after_seq=2')
  })
})

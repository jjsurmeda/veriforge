// The only place that owns a fetch-event-source connection (react.md):
// components read the Zustand store, never the stream.
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'

import { getAccessToken } from '../../../lib/auth'
import { useChatRunStore } from '../store'
import { TERMINAL_TYPES, type StreamEvent } from '../types'

const MAX_RETRIES = 3

export interface UseRunStream {
  resume: () => void
}

export function useRunStream(runId: string | null, chatId: string | null): UseRunStream {
  const queryClient = useQueryClient()
  const retries = useRef(0)
  const [nonce, setNonce] = useState(0)

  const resume = useCallback(() => {
    retries.current = 0
    setNonce((n) => n + 1)
  }, [])

  useEffect(() => {
    if (!runId) return
    const existing = useChatRunStore.getState().runs[runId]
    if (
      existing &&
      (existing.status === 'completed' ||
        existing.status === 'cancelled' ||
        existing.status === 'failed')
    ) {
      return
    }
    useChatRunStore.getState().begin(runId)

    const controller = new AbortController()
    let stopped = false

    const lastSeq = useChatRunStore.getState().runs[runId]?.lastSeq ?? 0
    const url = `/runs/${runId}/stream?after_seq=${lastSeq}`

    fetchEventSource(url, {
      signal: controller.signal,
      credentials: 'include',
      headers: { Authorization: `Bearer ${getAccessToken() ?? ''}` },
      onopen: async (response) => {
        if (!response.ok) throw new Error(`stream open failed: ${response.status}`)
      },
      onmessage: (message) => {
        if (!message.data) return
        const event = JSON.parse(message.data) as StreamEvent
        useChatRunStore.getState().applyEvent(runId, event)
        if (TERMINAL_TYPES.has(event.type)) {
          void queryClient.invalidateQueries({ queryKey: ['messages', chatId] })
          void queryClient.invalidateQueries({ queryKey: ['chat', chatId] })
          if (event.type === 'run.completed') {
            void queryClient.invalidateQueries({ queryKey: ['chats'] })
          }
          // No store clear: the trace panel, verdicts, metrics and
          // suggestions stay visible after completion (store.ts begin()).
        }
      },
      onerror: (error) => {
        if (stopped) throw error
        retries.current += 1
        if (retries.current >= MAX_RETRIES) {
          useChatRunStore.getState().setConnectionLost(runId)
          throw error
        }
        return 250 * 2 ** retries.current
      },
      onclose: () => {},
    }).catch(() => {
      // Aborted on unmount or fatally errored; store state already reflects it.
    })

    return () => {
      stopped = true
      controller.abort()
    }
  }, [runId, chatId, nonce, queryClient])

  return { resume }
}

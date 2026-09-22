import { create } from 'zustand'

import type { StreamEvent } from './types'

export type RunStatus =
  | 'connecting'
  | 'streaming'
  | 'completed'
  | 'cancelled'
  | 'failed'
  | 'connection_lost'

export interface RunLive {
  status: RunStatus
  text: string
  lastSeq: number
  messageId: string | null
  error: string | null
}

interface ChatRunStore {
  runs: Record<string, RunLive>
  begin: (runId: string, messageId?: string | null) => void
  applyEvent: (runId: string, event: StreamEvent) => void
  setConnectionLost: (runId: string) => void
  clear: (runId: string) => void
}

const empty: RunLive = {
  status: 'connecting',
  text: '',
  lastSeq: 0,
  messageId: null,
  error: null,
}

export const useChatRunStore = create<ChatRunStore>()((set) => ({
  runs: {},

  begin: (runId, messageId = null) =>
    set((state) => {
      const existing = state.runs[runId]
      // Keep progress across reconnects so resume() replays from lastSeq.
      const base = existing
        ? { ...existing, status: 'connecting' as RunStatus }
        : { ...empty }
      return {
        runs: {
          ...state.runs,
          [runId]: { ...base, messageId: messageId ?? base.messageId },
        },
      }
    }),

  applyEvent: (runId, event) =>
    set((state) => {
      const current = state.runs[runId] ?? empty
      const next: RunLive = { ...current, lastSeq: Math.max(current.lastSeq, event.seq ?? 0) }
      switch (event.type) {
        case 'run.started':
          next.status = 'streaming'
          break
        case 'answer.delta':
          next.status = 'streaming'
          next.text += event.text
          break
        case 'heartbeat':
          break
        case 'run.completed':
          next.status = 'completed'
          next.messageId = event.message_id
          break
        case 'run.cancelled':
          next.status = 'cancelled'
          next.messageId = event.message_id
          break
        case 'run.failed':
          next.status = 'failed'
          next.error = event.error_code
          break
      }
      return { runs: { ...state.runs, [runId]: next } }
    }),

  setConnectionLost: (runId) =>
    set((state) => {
      const current = state.runs[runId] ?? empty
      return {
        runs: { ...state.runs, [runId]: { ...current, status: 'connection_lost' } },
      }
    }),

  clear: (runId) =>
    set((state) => {
      const runs = { ...state.runs }
      delete runs[runId]
      return { runs }
    }),
}))

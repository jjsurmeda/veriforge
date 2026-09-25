import { create } from 'zustand'

import type {
  Abstain,
  Conflict,
  Decision,
  Metrics,
  Plan,
  RetrievedChunk,
  ReviewClaim,
  Revision,
  StepCompleted,
  StepStarted,
} from '../../generated/types.gen'
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
  chunks: RetrievedChunk[]
  metrics: Metrics | null
  steps: Array<StepStarted | StepCompleted>
  plan: Plan | null
  decisions: Decision[]
  thinking: string
  abstain: Abstain | null
  conflict: Conflict | null
  claims: ReviewClaim[]
  hold: boolean
  revision: Revision | null
  suggestions: string[]
}

interface ChatRunStore {
  runs: Record<string, RunLive>
  begin: (runId: string, messageId?: string | null) => void
  applyEvent: (runId: string, event: StreamEvent) => void
  setConnectionLost: (runId: string) => void
}

const empty: RunLive = {
  status: 'connecting',
  text: '',
  lastSeq: 0,
  messageId: null,
  error: null,
  chunks: [],
  metrics: null,
  steps: [],
  plan: null,
  decisions: [],
  thinking: '',
  abstain: null,
  conflict: null,
  claims: [],
  hold: false,
  revision: null,
  suggestions: [],
}

export const useChatRunStore = create<ChatRunStore>()((set) => ({
  runs: {},

  begin: (runId, messageId = null) =>
    set((state) => {
      // Resume (same run): keep accumulated progress so lastSeq replay
      // works. New run: replace the map — one entry at a time, kept after
      // the run completes so the Metrics tab, verdicts and suggestions
      // stay visible (slice-1's clear-on-terminal made the trust UI
      // vanish the moment the answer landed).
      const existing = state.runs[runId]
      if (existing) {
        return { runs: { [runId]: { ...existing, status: 'connecting' as RunStatus } } }
      }
      return { runs: { [runId]: { ...empty, messageId: messageId ?? null } } }
    }),

  applyEvent: (runId, event) =>
    set((state) => {
      const current = state.runs[runId] ?? empty
      const next: RunLive = { ...current, lastSeq: Math.max(current.lastSeq, event.seq ?? 0) }
      switch (event.type) {
        case 'run.started':
          next.status = 'streaming'
          break
        case 'step.started':
        case 'step.completed':
          next.steps = [...next.steps, event]
          break
        case 'plan':
          next.plan = event
          break
        case 'decision':
          next.decisions = [...next.decisions, event]
          break
        case 'thinking.delta':
          next.thinking += event.text
          break
        case 'retrieval':
          next.chunks = event.chunks ?? []
          break
        case 'abstain':
          next.abstain = event
          break
        case 'conflict':
          next.conflict = event
          break
        case 'answer.delta':
          next.status = 'streaming'
          next.text += event.text
          break
        case 'answer.hold':
          next.hold = true
          break
        case 'review.claim':
          next.claims = [
            ...next.claims.filter((c) => c.claim_id !== event.claim_id),
            event,
          ]
          break
        case 'revision':
          next.revision = event
          break
        case 'suggestions':
          next.suggestions = event.questions ?? []
          break
        case 'metrics':
          next.metrics = event
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
}))

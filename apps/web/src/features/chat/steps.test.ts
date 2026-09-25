import { describe, expect, it } from 'vitest'

import type { StreamEvent } from './types'
import { describeStep } from './steps'

const events: StreamEvent[] = [
  { type: 'run.started', seq: 1 },
  { type: 'plan', seq: 2, sub_questions: [{ id: 'q1', question: 'Find the policy' }] },
  { type: 'step.started', seq: 3, node: 'retrieve', label: 'Retrieve' },
  { type: 'step.completed', seq: 4, node: 'retrieve', label: 'Retrieve', duration_ms: 4 },
  { type: 'decision', seq: 5, name: 'mode', value: 'deep', engine: 'jev', latency_ms: 2 },
  { type: 'thinking.delta', seq: 6, text: 'Compare the evidence' },
  { type: 'retrieval', seq: 7, query: 'policy', chunks: [] },
  { type: 'answer.hold', seq: 8, reason: 'verifying' },
  { type: 'review.claim', seq: 9, claim_id: 'c1', text: 'claim', citation_ids: ['1'], verdict: 'supported', p_supported: 0.9 },
  { type: 'revision', seq: 10, revised_text: 'answer', diff: '' },
  { type: 'answer.delta', seq: 11, text: 'answer' },
  { type: 'conflict', seq: 12, citation_ids_left: ['1'], citation_ids_right: ['2'], rule_applied: 'prefer' },
  { type: 'abstain', seq: 13, found_summary: 'none', missing_summary: 'all' },
  { type: 'suggestions', seq: 14, questions: ['Next?'] },
  { type: 'metrics', seq: 15, latency_ms: {}, tokens_in: 1, tokens_out: 2, credits: 0, context_used: 0, context_window: 10 },
  { type: 'heartbeat', seq: 16 },
  { type: 'run.completed', seq: 17, message_id: 'm1' },
  { type: 'run.cancelled', seq: 18, message_id: 'm1' },
  { type: 'run.failed', seq: 19, error_code: 'failed', message: 'failed' },
]

describe('describeStep', () => {
  it('maps every stream event type to a human-readable step', () => {
    const labels = events.map((event) => describeStep(event).label)
    expect(labels).toHaveLength(events.length)
    expect(new Set(labels).size).toBeGreaterThan(8)
    expect(describeStep(events[1]).detail).toBe('Find the policy')
    expect(describeStep(events[8]).status).toBe('active')
  })
})

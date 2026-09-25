import { beforeEach, expect, it, describe } from 'vitest'

import type { ReviewClaim } from '../../generated/types.gen'
import { useChatRunStore, type RunLive } from './store'

const RUN_ID = 'run-1'

function baseRun(): RunLive {
  return {
    status: 'streaming',
    text: 'The battery lasts ten hours [1].',
    lastSeq: 5,
    messageId: 'm1',
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
}

function claimEvent(claimId: string, verdict: string, ns: string[]): ReviewClaim {
  return {
    type: 'review.claim',
    run_id: RUN_ID,
    seq: 6,
    claim_id: claimId,
    text: `claim ${claimId}`,
    citation_ids: ns,
    verdict,
    p_supported: verdict === 'supported' ? 0.95 : 0.0,
  } as ReviewClaim
}

describe('chat run store — slice 6 events', () => {
  beforeEach(() => {
    useChatRunStore.setState({ runs: { [RUN_ID]: baseRun() } })
  })

  it('answer.hold marks the run as held', () => {
    useChatRunStore.getState().applyEvent(RUN_ID, {
      type: 'answer.hold',
      run_id: RUN_ID,
      seq: 6,
      reason: 'verifying',
    } as never)
    expect(useChatRunStore.getState().runs[RUN_ID].hold).toBe(true)
  })

  it('review.claim events accumulate keyed by claim_id', () => {
    const store = useChatRunStore.getState()
    store.applyEvent(RUN_ID, claimEvent('c1', 'supported', ['1']))
    useChatRunStore.getState().applyEvent(RUN_ID, claimEvent('c2', 'unsupported', []))
    // Re-delivery of c1 (resume) replaces rather than duplicates.
    useChatRunStore.getState().applyEvent(RUN_ID, claimEvent('c1', 'partial', ['1']))
    const claims = useChatRunStore.getState().runs[RUN_ID].claims
    expect(claims).toHaveLength(2)
    expect(claims.find((c) => c.claim_id === 'c1')?.verdict).toBe('partial')
  })

  it('revision stores revised text and diff', () => {
    useChatRunStore.getState().applyEvent(RUN_ID, {
      type: 'revision',
      run_id: RUN_ID,
      seq: 6,
      revised_text: 'fixed',
      diff: '-old\n+fixed',
    } as never)
    const revision = useChatRunStore.getState().runs[RUN_ID].revision
    expect(revision?.revised_text).toBe('fixed')
    expect(revision?.diff).toContain('+fixed')
  })

  it('suggestions stores the question list', () => {
    useChatRunStore.getState().applyEvent(RUN_ID, {
      type: 'suggestions',
      run_id: RUN_ID,
      seq: 6,
      questions: ['a?', 'b?', 'c?'],
    } as never)
    expect(useChatRunStore.getState().runs[RUN_ID].suggestions).toEqual(['a?', 'b?', 'c?'])
  })
})

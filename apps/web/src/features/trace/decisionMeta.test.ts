import { describe, expect, it } from 'vitest'

import type { Decision } from '../../generated/types.gen'
import {
  decisionLabel,
  decisionOutcome,
  decisionStageLabel,
  groupDecisions,
} from './decisionMeta'

function decision(partial: Partial<Decision>): Decision {
  return {
    type: 'decision',
    run_id: 'run-1',
    seq: 1,
    ts: '2026-09-25T00:00:00Z',
    name: 'intent',
    value: 'lookup',
    engine: 'jev',
    latency_ms: 10,
    ...partial,
  }
}

describe('groupDecisions', () => {
  it('groups answers by call id and preserves call order', () => {
    const groups = groupDecisions([
      decision({ name: 'guard_injection', call_id: 'call-1', stage: 'ingress' }),
      decision({ name: 'intent', call_id: 'call-1', stage: 'ingress' }),
      decision({ name: 'sufficient', call_id: 'call-2', stage: 'sufficient' }),
    ])

    expect(groups.map((group) => group.key)).toEqual(['call:call-1', 'call:call-2'])
    expect(groups[0]?.decisions).toHaveLength(2)
    expect(groups[1]?.stage).toBe('sufficient')
  })

  it('falls back to stage and then one legacy group', () => {
    const byStage = groupDecisions([
      decision({ name: 'guard_pii', stage: 'ingress' }),
      decision({ name: 'off_topic', stage: 'ingress' }),
      decision({ name: 'intent' }),
      decision({ name: 'source' }),
    ])

    expect(byStage.map((group) => group.key)).toEqual(['stage:ingress', 'legacy'])
    expect(byStage[0]?.decisions).toHaveLength(2)
    expect(byStage[1]?.decisions).toHaveLength(2)
  })
})

describe('decision metadata', () => {
  it('handles dynamic names without crashing', () => {
    expect(decisionLabel('chunk_injection_4')).toBe('Chunk checks')
    expect(decisionLabel('claim_c1')).toBe('Claim verdicts')
    expect(decisionLabel('mystery_check')).toBe('mystery_check')
    expect(decisionStageLabel('claim_verdict')).toBe('Review')
    expect(decisionStageLabel('unknown_stage')).toBe('Unknown stage')
  })

  it('derives outcomes at, above, and below a threshold', () => {
    expect(decisionOutcome(decision({ name: 'guard_injection', probability: 0.84, threshold: 0.85 }))).toEqual({
      label: 'pass',
      tone: 'success',
    })
    expect(decisionOutcome(decision({ name: 'guard_injection', probability: 0.85, threshold: 0.85 }))).toEqual({
      label: 'block',
      tone: 'danger',
    })
    expect(decisionOutcome(decision({ name: 'guard_injection', probability: 0.9, threshold: 0.85 }))).toEqual({
      label: 'block',
      tone: 'danger',
    })
  })
})

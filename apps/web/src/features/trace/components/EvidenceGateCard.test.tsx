import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Decision } from '../../../generated/types.gen'
import { EvidenceGateCard } from './EvidenceGateCard'

afterEach(cleanup)

/** One recorded-shaped decision event, from the union TRD §12 defines. Only
 *  the fields these tests read are set; the rest carry the schema's defaults,
 *  the way an event replayed off the bus arrives. */
function decision(overrides: Partial<Decision> & Pick<Decision, 'name'>): Decision {
  return {
    run_id: 'run-1',
    seq: 1,
    ts: '2026-10-06T03:00:00Z',
    type: 'decision',
    value: 0.5,
    probability: null,
    probabilities: null,
    engine: 'jev',
    latency_ms: 210,
    reasoning: null,
    stage: null,
    call_id: null,
    batch_size: null,
    threshold: null,
    ...overrides,
  }
}

/** A run that answered: every gate cleared, one Jev call per gate. */
const allPass: Decision[] = [
  decision({ name: 'intent', value: 'lookup', probability: 0.9, stage: 'ingress' }),
  decision({
    name: 'evidence',
    value: 0.81,
    probability: null,
    stage: 'gate',
    call_id: 'call-ev',
    batch_size: 1,
    threshold: 0.55,
  }),
  decision({
    name: 'entity_0_0',
    value: 0.66,
    probability: 0.66,
    stage: 'evidence',
    call_id: 'call-ev',
    batch_size: 3,
    threshold: 0.5,
  }),
  decision({ name: 'conflict_0', value: 0.02, stage: 'conflict', threshold: 0.6 }),
]

/** The icon inside the verdict label — the shape that carries the verdict when
 *  colour does not. */
function verdictIcon(label: string): Element | null | undefined {
  return screen.getByText(label).closest('span')?.querySelector('svg')
}

describe('EvidenceGateCard', () => {
  it('renders nothing when the run published no gate decisions', () => {
    const { container } = render(<EvidenceGateCard decisions={[decision({ name: 'intent' })]} />)
    expect(container.innerHTML).toBe('')
  })

  it('shows one row per gate with its value, threshold and a cleared verdict', () => {
    render(<EvidenceGateCard decisions={allPass} />)

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    const rows = within(card).getAllByRole('meter')
    expect(rows.map((row) => row.getAttribute('aria-label'))).toEqual([
      'Evidence value 0.81, threshold 0.55, answered',
      'Entity match value 0.66, threshold 0.50, matched',
      'Conflict value 0.02, threshold 0.60, sources agree',
    ])
    // The value is rendered as text, not only as a bar width.
    expect(within(card).getByText('0.81')).toBeTruthy()
    expect(within(card).getByText('vs 0.55')).toBeTruthy()
  })

  it('gives a cleared gate and a blocked gate different shapes as well as words', () => {
    const cleared = render(
      <EvidenceGateCard
        decisions={[decision({ name: 'evidence', value: 0.9, stage: 'gate', threshold: 0.55 })]}
      />,
    )
    const clearedShape = verdictIcon('answered')?.innerHTML
    cleanup()

    render(
      <EvidenceGateCard
        decisions={[decision({ name: 'evidence', value: 0.41, stage: 'gate', threshold: 0.55 })]}
      />,
    )
    // Text verdict, and the value beside it rather than a colour alone.
    expect(screen.getByText('too little evidence')).toBeTruthy()
    expect(screen.getByRole('meter').getAttribute('aria-label')).toBe(
      'Evidence value 0.41, threshold 0.55, too little evidence',
    )
    // The two verdicts do not share an icon, so the rows stay distinguishable
    // with no colour perception at all.
    expect(verdictIcon('too little evidence')?.innerHTML).toBeTruthy()
    expect(verdictIcon('too little evidence')?.innerHTML).not.toBe(clearedShape)
    cleared.unmount()
  })

  it('folds the per-passage entity checks into one row on the best passage', () => {
    render(
      <EvidenceGateCard
        decisions={[
          decision({ name: 'entity_0_0', value: 0.11, probability: 0.11, threshold: 0.5, batch_size: 3 }),
          decision({ name: 'entity_1_0', value: 0.58, probability: 0.58, threshold: 0.5, batch_size: 3 }),
          decision({ name: 'entity_2_0', value: 0.04, probability: 0.04, threshold: 0.5, batch_size: 3 }),
        ]}
      />,
    )

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    expect(within(card).getAllByRole('meter')).toHaveLength(1)
    expect(within(card).getByRole('meter').getAttribute('aria-label')).toBe(
      'Entity match value 0.58, threshold 0.50, matched',
    )
    expect(within(card).getByText('best of 3 passages')).toBeTruthy()
  })

  it('marks the entity gate blocked when no passage matched the named entity', () => {
    render(
      <EvidenceGateCard
        decisions={[
          decision({ name: 'entity_0_0', value: 0.06, probability: 0.06, threshold: 0.5 }),
          decision({ name: 'entity_1_0', value: 0.31, probability: 0.31, threshold: 0.5 }),
        ]}
      />,
    )

    expect(screen.getByText('no passage matches')).toBeTruthy()
    expect(screen.getByRole('meter').getAttribute('aria-label')).toBe(
      'Entity match value 0.31, threshold 0.50, no passage matches',
    )
  })

  it('badges a fallback-engine gate and says the engine was degraded', () => {
    render(
      <EvidenceGateCard
        decisions={[
          decision({
            name: 'evidence',
            value: 0.8,
            probability: null,
            engine: 'fallback',
            threshold: 0.55,
          }),
        ]}
      />,
    )

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    expect(within(card).getByText('fallback')).toBeTruthy()
    expect(within(card).getByTitle('Jev unavailable — answered by LLM fallback')).toBeTruthy()
    // The verdict is still a real verdict on fallback numbers — the fallback
    // engine is calibrated differently (TRD §8) but the gate still cleared.
    expect(within(card).getByText('answered')).toBeTruthy()
  })

  it('discloses a conflict above the floor instead of calling it a failure', () => {
    render(
      <EvidenceGateCard
        decisions={[decision({ name: 'conflict_0', value: 0.95, stage: 'conflict', threshold: 0.6 })]}
      />,
    )

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    expect(within(card).getByText('disclosed')).toBeTruthy()
    expect(within(card).getByRole('meter').getAttribute('aria-label')).toBe(
      'Conflict value 0.95, threshold 0.60, disclosed',
    )
  })

  it('takes the most severe pair when several conflict checks ran', () => {
    render(
      <EvidenceGateCard
        decisions={[
          decision({ name: 'conflict_0', value: 0.03, threshold: 0.6 }),
          decision({ name: 'conflict_1', value: 0.91, threshold: 0.6 }),
          decision({ name: 'conflict_2', value: 0.44, threshold: 0.6 }),
        ]}
      />,
    )

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    expect(within(card).getByRole('meter').getAttribute('aria-label')).toBe(
      'Conflict value 0.91, threshold 0.60, disclosed',
    )
  })

  it('reports a gate whose event carried no threshold as observed, not as a pass', () => {
    render(
      <EvidenceGateCard
        decisions={[decision({ name: 'conflict_0', value: 0.95, stage: 'conflict', threshold: null })]}
      />,
    )

    const card = screen.getByRole('region', { name: 'Evidence gates' })
    expect(within(card).getByText('no threshold')).toBeTruthy()
    expect(within(card).queryByText(/vs /)).toBeNull()
  })

  it('shows the last attempt of a retried gate, not the first', () => {
    render(
      <EvidenceGateCard
        decisions={[
          decision({ name: 'evidence', value: 0.01, probability: null, threshold: 0.55 }),
          decision({ name: 'evidence', value: 0.79, probability: null, threshold: 0.55 }),
        ]}
      />,
    )

    expect(screen.getByRole('meter').getAttribute('aria-label')).toBe(
      'Evidence value 0.79, threshold 0.55, answered',
    )
    // Two attempts, not two measurements: the row must not claim a count it
    // did not fold, or a reader counts passages that are not passages.
    expect(screen.queryByText(/best of/)).toBeNull()
  })

  it('uses the value as the number when a gate publishes it without a probability', () => {
    // The evidence gate is computed, not asked for: `value` carries the mean
    // top-3 rubric grade and `probability` is null. Reading only `probability`
    // would show 0.00 against a 0.55 floor — a gate that looks blocked when it
    // cleared.
    render(
      <EvidenceGateCard
        decisions={[decision({ name: 'evidence', value: 0.72, stage: 'gate', threshold: 0.55 })]}
      />,
    )

    expect(screen.getByRole('meter').getAttribute('aria-label')).toBe(
      'Evidence value 0.72, threshold 0.55, answered',
    )
    expect(screen.getByText('0.72')).toBeTruthy()
  })
})

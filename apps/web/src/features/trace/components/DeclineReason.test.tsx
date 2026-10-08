import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Decision } from '../../../generated/types.gen'
import { questionEntities } from '../declineReason'
import { DeclineReason } from './DeclineReason'

afterEach(cleanup)

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
    latency_ms: 100,
    reasoning: null,
    stage: null,
    call_id: null,
    batch_size: null,
    threshold: null,
    ...overrides,
  }
}

/** Every gate clears — this run answered. */
const answered: Decision[] = [
  decision({ name: 'sufficient', value: 0.81, probability: 0.81, threshold: 0.05 }),
  decision({ name: 'relevance', value: 0.72, threshold: 0.6 }),
  decision({ name: 'entity_0', value: 0.66, probability: 0.66, threshold: 0.5 }),
]

describe('questionEntities', () => {
  it('reads the product name out of a question', () => {
    // Names before model codes: both regexes match "Kestrel K9" — the name
    // regex takes "Kestrel", the code regex takes "K9" — and the subject a
    // reader recognises is the name.
    expect(questionEntities('How long does a flat-to-full charge take on the Kestrel K9?')).toEqual([
      'Kestrel',
      'K9',
    ])
  })

  it('does not read the question\'s own first word as a subject', () => {
    // "Frankenstein" opens the sentence here; the entity the gate checked is
    // Victor Frankenstein, later in the string.
    expect(questionEntities('Frankenstein is not the same as Victor Frankenstein')).toEqual([
      'Victor Frankenstein',
    ])
  })

  it('skips interrogatives, honorifics and the stop words the backend also skips', () => {
    // "Mr" reaches the entity gate as its own name and the judge copes, but
    // "No retrieved passage is about Mr" is not a sentence to show a reader.
    expect(questionEntities('What does Mr. Darcy say in his first proposal?')).toEqual(['Darcy'])
  })
})

describe('DeclineReason', () => {
  it('names the entity gate and the thing nothing was found about', () => {
    render(
      <DeclineReason
        declined
        decisions={[
          decision({ name: 'sufficient', value: 0.42, probability: 0.42, threshold: 0.05 }),
          decision({ name: 'relevance', value: 0.71, threshold: 0.6 }),
          decision({ name: 'entity_0', value: 0.11, probability: 0.11, threshold: 0.5 }),
        ]}
        question="How long does a flat-to-full charge take on the Kestrel K9?"
        retrieved={[{ document_name: 'manual.md', page: 3 }]}
      />,
    )

    // The noun is the one the entity gate was actually asked about, which is
    // `Kestrel` — graph/auto.py's name regex does not fold a trailing model
    // number into the name. Saying "the Kestrel K9" would name something the
    // gate never checked.
    expect(screen.getByText('No retrieved passage is about Kestrel.')).toBeTruthy()
  })

  it('names the relevance gate without inventing an entity', () => {
    render(
      <DeclineReason
        declined
        decisions={[decision({ name: 'relevance', value: 0.22, threshold: 0.6 })]}
        question="What is the warranty policy?"
      />,
    )

    expect(
      screen.getByText('Nothing retrieved was close enough to the question to answer from.'),
    ).toBeTruthy()
  })

  it('names the sufficiency gate when that is what blocked', () => {
    render(
      <DeclineReason
        declined
        decisions={[decision({ name: 'sufficient', value: 0.02, probability: 0.02, threshold: 0.05 })]}
        question="Summarise the risk register."
      />,
    )

    expect(
      screen.getByText('What was retrieved does not cover enough of the question to answer it.'),
    ).toBeTruthy()
  })

  it('has no conflict sentence, because a conflict never causes a decline', () => {
    // The conflict check runs only after the run has decided to answer
    // (graph/auto.py), so it discloses beside an answer rather than blocking
    // one. A conflict sentence here would be a branch the pipeline cannot
    // reach, and the fixture would be testing fiction.
    render(
      <DeclineReason
        declined
        decisions={[
          decision({ name: 'sufficient', value: 0.9, probability: 0.9, threshold: 0.05 }),
          decision({ name: 'conflict_0', value: 0.94, probability: 0.94, threshold: 0.6 }),
        ]}
        question="How long is the warranty?"
      />,
    )

    expect(screen.queryByText(/disagree/i)).toBeNull()
  })

  it('says nothing when no gate blocked, rather than inventing a reason', () => {
    const { container } = render(
      <DeclineReason declined decisions={answered} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('says nothing when there are no decisions to read a gate from', () => {
    const { container } = render(
      <DeclineReason declined decisions={[]} />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('falls back to wording that needs no entity when the question names none', () => {
    render(
      <DeclineReason
        declined
        decisions={[decision({ name: 'entity_0', value: 0.09, probability: 0.09, threshold: 0.5 })]}
        question="summarise the risk register"
      />,
    )

    expect(
      screen.getByText('None of the retrieved passages is about the thing you asked about.'),
    ).toBeTruthy()
  })

  it('says nothing when the message did not decline', () => {
    // The same decisions that would name an entity gate, on a message that
    // answered: the reason belongs to the abstention, not to the decisions.
    const { container } = render(
      <DeclineReason
        declined={false}
        decisions={[decision({ name: 'entity_0', value: 0.09, probability: 0.09, threshold: 0.5 })]}
        question="How long is the warranty?"
      />,
    )
    expect(container.innerHTML).toBe('')
  })

  it('links to the gate it named', () => {
    render(
      <DeclineReason
        declined
        decisions={[decision({ name: 'relevance', value: 0.22, threshold: 0.6 })]}
        question="What is the warranty policy?"
        onShowGates={() => undefined}
      />,
    )

    expect(screen.getByRole('button', { name: 'See the relevance gate' })).toBeTruthy()
  })
})
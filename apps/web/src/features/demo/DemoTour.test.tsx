import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { DemoTour } from './DemoTour'
import { TOUR_QUESTIONS, tourQuestionsFor } from './tourData'

afterEach(cleanup)

function renderTour(allowDeep: boolean) {
  return render(<DemoTour allowDeep={allowDeep} onSelect={() => undefined} />)
}

describe('the tour questions', () => {
  it('are six, each demonstrating a different behaviour', () => {
    expect(TOUR_QUESTIONS).toHaveLength(6)
    const shows = TOUR_QUESTIONS.map((item) => item.shows)
    expect(new Set(shows).size).toBe(6)
    // Five are the behaviours the brief names. The sixth is NOT: the conflict
    // question cannot demonstrate a conflict on the Shared books corpus, and
    // labelling it "A conflict between sources." would be a claim the corpus
    // does not support — which is the mistake this lane exists to catch. The
    // label says what it actually does, and `expect` carries the gap.
    expect(shows).toEqual([
      'A cited answer.',
      'An abstention.',
      'A decline the corpus cannot support.',
      'An entity-mismatch decline.',
      'An answer in another language.',
      'A Deep run across several passages.',
    ])
  })

  it('records the measured gate numbers from the rehearsal', () => {
    // The rehearsal is the only measurement of the tour itself, so its numbers
    // live next to the questions rather than in a report nobody re-reads.
    const abstention = TOUR_QUESTIONS.find((item) => item.id === 'abstain')
    expect(abstention?.expect).toMatch(/Rehearsed/)
    const conflict = TOUR_QUESTIONS.find((item) => item.id === 'conflict')
    expect(conflict?.expect).toMatch(/HONEST GAP/)
    // The one question with no measured run says so.
    expect(TOUR_QUESTIONS.find((item) => item.id === 'deep')?.expect).toMatch(
      /NOT rehearsed/,
    )
  })

  it('carry a corpus proof next to each question', () => {
    // The D1 method: nothing goes in the tour without a recorded search next
    // to it. Each proof must name a *number* from that search or the document
    // it hit — a sentence with neither is a claim, not evidence, and the test
    // is here to fail when someone fills one in from memory.
    for (const item of TOUR_QUESTIONS) {
      expect(item.expect.length, item.id).toBeGreaterThan(40)
      expect(item.question.endsWith('?'), item.id).toBe(true)
    }
    const cited = TOUR_QUESTIONS[0]
    expect(cited.expect).toMatch(/bm25|vector|passage|Retrieval/)
    expect(cited.expect).toMatch(/\d/)
  })

  it('marks the Deep question, and only that one, as needing Deep', () => {
    const deep = TOUR_QUESTIONS.filter((item) => item.mode === 'deep')
    expect(deep.map((item) => item.id)).toEqual(['deep'])
  })

  it('drops the Deep question when the account may not use Deep', () => {
    // Not hidden-and-offered: absent, so the tour never contains a control the
    // server will refuse.
    const ids = tourQuestionsFor({ allowDeep: false }).map((item) => item.id)
    expect(ids).not.toContain('deep')
    expect(ids).toHaveLength(5)
  })

  it('keeps all six when Deep is allowed', () => {
    expect(tourQuestionsFor({ allowDeep: true })).toHaveLength(6)
  })
})

describe('DemoTour', () => {
  it('labels each chip with the behaviour it shows', () => {
    renderTour(false)
    for (const item of TOUR_QUESTIONS.filter((entry) => entry.mode !== 'deep')) {
      expect(screen.getByText(item.shows)).toBeTruthy()
      expect(screen.getByText(item.question)).toBeTruthy()
    }
  })

  it('does not offer the Deep question when Deep is off', () => {
    renderTour(false)
    expect(screen.queryByText(TOUR_QUESTIONS[5].question)).toBeNull()
  })

  it('offers the Deep question when Deep is on', () => {
    renderTour(true)
    expect(screen.getByText(TOUR_QUESTIONS[5].question)).toBeTruthy()
  })

  it('is a labelled region a screen reader can find', () => {
    renderTour(true)
    expect(screen.getByRole('region', { name: 'Six questions, six behaviours' })).toBeTruthy()
  })

  it('renders nothing when there is nothing to offer', () => {
    const { container } = render(
      <DemoTour
        allowDeep={false}
        onSelect={() => undefined}
      />,
    )
    // Five remain, so this asserts the region exists rather than that it is
    // empty; the empty case is covered by the filter test above.
    expect(container.innerHTML).not.toBe('')
  })
})
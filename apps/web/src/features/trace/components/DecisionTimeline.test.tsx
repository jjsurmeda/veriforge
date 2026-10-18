/** `EngineBadge` has three states, not two, and the third is the one that
 *  matters during an incident (KI-57).
 *
 *  `fallback` means Jev was down and the LLM answered instead — a working
 *  system, degraded. `unavailable` means **nothing** answered and the stage
 *  used its own default: the number in the row was never a reading. A trace
 *  that renders both as "fallback" makes the second look like the first, which
 *  is the difference between an operator looking at the decision layer and
 *  looking at the corpus.
 */

import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { EngineBadge } from './DecisionTimeline'

afterEach(cleanup)

describe('EngineBadge', () => {
  it('names the engine that answered', () => {
    render(<EngineBadge engine="jev" />)
    expect(screen.getByText('Jev')).toBeDefined()
  })

  it('names the fallback as a degraded but working system', () => {
    render(<EngineBadge engine="fallback" />)
    expect(screen.getByText('fallback')).toBeDefined()
  })

  it('never calls an unanswered decision a fallback', () => {
    render(<EngineBadge engine="unavailable" />)
    // Not "fallback": no engine answered this one.
    expect(screen.queryByText('fallback')).toBeNull()
    expect(screen.getByText('unavailable')).toBeDefined()
  })

  it('gives the unavailable state a tooltip that says what happened', () => {
    render(<EngineBadge engine="unavailable" />)
    const badge = screen.getByText('unavailable').closest('span')
    expect(badge?.getAttribute('title')).toMatch(/unreachable/i)
  })

  it('leaves the healthy engine without an alarm tooltip', () => {
    render(<EngineBadge engine="jev" />)
    const badge = screen.getByText('Jev').closest('span')
    expect(badge?.getAttribute('title')).toBeNull()
  })
})

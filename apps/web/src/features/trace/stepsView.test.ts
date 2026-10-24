import { describe, expect, it } from 'vitest'

import { collapseSteps } from './stepsView'

describe('collapseSteps', () => {
  it('shows a finished step once, with its duration', () => {
    const views = collapseSteps([
      { type: 'step.started', node: 'retrieve', label: 'Searching' },
      { type: 'step.completed', node: 'retrieve', label: 'Searching', duration_ms: 120 },
    ])
    expect(views).toEqual([{ node: 'retrieve', label: 'Searching', durationMs: 120 }])
  })

  it('keeps an unfinished step open and a repeated node as two rows', () => {
    const views = collapseSteps([
      { type: 'step.started', node: 'retrieve', label: 'Searching' },
      { type: 'step.completed', node: 'retrieve', label: 'Searching', duration_ms: 50 },
      { type: 'step.started', node: 'retrieve', label: 'Searching' },
    ])
    expect(views.map((v) => v.durationMs)).toEqual([50, null])
  })
})

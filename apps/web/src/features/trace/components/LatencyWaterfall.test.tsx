import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Metrics } from '../../../generated/types.gen'
import { LatencyWaterfall } from './LatencyWaterfall'

afterEach(cleanup)

function metrics(overrides: Partial<Metrics> = {}): Metrics {
  return {
    run_id: 'run-1',
    seq: 12,
    ts: '2026-10-06T03:00:00Z',
    type: 'metrics',
    latency_ms: {
      'ingress+rewrite': 900,
      retrieve: 1400,
      rerank: 300,
      sufficient: 240,
      generate: 1800,
      review: 500,
    },
    tokens_in: 1800,
    tokens_out: 260,
    credits: 42,
    context_used: 9000,
    context_window: 128000,
    faithfulness: 0.93,
    min_support: 0.81,
    ttft_ms: 2840,
    ...overrides,
  }
}

describe('LatencyWaterfall', () => {
  it('reports time to first token, and what it consists of', () => {
    render(<LatencyWaterfall metrics={metrics()} />)

    // 900 + 1400 + 300 + 240 = 2840: the pipeline before the generator, and
    // the same total the run's own clock measured.
    const terms = screen.getByText('Time to first token').closest('dl')
    expect(terms?.textContent).toBe(
      'Time to first token2840 ms=before the generator2840 ms+answer1800 ms',
    )
  })

  it('states every stage with its own millisecond value as text', () => {
    render(<LatencyWaterfall metrics={metrics()} />)

    // Read each row as a unit, so the assertion is "this stage took this long"
    // rather than two independent matches that could come from different rows.
    const rows = screen.getAllByRole('listitem').map((row) => row.textContent)
    expect(rows).toEqual([
      'ingress rewrite900 ms',
      'retrieve1400 ms',
      'rerank300 ms',
      'sufficient240 ms',
      'generate1800 ms',
      'review500 ms',
    ])
    expect(screen.getByText('total 5140 ms')).toBeTruthy()
  })

  it('orders stages as the run executes them, not alphabetically', () => {
    render(<LatencyWaterfall metrics={metrics()} />)

    const labels = screen
      .getAllByRole('listitem')
      .map((item) => item.querySelector('span')?.textContent)
    expect(labels).toEqual([
      'ingress rewrite',
      'retrieve',
      'rerank',
      'sufficient',
      'generate',
      'review',
    ])
  })

  it('has a text equivalent for the bar', () => {
    render(<LatencyWaterfall metrics={metrics()} />)

    expect(
      screen.getByRole('img').getAttribute('aria-label'),
    ).toBe(
      'Total 5140 milliseconds. Time to first token 2840 milliseconds: 2840 before the generator, 1800 generating the answer.',
    )
  })

  it('says the time was not measured rather than claiming zero', () => {
    // A run with no answer tokens (a greeting, a library listing) has no first
    // token. "0 ms" would read as instant, which is a different claim.
    render(<LatencyWaterfall metrics={metrics({ ttft_ms: null })} />)

    expect(screen.getByText('not measured')).toBeTruthy()
    expect(screen.queryByText('0 ms')).toBeNull()
  })

  it('shows no first-token line for a run that never generated', () => {
    render(
      <LatencyWaterfall
        metrics={metrics({
          latency_ms: { 'ingress+rewrite': 300, retrieve: 600 },
          ttft_ms: null,
        })}
      />,
    )

    expect(screen.queryByText('Time to first token')).toBeNull()
    expect(screen.getByText('total 900 ms')).toBeTruthy()
    expect(screen.getByRole('img').getAttribute('aria-label')).toBe(
      'Total 900 milliseconds across 2 stages.',
    )
  })

  it('keeps a stage the backend added after the ones it knows about', () => {
    render(
      <LatencyWaterfall
        metrics={metrics({ latency_ms: { 'output_guard': 90, retrieve: 500, generate: 1000 } })}
      />,
    )

    const labels = screen
      .getAllByRole('listitem')
      .map((item) => item.querySelector('span')?.textContent)
    expect(labels).toEqual(['retrieve', 'generate', 'output guard'])
  })

  it('renders nothing when there are no stages at all', () => {
    const { container } = render(<LatencyWaterfall metrics={metrics({ latency_ms: {} })} />)
    expect(container.innerHTML).toBe('')
  })
})
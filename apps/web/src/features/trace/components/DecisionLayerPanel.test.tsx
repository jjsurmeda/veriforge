import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DecisionStatsOut } from '../../../generated/types.gen'
import { DecisionLayerPanel } from './DecisionLayerPanel'

const statsMock = vi.hoisted(() => vi.fn())

vi.mock('../../../generated/sdk.gen', () => ({
  decisionStatsAdminDecisionsStatsGet: statsMock,
}))

afterEach(() => {
  cleanup()
  statsMock.mockReset()
})

function stats(overrides: Partial<DecisionStatsOut> = {}): DecisionStatsOut {
  return {
    total: 120,
    jev_count: 118,
    fallback_count: 2,
    fallback_share: 2 / 120,
    jev_latency_p50_ms: 410,
    jev_latency_p95_ms: 900,
    ingress_p95_ms: 380,
    rerank_latency_p50_ms: 260,
    rerank_latency_p95_ms: 610,
    by_decision: [{ name_or_prefix: 'sufficient', count: 40, fallback_count: 0 }],
    breaker: { state: 'closed', open_until: null },
    shadow: { sampled: 3, agree_rate: 2 / 3, recent_disagreements: [] },
    targets: { ingress_p95_ms: 600, fallback_share: 0.05 },
    ...overrides,
  }
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <DecisionLayerPanel />
    </QueryClientProvider>,
  )
}

describe('DecisionLayerPanel (read-only)', () => {
  it('reports engine mix, breaker state, rerank latency and fallback share', async () => {
    statsMock.mockResolvedValue({ data: stats() })
    renderPanel()

    await waitFor(() => expect(screen.getByText('Jev p50')).toBeTruthy())
    expect(screen.getByText('118/120')).toBeTruthy()
    expect(screen.getByText('1.7%')).toBeTruthy()
    expect(screen.getByText('closed')).toBeTruthy()
    expect(screen.getByText('260 ms')).toBeTruthy()
    expect(screen.getByText('610 ms')).toBeTruthy()
  })

  it('has no control that writes', async () => {
    statsMock.mockResolvedValue({ data: stats() })
    renderPanel()

    await waitFor(() => expect(screen.getByText('Jev p50')).toBeTruthy())
    // One control, and it only chooses the window. Nothing here can change a
    // threshold, create an invite or grant a role.
    expect(screen.queryAllByRole('button')).toHaveLength(0)
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
    expect(screen.getByRole('combobox', { name: 'Decision stats window' })).toBeTruthy()
  })

  it('says so when the window has no data, rather than drawing an empty chart', async () => {
    statsMock.mockResolvedValue({
      data: stats({
        total: 0,
        jev_count: 0,
        fallback_count: 0,
        fallback_share: 0,
        jev_latency_p50_ms: null,
        jev_latency_p95_ms: null,
        ingress_p95_ms: null,
        rerank_latency_p50_ms: null,
        rerank_latency_p95_ms: null,
        by_decision: [],
        shadow: { sampled: 0, agree_rate: 0, recent_disagreements: [] },
      }),
    })
    renderPanel()

    await waitFor(() =>
      expect(screen.getByText('No decisions in this window yet.')).toBeTruthy(),
    )
    // No stat tiles at all: a row of zeroes would read as measured.
    expect(screen.queryByText('Jev p50')).toBeNull()
  })

  it('says so when nothing has been sampled for shadow agreement', async () => {
    statsMock.mockResolvedValue({
      data: stats({ shadow: { sampled: 0, agree_rate: 0, recent_disagreements: [] } }),
    })
    renderPanel()

    await waitFor(() =>
      expect(screen.getByText(/Nothing sampled yet/)).toBeTruthy(),
    )
  })

  it('shows a dash, not zero, when rerank latency is absent', async () => {
    statsMock.mockResolvedValue({ data: stats({ rerank_latency_p50_ms: null, rerank_latency_p95_ms: null }) })
    renderPanel()

    await waitFor(() => expect(screen.getByText('Rerank p50')).toBeTruthy())
    expect(screen.getByText('Rerank p50')).toBeTruthy()
    // Two dashes: rerank p50 and p95. Jev's real values are still numbers.
    expect(screen.getAllByText('—')).toHaveLength(2)
  })

  it('reports a read failure in the panel rather than silently showing nothing', async () => {
    statsMock.mockResolvedValue({ error: { message: 'nope' } })
    renderPanel()

    await waitFor(() =>
      expect(screen.getByRole('alert')).toBeTruthy(),
    )
    expect(screen.getByText('Decision statistics could not be loaded.')).toBeTruthy()
  })

  it('re-queries when the window changes', async () => {
    statsMock.mockResolvedValue({ data: stats() })
    renderPanel()

    await waitFor(() => expect(statsMock).toHaveBeenCalled())
    const select = screen.getByRole('combobox', { name: 'Decision stats window' })
    // The select is a native control; dispatch through the DOM value setter.
    const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')?.set
    setter?.call(select, '168')
    select.dispatchEvent(new Event('change', { bubbles: true }))

    await waitFor(() => expect(statsMock).toHaveBeenCalledTimes(2))
  })
})
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../../generated/sdk.gen', () => ({
  getLibraryLibraryGet: vi.fn(async () => ({ data: { documents: [], starter_questions: [] } })),
  listChatDocumentsChatsChatIdDocumentsGet: vi.fn(async () => ({ data: [] })),
  uploadChatDocumentChatsChatIdDocumentsPost: vi.fn(async () => ({ data: {} })),
  deleteDocumentDocumentsDocumentIdDelete: vi.fn(async () => ({ data: undefined })),
  reindexDocumentDocumentsDocumentIdReindexPost: vi.fn(async () => ({ data: undefined })),
  patchDocumentDocumentsDocumentIdPatch: vi.fn(async () => ({ data: undefined })),
  listChunksDocumentsDocumentIdChunksGet: vi.fn(async () => ({ data: [] })),
}))

vi.mock('@tanstack/react-router', () => ({
  Link: ({ children, to }: { children: React.ReactNode; to: string }) => <a href={to}>{children}</a>,
}))

const { TracePanel } = await import('./TracePanel')
const { TooltipProvider } = await import('../../../components/ui/primitives')

Element.prototype.scrollIntoView = () => undefined

function renderPanel(props: Partial<React.ComponentProps<typeof TracePanel>> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <TooltipProvider>
      <QueryClientProvider client={client}>
        <TracePanel
          steps={[]}
          decisions={[]}
          thinking=""
          streaming={false}
          chunks={[]}
          metrics={null}
          hold={false}
          chatId="chat-1"
          viewerDocumentId={null}
          open
          {...props}
        />
      </QueryClientProvider>
    </TooltipProvider>,
  )
}

afterEach(cleanup)

describe('workspace panel empty states', () => {
  it('Sources uses PanelEmpty when the chat has no documents', async () => {
    renderPanel()

    fireEvent.click(screen.getByRole('tab', { name: 'Sources' }))

    expect(await screen.findByText('Add sources to this chat.')).toBeTruthy()
    expect(screen.getByText('PDF, DOCX, MD, TXT, up to 20 MB.')).toBeTruthy()
  })

  it('Citations, Trace and Metrics each use PanelEmpty', () => {
    renderPanel()

    fireEvent.click(screen.getByRole('tab', { name: /^Citations/ }))
    expect(screen.getByText('No citations yet.')).toBeTruthy()
    expect(
      screen.getByText('The evidence behind an answer appears here once a run retrieves it.'),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Trace' }))
    expect(screen.getByText('No run yet.')).toBeTruthy()
    expect(
      screen.getByText('Decisions and reasoning stream here while a run is in flight.'),
    ).toBeTruthy()

    fireEvent.click(screen.getByRole('tab', { name: 'Metrics' }))
    expect(screen.getByText('No metrics yet.')).toBeTruthy()
    expect(
      screen.getByText('Latency, tokens, credits and scores land when the run completes.'),
    ).toBeTruthy()
  })

  // Item 6: a lost replay leaves the same empty arrays as a chat that has
  // never run, so "No run yet." was a wrong claim about a run that exists.
  it('Trace says the replay was lost instead of "No run yet."', () => {
    const onRetryTrace = vi.fn()
    renderPanel({ traceStatus: 'connection_lost', onRetryTrace })

    fireEvent.click(screen.getByRole('tab', { name: 'Trace' }))

    expect(screen.getByText('This trace could not be replayed.')).toBeTruthy()
    expect(screen.queryByText('No run yet.')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Reconnect' }))
    expect(onRetryTrace).toHaveBeenCalled()
  })
})


describe('trace and metrics content (KI-22)', () => {
  const decisions = [
    { name: 'evidence', engine: 'jev', latency_ms: 12, value: 0.8, probability: 0.8, threshold: 0.5, stage: 'gate', call_id: 'c1' },
    { name: 'guard_pii', engine: 'jev', latency_ms: 9, value: 0.1, probability: 0.1, threshold: 0.5, stage: 'ingress', call_id: 'c0' },
  ] as never

  it('shows each step once and the evidence gate once', () => {
    renderPanel({
      steps: [
        { type: 'step.started', node: 'retrieve', label: 'Searching' },
        { type: 'step.completed', node: 'retrieve', label: 'Searching', duration_ms: 1500 },
      ],
      decisions,
    })

    expect(screen.getAllByText('Searching')).toHaveLength(1)
    expect(screen.getByText('1.5 s')).toBeTruthy()
    // The gate lives in the Evidence gates card, not again in the timeline.
    expect(screen.getAllByText('Evidence')).toHaveLength(1)
    expect(screen.queryByText('Evidence gate')).toBeNull()
    expect(screen.getByText('Ingress')).toBeTruthy()
  })

  it('says a failed run failed', () => {
    renderPanel({ failure: 'The run could not finish. Try again.' })
    expect(screen.getByText(/This run failed/)).toBeTruthy()
    expect(screen.queryByText('No run yet.')).toBeNull()
  })

  it('Metrics names the run, scales units and links the decision layer', () => {
    renderPanel({
      started: { type: 'run.started', mode: 'deep', model: 'm-1', source: 'upload', run_id: 'r1' },
      selectedMessage: { id: 'm', chat_id: 'c', role: 'assistant', content: '', status: 'complete', created_at: '', run_id: 'r1', metrics: { reranker: 'jev' } },
      metrics: { type: 'metrics', latency_ms: { retrieve: 400, generate: 12000 }, tokens_in: 4000, tokens_out: 1710, credits: 3, context_used: 5000, context_window: 128000, faithfulness: 0.9, min_support: 0.8, ttft_ms: 700 },
    })
    fireEvent.click(screen.getByRole('tab', { name: 'Metrics' }))

    expect(screen.getByText('Deep')).toBeTruthy()
    expect(screen.getByText('jev')).toBeTruthy()
    expect(screen.getByText('12.4 s')).toBeTruthy()
    expect(screen.getByText('5,710')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'System-wide decision layer' }).getAttribute('href')).toBe('/decision-layer')
  })

  it('shows live on the Trace tab itself and drops the Expand button below xl', () => {
    renderPanel({ streaming: true })
    expect(screen.getByRole('tab', { name: /Trace/ }).querySelector('[aria-label="live"]')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Expand workspace panel' }).className).toContain('hidden')
  })
})

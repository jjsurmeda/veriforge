import type { Page, Route } from '@playwright/test'

/** Browser-side API mock for the workspace specs: every call the chat view
 *  makes is fulfilled by `page.route`, so no backend, model call or credit is
 *  involved. Run the dev server with `npm run dev -- --port <p>` and point
 *  PLAYWRIGHT_BASE_URL at it. */

const T = '2026-10-24T10:00:00Z'

type Ev = Record<string, unknown>
const ev = (runId: string, seq: number, rest: Ev): Ev => ({ run_id: runId, seq, ts: T, ...rest })

export type Scenario = 'answer' | 'abstain' | 'failed' | 'messages-loading' | 'messages-error'

const CHUNK = {
  chunk_id: 'ch1', document_id: 'd1', document_name: 'warranty.pdf', page: 4,
  excerpt: 'The battery is covered for 24 months from purchase.', rerank_score: 0.91,
  source_type: 'document',
}

function runEvents(runId: string, scenario: Scenario): Ev[] {
  const base: Ev[] = [
    ev(runId, 1, { type: 'run.started', mode: 'deep', source: 'upload', model: 'anthropic/claude-sonnet', settings_version: 3 }),
    ev(runId, 2, { type: 'step.started', node: 'retrieve', label: 'Searching your sources' }),
    ev(runId, 3, { type: 'step.completed', node: 'retrieve', label: 'Searching your sources', duration_ms: 1420 }),
    ev(runId, 4, { type: 'decision', name: 'guard_pii', engine: 'jev', latency_ms: 9, value: 0.1, probability: 0.1, threshold: 0.5, stage: 'ingress', call_id: 'c0' }),
    ev(runId, 5, { type: 'decision', name: 'evidence', engine: 'jev', latency_ms: 31, value: 0.82, probability: 0.82, threshold: 0.5, stage: 'gate', call_id: 'c1' }),
    ev(runId, 6, { type: 'retrieval', chunks: [CHUNK] }),
  ]
  if (scenario === 'failed') return [...base.slice(0, 3), ev(runId, 7, { type: 'run.failed', error_code: 'provider_unavailable', message: 'down' })]
  if (scenario === 'abstain') {
    return [...base, ev(runId, 7, { type: 'abstain', found_summary: 'A warranty page.', missing_summary: 'Mars helium.', offered_actions: ['web', 'deep'] }),
      ev(runId, 8, { type: 'run.completed', message_id: 'm2' })]
  }
  return [...base,
    ev(runId, 7, { type: 'answer.delta', text: 'The battery is covered for 24 months [1].' }),
    ev(runId, 8, { type: 'metrics', latency_ms: { retrieve: 1420, rerank: 310, evidence: 240, generate: 11800, review: 700 }, ttft_ms: 2100, tokens_in: 4210, tokens_out: 1500, credits: 12.4, context_used: 5710, context_window: 128000, faithfulness: 0.93, min_support: 0.81 }),
    ev(runId, 9, { type: 'run.completed', message_id: 'm2' })]
}

export async function mockApi(page: Page, scenario: Scenario = 'answer'): Promise<void> {
  const runId = `run-${scenario}`
  const json = (route: Route, body: unknown, status = 200) =>
    route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

  const assistant = {
    id: 'm2', chat_id: 'c1', role: 'assistant', created_at: T, run_id: runId,
    content: scenario === 'abstain' ? 'I could not find that in your sources.' : scenario === 'failed' ? '' : 'The battery is covered for 24 months [1].',
    status: scenario === 'abstain' ? 'abstained' : scenario === 'failed' ? 'failed' : 'complete',
    citations: scenario === 'answer' ? [{ n: 1, chunk_id: 'ch1', document_id: 'd1', document_name: 'warranty.pdf', page: 4, excerpt: CHUNK.excerpt, rerank_score: 0.91, verdict: 'partial', p_supported: 0.64 }] : [],
    metrics: { reranker: 'jev' },
  }
  const messages = [{ id: 'm1', chat_id: 'c1', role: 'user', content: 'How long is the battery covered?', status: 'complete', created_at: T, citations: [], metrics: null, run_id: null }, assistant]

  await page.route((url) => /^\/(auth|me|chats|runs|models|model-roles|library|documents|web-sources|rerankers)(\/|$)/.test(url.pathname) && !url.pathname.startsWith('/src/'), async (route) => {
    const url = new URL(route.request().url())
    if (route.request().resourceType() === 'document') return route.fallback()
    const p = url.pathname
    if (p === '/auth/refresh') return json(route, { access_token: 'mock' })
    if (p === '/auth/demo/limits') return json(route, { is_demo: false })
    if (p === '/me') return json(route, { id: 'u1', email: 'sam@example.com', role: 'user' })
    if (p === '/me/quota') return json(route, { blocked: false, estimate: 1, limit_5h: 50, remaining_5h: 40, used_5h: 10, reset_at_5h: '2026-10-24T15:00:00Z', limit_month: 100, mode: 'auto', remaining_month: 80, reset_at_month: '2026-11-01T00:00:00Z', used_month: 20 })
    if (p === '/chats') return json(route, [{ id: 'c1', title: 'Battery warranty', pinned: false, model_id: null, starter_questions: [], created_at: T, active_run_id: null }])
    if (p === '/chats/c1') return json(route, { id: 'c1', title: 'Battery warranty', pinned: false, model_id: null, starter_questions: [], created_at: T, active_run_id: null })
    if (p === '/chats/c1/messages') {
      if (scenario === 'messages-error') return json(route, { error_code: 'server_error', message: 'boom' }, 500)
      if (scenario === 'messages-loading') return new Promise(() => undefined)
      return json(route, messages)
    }
    if (p === '/chats/c1/documents') return json(route, [])
    if (p === '/models') return json(route, [])
    if (p === '/library') return json(route, { documents: [], starter_questions: [] })
    if (p === `/runs/${runId}/stream`) {
      const body = runEvents(runId, scenario).map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
      return route.fulfill({ status: 200, contentType: 'text/event-stream', body })
    }
    return json(route, [])
  })
}

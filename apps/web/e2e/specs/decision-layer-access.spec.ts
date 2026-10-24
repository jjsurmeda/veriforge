import { expect, test, type Page } from '@playwright/test'

// API fully mocked in the browser: no stack, no model calls (slice C).
// Run with PLAYWRIGHT_BASE_URL=http://localhost:5203 against `vite`.

const stats = (withDisagreements: boolean) => ({
  total: 4830,
  jev_count: 4830,
  fallback_count: 0,
  fallback_share: 0,
  jev_latency_p50_ms: 509,
  jev_latency_p95_ms: 981,
  ingress_p95_ms: 500,
  rerank_latency_p50_ms: 786,
  rerank_latency_p95_ms: 1204,
  by_decision: [
    { name_or_prefix: 'passage_relevance', count: 3195, fallback_count: 0 },
    { name_or_prefix: 'claim_verdicts', count: 416, fallback_count: 0 },
  ],
  breaker: { state: 'closed', open_until: null },
  shadow: {
    sampled: 244,
    agree_rate: 0.86,
    recent_disagreements: withDisagreements
      ? [{ run_id: 'run-xyz', decision: 'intent', jev_answer: { value: 'lookup' }, fallback_answer: { value: 'summarize' }, created_at: '2026-10-24T10:00:00Z' }]
      : [],
  },
  targets: { ingress_p95_ms: 600, fallback_share: 0.05 },
})

const rerankers = [
  { id: 'jev', label: 'Jev', kind: 'decision-model', calibrated: true, cost_per_1k_queries_usd: 1.162, cost_note: '', is_default: true, key_present: true },
  { id: 'cohere', label: 'Cohere Rerank', kind: 'api', calibrated: false, cost_per_1k_queries_usd: 2, cost_note: '', is_default: false, key_present: true },
]

async function mockApi(page: Page, role: 'user' | 'admin') {
  const calls: string[] = []
  const patches: unknown[] = []
  await page.route('**/*', async (route) => {
    const req = route.request()
    const type = req.resourceType()
    if (type !== 'fetch' && type !== 'xhr') return route.fallback()
    const { pathname } = new URL(req.url())
    calls.push(`${req.method()} ${pathname}`)
    const json = (body: unknown, status = 200) => route.fulfill({ status, json: body })
    if (pathname === '/auth/refresh') return json({ access_token: 't' })
    if (pathname === '/me') return json({ id: 'u1', email: `${role}@example.com`, role, status: 'active', plan_id: 'p', credits_5h: 1, credits_month: 1 })
    if (pathname === '/decisions/stats') return json(stats(false))
    if (pathname === '/admin/decisions/stats') return json(stats(true))
    if (pathname === '/rerankers') return json(rerankers)
    if (pathname === '/admin/settings' && req.method() === 'PATCH') {
      patches.push(req.postDataJSON())
      return json({ version: 2, active: true, data: {} })
    }
    if (pathname === '/admin/settings') return json({ version: 1, active: true, data: { retrieval: { reranker: 'jev' } } })
    if (pathname === '/me/quota')
      return json({ blocked: false, estimate: 0, limit_5h: 100, limit_month: 1000, mode: 'normal', remaining_5h: 100, remaining_month: 1000, reset_at_5h: '2026-10-24T18:00:00Z', reset_at_month: '2026-11-01T00:00:00Z', used_5h: 0, used_month: 0 })
    return json([])
  })
  return { calls, patches }
}

const shot = async (page: Page, name: string) => {
  const dir = process.env.SHOTS_DIR
  if (!dir) return
  const width = page.viewportSize()?.width ?? 0
  for (const scheme of ['light', 'dark'] as const) {
    await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), scheme)
    await page.waitForTimeout(500) // theme colour transition
    await page.screenshot({ path: `${dir}/${name.replace(/-(desktop-1440|mobile-390)$/, '')}-${width}-${scheme}.png`, fullPage: true })
  }
}

test('an ordinary user reads the Decision layer page without calling /admin', async ({ page }, info) => {
  const { calls } = await mockApi(page, 'user')
  await page.goto('/decision-layer')
  await expect(page.getByRole('heading', { name: 'Decision layer', level: 1 })).toBeVisible()
  await expect(page.getByText('Judge fallback share')).toBeVisible()
  await expect(page.getByText(/visible to administrators only/)).toBeVisible()
  expect(calls).toContain('GET /decisions/stats')
  expect(calls.filter((c) => c.includes('/admin/'))).toEqual([])
  await shot(page, `decision-layer-user-${info.project.name}`)
})

test('admin picks a reranker, saves it, and reads the stored benchmarks', async ({ page }, info) => {
  const { patches } = await mockApi(page, 'admin')
  await page.goto('/admin')
  await page.getByLabel('Reranker', { exact: true }).selectOption('cohere')
  await shot(page, `admin-settings-${info.project.name}`)
  await page.getByRole('button', { name: 'Create version' }).click()
  await expect.poll(() => patches.length).toBe(1)
  expect(JSON.stringify(patches[0])).toContain('"reranker":"cohere"')

  const wide = (page.viewportSize()?.width ?? 0) >= 1024
  if (wide) await page.getByRole('button', { name: 'Benchmarks' }).click()
  else await page.getByRole('combobox', { name: 'Section' }).selectOption('benchmarks')
  await expect(page.getByText('31/33 (0.939)')).toBeVisible()
  await expect(page.getByText(/20261018-195514\.json/)).toBeVisible()
  await shot(page, `admin-benchmarks-${info.project.name}`)
})

test('a non-admin on /admin gets a link home', async ({ page }, info) => {
  await mockApi(page, 'user')
  await page.goto('/admin')
  await expect(page.getByRole('link', { name: 'Back to chats' })).toBeVisible()
  await shot(page, `admin-as-user-${info.project.name}`)
})

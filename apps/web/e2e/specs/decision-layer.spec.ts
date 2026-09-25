import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

import { grantAdmin } from '../support/admin'
import { createChat, login, signUp } from '../support/auth'
import { accessToken, startSeededRun } from '../support/live'
import { makeTestUser, type TestUser } from '../support/seed'

async function createAdmin(request: APIRequestContext): Promise<{ user: TestUser; token: string }> {
  const user = makeTestUser()
  const response = await request.post('/auth/signup', {
    data: { email: user.email, password: user.password },
  })
  expect(response.ok()).toBeTruthy()
  grantAdmin(user.email)
  return { user, token: await accessToken(request, user) }
}

async function setEngineMode(
  request: APIRequestContext,
  token: string,
  mode: 'auto' | 'fallback_only',
): Promise<void> {
  const response = await request.patch('/admin/settings', {
    headers: { Authorization: `Bearer ${token}` },
    data: { decision_engine_mode: mode },
  })
  expect(response.ok()).toBeTruthy()
}

function fixtureStream(runId: string): string {
  const now = '2026-09-25T00:00:00Z'
  const decisions = [
    { name: 'guard_injection', value: 0.03, probability: 0.03, threshold: 0.85 },
    { name: 'guard_jailbreak', value: 0.01, probability: 0.01, threshold: 0.85 },
    { name: 'guard_pii', value: 0.02, probability: 0.02, threshold: 0.70 },
    { name: 'off_topic', value: 0.01, probability: 0.01, threshold: 0.80 },
    {
      name: 'intent',
      value: 'lookup',
      probabilities: { lookup: 0.82, summarize: 0.15, chitchat: 0.03 },
    },
    {
      name: 'source',
      value: 'upload',
      probabilities: { upload: 0.82, web: 0.15, both: 0.03 },
    },
    {
      name: 'complexity',
      value: 'single',
      probabilities: { single: 0.82, multi: 0.18 },
    },
    {
      name: 'risk',
      value: 'low',
      probabilities: { low: 0.82, high: 0.18 },
    },
    { name: 'lexical_weight', value: 0.35 },
  ]
  const events = [
    {
      type: 'run.started',
      run_id: runId,
      seq: 1,
      ts: now,
      mode: 'auto',
      source: 'upload',
      model: 'openai/gpt-4o-mini',
      settings_version: null,
    },
    ...decisions.map((decision, index) => ({
      type: 'decision',
      run_id: runId,
      seq: index + 2,
      ts: now,
      engine: 'jev',
      latency_ms: 214,
      stage: 'ingress',
      call_id: 'fixture-call',
      batch_size: decisions.length,
      threshold: null,
      ...decision,
    })),
    { type: 'answer.delta', run_id: runId, seq: 11, ts: now, text: 'Fixture answer' },
  ]
  return events
    .map((event) => `id: ${event.seq}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`)
    .join('')
}

async function installAutoFixture(page: Page): Promise<void> {
  await page.route(/\/chats\/[^/?]+$/, async (route) => {
    const response = await route.fetch()
    const body = (await response.json()) as Record<string, unknown>
    await route.fulfill({ response, json: { ...body, active_run_id: 'fixture-decision-run' } })
  })
  await page.route('**/chats/*/runs', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({ run_id: 'fixture-decision-run', message_id: 'fixture-message' }),
    })
  })
  await page.route('**/runs/**', async (route) => {
    if (!route.request().url().includes('/stream')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'text/event-stream',
      body: fixtureStream('fixture-decision-run'),
    })
  })
}

test.describe.configure({ mode: 'serial' })

test('marks fallback decisions and restores auto mode', async ({ page, request }) => {
  const admin = await createAdmin(request)
  try {
    await setEngineMode(request, admin.token, 'fallback_only')
    const user = makeTestUser()
    await signUp(page, user)
    const { chatId } = await startSeededRun(
      request,
      user,
      'Summarize the warranty terms and explain the exclusions in detail.',
      'auto',
    )

    await page.goto(`/chat/${chatId}`)
    await expect(page.getByRole('heading', { name: 'Ingress' })).toBeVisible({ timeout: 110_000 })
    await expect(page.getByTitle('Jev unavailable — answered by LLM fallback').first()).toBeVisible()
    await page.screenshot({ path: 'e2e/screenshots/decision-layer-trace-light.png', fullPage: true })
    await page.getByRole('button', { name: 'Switch to dark theme' }).click()
    await expect(page.getByRole('button', { name: 'Switch to light theme' })).toBeVisible()
    await page.screenshot({ path: 'e2e/screenshots/decision-layer-trace-dark.png', fullPage: true })
    await page.getByRole('button', { name: 'Switch to light theme' }).click()
  } finally {
    await setEngineMode(request, admin.token, 'auto')
  }
})

test('groups a faked auto ingress call with a threshold meter', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)
  await installAutoFixture(page)

  await page.getByRole('textbox', { name: 'Question' }).fill('What does the warranty cover?')
  await page.getByRole('button', { name: 'Send' }).click()
  await page.reload()

  await expect(page.getByRole('heading', { name: 'Ingress' })).toBeVisible()
  await expect(page.getByText('1 Jev call · 9 questions · 214 ms')).toBeVisible()
  const meter = page.getByRole('meter').first()
  await expect(meter).toBeVisible()
  await expect(meter).toHaveAttribute('aria-label', /threshold/)
})

test('renders admin decision stats and breaker status', async ({ page, request }) => {
  const admin = await createAdmin(request)
  await login(page, admin.user)
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Decision layer' }).click()

  await expect(page.getByRole('heading', { name: 'Decision layer' })).toBeVisible()
  await expect(page.getByText('Fallback share')).toBeVisible()
  await expect(page.getByText('Circuit breaker')).toBeVisible()
  await expect(page.getByText(/closed|open|half open/)).toBeVisible()
  const switchToLight = page.getByRole('button', { name: 'Switch to light theme' })
  if (await switchToLight.count()) await switchToLight.click()
  await expect(page.getByRole('button', { name: 'Switch to dark theme' })).toBeVisible()
  await page.screenshot({ path: 'e2e/screenshots/decision-layer-admin-light.png', fullPage: true })
  await page.getByRole('button', { name: 'Switch to dark theme' }).click()
  await expect(page.getByRole('button', { name: 'Switch to light theme' })).toBeVisible()
  await page.screenshot({ path: 'e2e/screenshots/decision-layer-admin-dark.png', fullPage: true })
})

import { expect, test, type Page } from '@playwright/test'

import { mockApi } from '../support/mockApi'

async function openPanel(page: Page) {
  // Closed by default below 1024px, open beside the thread above it.
  const toggle = page.getByRole('button', { name: 'Toggle workspace panel' })
  await toggle.waitFor()
  if ((await toggle.getAttribute('aria-pressed')) === 'false') await toggle.click()
}

// Slice B (audit F-5, F-16..F-30). Every call is mocked in the browser
// (support/mockApi.ts): no backend, no model call.

test('Trace shows each step and the evidence gate once, and Metrics names the run', async ({ page }) => {
  await mockApi(page, 'answer')
  await page.goto('/chat/c1')
  await openPanel(page)
  await page.getByRole('tab', { name: 'Trace' }).click()
  await expect(page.getByText('Searching your sources')).toHaveCount(1)
  await expect(page.getByRole('heading', { name: 'Evidence gates' })).toHaveCount(1)
  await expect(page.getByText('1.4 s').first()).toBeVisible()

  await page.getByRole('tab', { name: 'Metrics' }).click()
  const run = page.getByRole('region', { name: 'This run' })
  await expect(run.getByText('Deep')).toBeVisible()
  await expect(run.getByText('anthropic/claude-sonnet')).toBeVisible()
  await expect(run.getByText('jev')).toBeVisible()
  await expect(page.getByText('5,710').first()).toBeVisible()
  await page.getByRole('link', { name: 'System-wide decision layer' }).click()
  await expect(page).toHaveURL(/\/decision-layer$/)
})

test('Citations tab shows the reviewer verdict as text with its support', async ({ page }) => {
  await mockApi(page, 'answer')
  await page.goto('/chat/c1')
  await openPanel(page)
  await page.getByRole('tab', { name: /^Citations/ }).click()
  const panel = page.getByRole('complementary', { name: 'Evidence workspace' })
  await expect(panel.getByText('partially supported')).toBeVisible()
  await expect(panel.getByText(/support 0\.64/)).toBeVisible()
})

test('abstain actions come from abstain.offered_actions', async ({ page }) => {
  await mockApi(page, 'abstain')
  await page.goto('/chat/c1')
  await expect(page.getByRole('button', { name: /Search the web/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /Run Deep/ })).toBeVisible()
})

test('a failed run says so in danger styling and in the Trace', async ({ page }) => {
  await mockApi(page, 'failed')
  await page.goto('/chat/c1')
  await openPanel(page)
  await page.getByRole('tab', { name: 'Trace' }).click()
  await expect(page.getByText(/This run failed/)).toBeVisible()
  await expect(page.getByText('No run yet.')).toHaveCount(0)
})

test('a thread that is loading or failed never claims it is empty', async ({ page }) => {
  await mockApi(page, 'messages-error')
  await page.goto('/chat/c1')
  await expect(page.getByText(/messages could not be read/)).toBeVisible()
  await expect(page.getByText('Ask anything to start the conversation.')).toHaveCount(0)
})

test('the workspace tabs fit a 400px panel and Escape closes the drawer at 390', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await mockApi(page, 'answer')
  await page.goto('/chat/c1')
  await openPanel(page)
  const panel = page.getByRole('complementary', { name: 'Evidence workspace' })
  await expect(panel).toBeVisible()
  const tabs = panel.getByRole('tablist')
  const overflow = await tabs.evaluate((el) => el.scrollWidth > el.clientWidth)
  expect(overflow).toBe(false)
  await panel.getByRole('tab', { name: 'Trace' }).focus()
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
})

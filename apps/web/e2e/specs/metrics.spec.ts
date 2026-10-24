import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

const question = 'Summarize the warranty terms and explain the exclusions in detail.'

test('shows the run mode, the latency waterfall and usage metrics', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(request, user, question, 'deep')

  await page.goto(`/chat/${chatId}`)
  const metricsTab = page.getByRole('tab', { name: 'Metrics' })
  await expect(metricsTab).toBeVisible({ timeout: 30_000 })
  await metricsTab.click()

  await expect(page.getByText('Where the time went')).toBeVisible({ timeout: 110_000 })
  await expect(page.getByRole('region', { name: 'This run' })).toBeVisible()
  await expect(page.getByText('Faithfulness', { exact: true })).toBeVisible()
  await expect(page.getByText('Tokens', { exact: true })).toBeVisible()
  await expect(page.getByText('Credits', { exact: true })).toBeVisible()
  await expect(page.getByText('Context used')).toBeVisible()
})

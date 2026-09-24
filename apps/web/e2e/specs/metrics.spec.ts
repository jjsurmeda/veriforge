import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

const question = 'Summarize the warranty terms and explain the exclusions in detail.'

test('shows the latency waterfall and answer usage metrics', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(request, user, question, 'deep')

  await page.goto(`/chat/${chatId}`)
  const metricsTab = page.getByRole('button', { name: 'Metrics' })
  await expect(metricsTab).toBeVisible({ timeout: 30_000 })
  await metricsTab.click()

  await expect(page.getByText('Latency by stage')).toBeVisible({ timeout: 110_000 })
  await expect(page.getByText('Answer scores')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Usage' })).toBeVisible()
  await expect(page.getByText(/faithfulness/)).toBeVisible()
  await expect(page.getByText(/tokens in/)).toBeVisible()
  await expect(page.getByText(/credits/).last()).toBeVisible()
  await expect(page.getByText(/context/).last()).toBeVisible()
})

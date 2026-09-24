import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

const question = 'What does a solid red LED mean, and which fault code indicates blade motor overcurrent?'

test('renders three follow-ups and starts another run', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(request, user, question)

  await page.goto(`/chat/${chatId}`)
  const row = page.getByText('Suggested follow-ups:').locator('..')
  await expect(row).toBeVisible({ timeout: 110_000 })
  await expect(row.getByRole('button')).toHaveCount(3)

  await row.getByRole('button').first().click()
  await expect(page.getByRole('button', { name: 'Stop' })).toBeVisible()
})

import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

test('cancels a run and preserves partial answer text', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(
    request,
    user,
    'Compare the warranty coverage for the cutting blade, the battery, and accidental damage.',
    'fast',
  )

  await page.goto(`/chat/${chatId}`)
  const stop = page.getByRole('button', { name: 'Stop' })
  await expect(stop).toBeVisible({ timeout: 30_000 })
  await expect(page.locator('main .whitespace-pre-wrap').nth(1)).not.toHaveText('', {
    timeout: 60_000,
  })
  await stop.click()

  const messages = page.locator('main > div:first-child > div > div.px-4')
  const last = messages.last()
  await expect(last).toContainText('Cancelled', { timeout: 30_000 })
  const text = (await last.innerText()).replace('Veriforge', '').replace('Cancelled', '').trim()
  expect(text).not.toBe('')
  await page.screenshot({ path: 'e2e/screenshots/e2e-cancel-mid-stream.png', fullPage: true })
})

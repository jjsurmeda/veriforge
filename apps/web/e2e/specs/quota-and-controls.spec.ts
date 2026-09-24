import { expect, test } from '@playwright/test'

import { createChat, setComposerMode, setComposerSource, signUp } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('shows quota windows and keeps the picker catalogue bounded', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  await expect(page.getByRole('group', { name: '5h quota' })).toContainText(/5h.*\/.*resets/)
  await expect(page.getByRole('group', { name: 'month quota' })).toContainText(/month.*\/.*resets/)

  const model = page.locator('select').first()
  await expect(model.locator('option')).toHaveCount(2)
  await expect(model.locator('option')).toHaveText([
    'anthropic/claude-haiku-4.5',
    'openai/gpt-4o-mini',
  ])

  await setComposerMode(page, 'fast')
  await setComposerSource(page, 'upload')
  await expect(page.locator('select').nth(1)).toHaveValue('fast')
  await expect(page.locator('select').nth(2)).toHaveValue('upload')

  await page.screenshot({ path: 'e2e/screenshots/e2e-quota-controls.png', fullPage: true })
})

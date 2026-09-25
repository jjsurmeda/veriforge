import { expect, test } from '@playwright/test'

import { createChat, setComposerMode, setComposerSource, signUp } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('shows quota windows and keeps the picker catalogue bounded', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  const quota = page.getByRole('button', { name: 'Credit quota details' }).last()
  await quota.click()
  await expect(page.getByRole('group', { name: '5h quota' })).toContainText(/5h.*\/.*resets/i)
  await expect(page.getByRole('group', { name: 'month quota' })).toContainText(/month.*\/.*resets/i)
  await page.keyboard.press('Escape')

  const settings = page.getByRole('button', { name: 'Run settings' }).first()
  await settings.click()
  const settingsDialog = page.getByRole('dialog')
  const model = settingsDialog.getByRole('combobox', { name: 'Model' })
  await model.click()
  const modelOptions = page.getByRole('option')
  await expect(modelOptions).toHaveCount(2)
  await expect(modelOptions).toContainText([
    'anthropic/claude-haiku-4.5',
    'openai/gpt-4o-mini',
  ])
  await page.keyboard.press('Escape')

  await setComposerMode(page, 'fast')
  await setComposerSource(page, 'upload')
  await expect(page.locator('button[role="combobox"][aria-label="Run mode"]:visible').last()).toContainText('Fast')
  await expect(page.locator('button[role="combobox"][aria-label="Run source"]:visible').last()).toContainText('Upload')

  await page.screenshot({ path: 'e2e/screenshots/e2e-quota-controls.png', fullPage: true })
})

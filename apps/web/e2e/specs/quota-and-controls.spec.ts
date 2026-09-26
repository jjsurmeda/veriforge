import { expect, test } from '@playwright/test'

import { createChat, setComposerMode, setComposerSource, signUp, sidebar } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('shows quota windows in the profile menu and keeps the picker catalogue bounded', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  const model = page.getByRole('button', { name: 'Model', exact: true })
  await model.click()
  const modelOptions = page.getByRole('option')
  await expect(modelOptions).toHaveCount(2)
  await expect(modelOptions).toContainText(['claude-haiku-4.5', 'gpt-4o-mini'])
  await page.keyboard.press('Escape')

  await expect(page.getByRole('button', { name: 'Deep', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('button', { name: 'Web', exact: true })).toHaveAttribute('aria-pressed', 'false')
  await setComposerMode(page, true)
  await setComposerSource(page, true)
  await expect(page.getByRole('button', { name: 'Deep', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('button', { name: 'Web', exact: true })).toHaveAttribute('aria-pressed', 'true')

  // Credits live in the profile popup, which is in the sidebar — a drawer
  // below 1024px — so this runs last and never has to close it again.
  await sidebar(page).getByRole('button', { name: 'Profile menu' }).click()
  await expect(page.getByRole('group', { name: '5h quota' })).toContainText(/5h.*\/.*resets/i)
  await expect(page.getByRole('group', { name: 'month quota' })).toContainText(/month.*\/.*resets/i)
  await page.keyboard.press('Escape')

  await page.screenshot({ path: 'e2e/screenshots/e2e-quota-controls.png', fullPage: true })
})

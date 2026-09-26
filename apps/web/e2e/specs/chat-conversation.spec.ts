import { expect, test } from '@playwright/test'

import { createChat, openNavigation, signUp, sidebar } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('the sidebar lists chats and nothing else', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  await openNavigation(page)
  await expect(sidebar(page).getByText('Chats')).toBeVisible()
  await expect(sidebar(page).getByRole('button', { name: /^Library$/ })).toHaveCount(0)
  await expect(sidebar(page).getByText('Include Library')).toHaveCount(0)
  await page.screenshot({ path: 'e2e/screenshots/e2e-chat-conversation.png', fullPage: true })
})

test('accepts the documented veriforge.test signup domain', async ({ page }) => {
  const user = makeTestUser('veriforge.test')
  await signUp(page, user)
})

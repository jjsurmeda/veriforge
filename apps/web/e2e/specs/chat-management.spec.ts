import { expect, test } from '@playwright/test'

import { createChat, signUp } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('creates and deletes chats from the sidebar', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)
  await createChat(page)

  const rows = page.locator('aside nav > div')
  await expect(rows).toHaveCount(2)

  await rows.first().hover()
  await rows.first().locator('button[aria-label^="Delete"]').click()
  await expect(rows).toHaveCount(1)
})

test('offers rename and pin controls for a chat', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  const row = page.locator('aside nav > div').first()
  await row.hover()
  await expect(row.getByRole('button', { name: /rename/i })).toBeVisible()
  await expect(row.getByRole('button', { name: /pin/i })).toBeVisible()
})

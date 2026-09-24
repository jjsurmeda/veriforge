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

test('collapses the chat sidebar and persists the rail preference', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await createChat(page)

  const collapse = page.getByRole('button', { name: 'Collapse chat sidebar' })
  await collapse.click()
  const expand = page.getByRole('button', { name: 'Expand chat sidebar' })
  await expect(expand).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByRole('complementary').first()).toHaveCSS('width', '64px')

  await page.reload()
  await expect(page.getByRole('button', { name: 'Expand chat sidebar' })).toHaveAttribute('aria-pressed', 'true')
})

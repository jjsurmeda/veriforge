import { expect, test } from '@playwright/test'

import { createChat, signUp } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('signs up and exposes the shared seed corpus', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)

  await page.goto('/sources')
  await expect(page.getByRole('button', { name: /eval-seed-corpus\(shared\) 7/ })).toBeVisible()
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'No chat selected' })).toBeVisible()
})

test('attaches eval-seed-corpus to a chat before asking', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)
  await page.goto('/sources')
  await expect(page.getByRole('button', { name: /eval-seed-corpus\(shared\) 7/ })).toBeVisible()

  await page.goto('/')
  await createChat(page)
  const settings = page.getByRole('button', { name: 'Run settings' })
  if ((await settings.getAttribute('aria-expanded')) !== 'true') await settings.click()

  const collection = page.getByRole('main').getByRole('checkbox', { name: /eval-seed-corpus/ })
  await collection.check()
  await expect(collection).toBeChecked()
  await page.screenshot({ path: 'e2e/screenshots/e2e-chat-conversation.png', fullPage: true })
})

test('accepts the documented veriforge.test signup domain', async ({ page }) => {
  const user = makeTestUser('veriforge.test')
  await signUp(page, user)
})

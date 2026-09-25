import { expect, test } from '@playwright/test'

import { createChat, openNavigation, signUp, sidebar } from '../support/auth'
import { makeTestUser } from '../support/seed'

test('signs up and sees the shared seed corpus in the Library section', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)

  await openNavigation(page)
  await sidebar(page).getByRole('button', { name: /^Library$/ }).click()
  await expect(sidebar(page).getByRole('heading', { name: 'Shared' })).toBeVisible()
  await expect(sidebar(page).getByRole('heading', { name: 'Mine' })).toBeVisible()
})

test('a new chat includes the Library by default', async ({ page }) => {
  const user = makeTestUser()
  await signUp(page, user)

  await page.goto('/')
  await createChat(page)

  await openNavigation(page)
  await expect(
    sidebar(page).getByRole('checkbox', { name: 'Include Library' }),
  ).toBeChecked()
  await page.screenshot({ path: 'e2e/screenshots/e2e-chat-conversation.png', fullPage: true })
})

test('accepts the documented veriforge.test signup domain', async ({ page }) => {
  const user = makeTestUser('veriforge.test')
  await signUp(page, user)
})

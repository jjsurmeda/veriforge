import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

test('renders the abstention found/missing template', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(
    request,
    user,
    'What is the boiling point of helium on the surface of Mars?',
    'auto',
  )

  await page.goto(`/chat/${chatId}`)
  await expect(page.getByText('Abstained')).toBeVisible({ timeout: 110_000 })
  await expect(page.getByText('What I found:')).toBeVisible()
  await expect(page.getByText('What is missing:')).toBeVisible()
})

test('offers Web and Deep actions from the abstention template', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(
    request,
    user,
    'What is the boiling point of helium on the surface of Mars?',
    'auto',
  )

  await page.goto(`/chat/${chatId}`)
  await expect(page.getByText('Abstained')).toBeVisible({ timeout: 110_000 })
  const webAction = page.getByRole('button', { name: /Searching the web/i })
  const deepAction = page.getByRole('button', { name: /Deep mode/i })
  await expect(webAction).toBeVisible()
  await expect(deepAction).toBeVisible()
  await webAction.scrollIntoViewIfNeeded()
  await page.screenshot({ path: 'e2e/screenshots/e2e-abstain-actions.png', fullPage: true })
})

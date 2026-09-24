import { expect, test, type Page } from '@playwright/test'

import { grantAdmin } from '../support/admin'
import { login } from '../support/auth'
import { makeTestUser } from '../support/seed'

async function signUpAdmin(page: Page, email: string, password: string) {
  await page.goto('/signup')
  await page.getByLabel('Email').fill(email)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Sign up' }).click()
  await page.waitForURL((url) => url.pathname === '/' || url.pathname.startsWith('/chat/'))
  grantAdmin(email)
  await login(page, { email, password })
}

test('renders each admin section', async ({ page }) => {
  const user = makeTestUser()
  await signUpAdmin(page, user.email, user.password)
  await page.goto('/admin')

  for (const section of ['Settings', 'Providers', 'Models', 'Roles', 'Plans']) {
    await page.getByRole('button', { name: section }).click()
    const heading = {
      Settings: 'Runtime settings',
      Providers: 'Providers',
      Models: 'Model catalogue',
      Roles: 'Model roles',
      Plans: 'Plans and quota overrides',
    }[section]
    await expect(page.getByRole('heading', { name: heading })).toBeVisible()
    await page.screenshot({ path: `e2e/screenshots/e2e-admin-${section.toLowerCase()}.png`, fullPage: true })
  }
})

test('keeps the admin model catalogue to the two mid/flash models', async ({ page }) => {
  const user = makeTestUser()
  await signUpAdmin(page, user.email, user.password)
  await page.goto('/admin')
  await page.getByRole('button', { name: 'Models' }).click()

  await expect(page.getByText('anthropic/claude-haiku-4.5')).toBeVisible()
  await expect(page.getByText('openai/gpt-4o-mini')).toBeVisible()
  await expect(page.getByText('typesafe/jev-1.13')).toHaveCount(0)
})

test('creates a settings version and rolls back to the previous version', async ({ page }) => {
  const user = makeTestUser()
  await signUpAdmin(page, user.email, user.password)
  await page.goto('/admin')

  const topK = page.getByRole('spinbutton', { name: 'Retrieval top-k' })
  await topK.fill('9')
  await page.getByRole('button', { name: 'Create version' }).click()
  await expect(page.getByText('v2', { exact: true })).toBeVisible({ timeout: 30_000 })

  const v1Row = page.getByText('v1', { exact: true }).locator('..').locator('..')
  await v1Row.getByRole('button', { name: 'Activate' }).click()
  await expect(page.getByText(/Active v1/)).toBeVisible({ timeout: 30_000 })
})

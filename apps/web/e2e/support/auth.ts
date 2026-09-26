import { expect, type Page } from '@playwright/test'

import type { TestUser } from './seed'

export async function signUp(page: Page, user: TestUser): Promise<void> {
  await page.goto('/signup')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Sign up' }).click()
  await page.waitForURL((url) => url.pathname === '/' || url.pathname.startsWith('/chat/'))
}

export async function login(page: Page, user: TestUser): Promise<void> {
  await page.goto('/login')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL((url) => url.pathname === '/' || url.pathname.startsWith('/chat/'))
}

export async function createChat(page: Page): Promise<string> {
  const before = page.url()
  await openNavigation(page)
  await sidebar(page).getByRole('button', { name: 'New chat' }).first().click()
  await page.waitForURL((url) => /\/chat\/[^/]+$/.test(url.pathname) && url.href !== before)
  const chatId = page.url().split('/').at(-1)
  expect(chatId).toBeTruthy()
  return chatId as string
}

export function sidebar(page: Page) {
  return page.getByRole('complementary', { name: 'Chat navigation' })
}

// Below 1024px the left navigation is a drawer (docs/design-system.md §5),
// so every helper that touches the sidebar has to open it first. At lg and up
// the trigger never renders and the sidebar is already visible.
export async function openNavigation(page: Page): Promise<void> {
  if (await sidebar(page).isVisible()) return
  const trigger = page.getByRole('button', { name: 'Open navigation' })
  const found = await trigger.waitFor({ state: 'visible', timeout: 5_000 }).then(
    () => true,
    () => false,
  )
  if (!found) return
  await trigger.click()
  await expect(sidebar(page)).toBeVisible()
}

export async function closeNavigation(page: Page): Promise<void> {
  const close = page.getByRole('button', { name: 'Close navigation' })
  if (!(await close.isVisible().catch(() => false))) return
  await close.click()
  await expect(sidebar(page)).toBeHidden()
}

export async function addChatSource(page: Page, files: string | string[]): Promise<void> {
  await page.locator('input[aria-label="Add sources to the chat"]').setInputFiles(files)
  await expect(page.getByRole('tab', { name: 'Sources' })).toHaveAttribute('aria-selected', 'true')
}

export async function setComposerMode(page: Page, on: boolean): Promise<void> {
  const chip = page.getByRole('button', { name: 'Deep', exact: true })
  if ((await chip.getAttribute('aria-pressed')) !== String(on)) await chip.click()
}

export async function setComposerSource(page: Page, on: boolean): Promise<void> {
  const chip = page.getByRole('button', { name: 'Web', exact: true })
  if ((await chip.getAttribute('aria-pressed')) !== String(on)) await chip.click()
}

export async function waitForRunToFinish(page: Page): Promise<void> {
  // Wait for the run to actually start before waiting for it to end, or the
  // Stop button has not rendered yet and the second check passes instantly.
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeHidden({ timeout: 110_000 })
  await expect(page.getByRole('textbox', { name: 'Question' })).toBeEnabled()
}

export async function deleteCurrentChat(page: Page): Promise<void> {
  await page.getByRole('button', { name: 'Thread actions' }).click()
  await page.getByRole('menuitem', { name: 'Delete' }).click()
  await page.waitForURL(/\/$/)
}

// The app header is dissolved on / and /chat/* (design-system.md §5), so the
// theme toggle is reached through the sidebar footer on chat surfaces and
// through the header on the surfaces that keep the shell.
export async function toggleTheme(page: Page): Promise<void> {
  const inHeader = page.locator('header button[aria-label^="Switch to"]')
  if (await inHeader.first().isVisible().catch(() => false)) {
    await inHeader.first().click()
    return
  }
  await openNavigation(page)
  await sidebar(page).locator('button[aria-label^="Switch to"]').first().click()
}

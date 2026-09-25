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
  await openNavigation(page)
  await sidebar(page).locator('input[aria-label="Chat source files"]').setInputFiles(files)
}

export async function uploadLibraryDocument(page: Page, file: string): Promise<void> {
  await page.goto('/library')
  await page.locator('input[type="file"]').first().setInputFiles(file)
}

export async function setComposerMode(page: Page, value: 'auto' | 'fast' | 'deep'): Promise<void> {
  const trigger = page.locator('button[role="combobox"][aria-label="Run mode"]:visible').last()
  await trigger.click()
  await page.getByRole('option', { name: new RegExp(`^${value}`, 'i') }).click()
}

export async function setComposerSource(
  page: Page,
  value: 'auto' | 'upload' | 'web' | 'both',
): Promise<void> {
  const trigger = page.locator('button[role="combobox"][aria-label="Run source"]:visible').last()
  await trigger.click()
  await page.getByRole('option', { name: new RegExp(`^${value}`, 'i') }).click()
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

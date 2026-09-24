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
  const sidebar = page.getByRole('complementary')
  const evalCorpus = sidebar.getByRole('checkbox', { name: /eval-seed-corpus/i })
  if (await evalCorpus.count()) {
    await expect(evalCorpus).toBeVisible()
    await evalCorpus.check()
    await expect(evalCorpus).toBeChecked()
  }
  await sidebar.getByRole('button', { name: 'New chat' }).first().click()
  await page.waitForURL(/\/chat\/[^/]+$/)
  const chatId = page.url().split('/').at(-1)
  expect(chatId).toBeTruthy()
  return chatId as string
}

export async function setComposerMode(page: Page, value: 'auto' | 'fast' | 'deep'): Promise<void> {
  const settings = page.getByRole('button', { name: 'Run settings' })
  if ((await settings.getAttribute('aria-expanded')) !== 'true') await settings.click()
  await page.getByRole('combobox', { name: 'Run mode' }).selectOption(value)
}

export async function setComposerSource(
  page: Page,
  value: 'auto' | 'upload' | 'web' | 'both',
): Promise<void> {
  const settings = page.getByRole('button', { name: 'Run settings' })
  if ((await settings.getAttribute('aria-expanded')) !== 'true') await settings.click()
  await page.getByRole('combobox', { name: 'Run source' }).selectOption(value)
}

export async function waitForRunToFinish(page: Page): Promise<void> {
  await expect(page.getByRole('button', { name: 'Stop' })).toBeHidden({ timeout: 110_000 })
  await expect(page.getByRole('textbox', { name: 'Question' })).toBeEnabled()
}

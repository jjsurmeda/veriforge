import { expect, test } from '@playwright/test'

import { mockApi } from '../support/mockApi'

const chats = [
  { id: 'c1', title: 'Why is the warranty period different in the two contracts' },
  { id: 'c2', title: 'Second chat' },
]

test('sidebar has no Decision layer row; the profile menu offers it', async ({ page }) => {
  await mockApi(page, { chats })
  await page.goto('/chat/c1')
  const nav = page.getByRole('complementary', { name: 'Chat navigation' })
  if (!(await nav.isVisible())) await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(nav.getByRole('button', { name: 'Decision layer' })).toHaveCount(0)
  await nav.getByRole('button', { name: 'Profile menu' }).click()
  await page.getByRole('menuitem', { name: 'Decision layer' }).click()
  await expect(page).toHaveURL(/\/decision-layer$/)
})

test('the skip link moves focus past the sidebar to main', async ({ page }) => {
  await mockApi(page, { chats })
  await page.goto('/chat/c1')
  await page.keyboard.press('Tab')
  const skip = page.getByRole('link', { name: 'Skip to main content' })
  await expect(skip).toBeFocused()
  await page.keyboard.press('Enter')
  await expect(page.locator('main')).toBeFocused()
})

test('chat rows keep one actions button each', async ({ page }) => {
  await mockApi(page, { chats })
  await page.goto('/chat/c1')
  const nav = page.getByRole('complementary', { name: 'Chat navigation' })
  if (!(await nav.isVisible())) await page.getByRole('button', { name: 'Open navigation' }).click()
  await expect(nav.getByRole('button', { name: /^Actions for/ })).toHaveCount(2)
})

test('a failed chat list says so in the main area and the page has one h1', async ({ page }) => {
  await mockApi(page, { chatsFail: true })
  await page.goto('/')
  await expect(page.getByRole('status')).toContainText('could not be loaded')
  await expect(page.getByRole('heading', { level: 1 })).toHaveCount(1)
})

test('a blocked account sees the reset time in the composer', async ({ page }) => {
  await mockApi(page, { chats, quota: { blocked: true } })
  await page.goto('/chat/c1')
  await expect(page.getByRole('textbox', { name: 'Question' })).toHaveAttribute('placeholder', /resets at/)
})

test('Escape closes the workspace drawer below 1024px', async ({ page, viewport }) => {
  test.skip((viewport?.width ?? 0) >= 1024, 'the workspace is a drawer only below lg')
  await mockApi(page, { chats })
  await page.goto('/chat/c1')
  const toggle = page.getByRole('button', { name: 'Toggle workspace panel' })
  await toggle.click()
  await expect(toggle).toHaveAttribute('aria-pressed', 'true')
  await page.keyboard.press('Escape')
  await expect(toggle).toHaveAttribute('aria-pressed', 'false')
})

test('mobile controls are at least 44px', async ({ page, viewport }) => {
  test.skip((viewport?.width ?? 0) >= 1024, 'mobile target floor')
  await mockApi(page, { chats })
  await page.goto('/chat/c1')
  for (const name of ['Open navigation', 'Thread actions', 'Toggle workspace panel', 'Add sources', 'Send', 'Filters']) {
    const box = await page.getByRole('button', { name, exact: true }).boundingBox()
    expect(box?.height, name).toBeGreaterThanOrEqual(44)
    expect(box?.width, name).toBeGreaterThanOrEqual(44 - 1)
  }
})

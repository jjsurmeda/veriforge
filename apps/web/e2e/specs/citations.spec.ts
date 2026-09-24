import { expect, test } from '@playwright/test'

import { signUp } from '../support/auth'
import { startSeededRun } from '../support/live'
import { makeTestUser } from '../support/seed'

const question = 'What does a solid red LED mean, and which fault code indicates blade motor overcurrent?'

test('shows citation evidence and a non-colour verdict cue', async ({ page, request }) => {
  const user = makeTestUser()
  await signUp(page, user)
  const { chatId } = await startSeededRun(request, user, question)

  await page.goto(`/chat/${chatId}`)
  const chip = page.locator('sup[aria-label^="Citation"]').first()
  await expect(chip).toBeVisible({ timeout: 110_000 })
  await chip.hover()

  const tooltip = page.locator('[role="tooltip"]').filter({ hasText: 'faq.md' })
  await expect(tooltip).toBeVisible()
  await expect(tooltip).toContainText('rerank')
  await expect(tooltip).toContainText(/supported|partial|unsupported/)

  const state = await chip.evaluate((element) => ({
    label: element.getAttribute('aria-label') ?? '',
    text: element.textContent ?? '',
    color: getComputedStyle(element).color,
    decoration: getComputedStyle(element).textDecorationLine,
  }))
  expect(state.label).toMatch(/supported|partial|unsupported/)
  expect(state.text).toMatch(/[✓×]/)
  expect(state.color).not.toBe('')
  expect(state.decoration).toBeTruthy()
})

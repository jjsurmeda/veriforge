import { existsSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { addChatSource, createChat, deleteCurrentChat, signUp, waitForRunToFinish } from '../support/auth'
import { docentFixtures, makeTestUser } from '../support/seed'

const chatFixture = docentFixtures.jekyll

test.describe('chat sources', () => {
  test.beforeAll(() => {
    expect(
      existsSync(chatFixture),
      `Docent fixtures are required: ${chatFixture}`,
    ).toBe(true)
  })

  test('a chat file reaches ready, is cited, and dies with its chat', async ({ page }) => {
    const user = makeTestUser()
    await signUp(page, user)
    const chatId = await createChat(page)

    await addChatSource(page, chatFixture)
    await page.getByRole('textbox', { name: 'Question' }).fill('Who is the doctor in this file?')
    await page.getByRole('button', { name: 'Send' }).click()
    await waitForRunToFinish(page)
    await expect(page.getByRole('main').getByText(/\[1\] cas-etrange/)).toBeVisible()

    const otherChatId = await createChat(page)
    expect(otherChatId).not.toBe(chatId)

    await page.goto(`/chat/${chatId}`)
    await deleteCurrentChat(page)
    await page.goto(`/chat/${chatId}`)
    await expect(page.getByText('Chat not found.')).toBeVisible()
  })
})

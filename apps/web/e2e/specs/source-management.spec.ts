import { existsSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { addChatSource, createChat, deleteCurrentChat, openNavigation, setComposerSource, signUp, sidebar, uploadLibraryDocument, waitForRunToFinish } from '../support/auth'
import { docentFixtures, makeTestUser } from '../support/seed'

const chatFixture = docentFixtures.jekyll
const libraryFixture = docentFixtures.faust

test.describe('chat sources and the Library', () => {
  test.beforeAll(() => {
    expect(
      existsSync(chatFixture) && existsSync(libraryFixture),
      `Docent fixtures are required: ${chatFixture}, ${libraryFixture}`,
    ).toBe(true)
  })

  test('a chat file reaches ready, is cited, and dies with its chat', async ({ page }) => {
    const user = makeTestUser()
    await signUp(page, user)
    const chatId = await createChat(page)

    await addChatSource(page, chatFixture)
    const source = sidebar(page).getByRole('button', { name: /cas-etrange/ })
    await expect(source).toBeVisible()
    await expect(
      sidebar(page).locator('li', { hasText: 'cas-etrange' }).getByText('ready'),
    ).toBeVisible({ timeout: 120_000 })

    await setComposerSource(page, 'upload')
    await page.getByRole('textbox', { name: 'Question' }).fill('Who is the doctor in this file?')
    await page.getByRole('button', { name: 'Send' }).click()
    await waitForRunToFinish(page)
    await expect(page.getByRole('main').getByText(/\[1\] cas-etrange/)).toBeVisible()

    const otherChatId = await createChat(page)
    expect(otherChatId).not.toBe(chatId)
    await openNavigation(page)
    await expect(sidebar(page).getByRole('button', { name: /cas-etrange/ })).toHaveCount(0)

    await page.goto(`/chat/${chatId}`)
    await deleteCurrentChat(page)
    await page.goto(`/chat/${chatId}`)
    await expect(page.getByText('Chat not found.')).toBeVisible()
  })

  test('a Library file is visible in every chat until Include Library is off', async ({ page }) => {
    const user = makeTestUser()
    await signUp(page, user)

    await uploadLibraryDocument(page, libraryFixture)
    await expect(
      page.getByRole('listitem').filter({ hasText: 'faust-erster-teil' }).getByText('ready'),
    ).toBeVisible({ timeout: 120_000 })

    await page.goto('/')
    await createChat(page)
    await openNavigation(page)
    await expect(sidebar(page).getByText('Include Library')).toBeVisible()

    await setComposerSource(page, 'upload')
    await page.getByRole('textbox', { name: 'Question' }).fill('Who is the author of Faust: Der Tragodie erster Teil?')
    await page.getByRole('button', { name: 'Send' }).click()
    await waitForRunToFinish(page)
    await expect(page.getByRole('main').getByText(/\[1\] faust-erster-teil/)).toBeVisible()

    const secondChat = await createChat(page)
    await setComposerSource(page, 'upload')
    await page.getByRole('textbox', { name: 'Question' }).fill('Who is the author of Faust: Der Tragodie erster Teil?')
    await page.getByRole('button', { name: 'Send' }).click()
    await waitForRunToFinish(page)
    await expect(page.getByRole('main').getByText(/\[1\] faust-erster-teil/)).toBeVisible()
    expect(secondChat).toBeTruthy()

    await openNavigation(page)
    await sidebar(page).getByRole('checkbox', { name: 'Include Library' }).click()
    await expect(sidebar(page).getByRole('checkbox', { name: 'Include Library' })).not.toBeChecked()
    await page.getByRole('button', { name: 'Close navigation' }).click()
    await setComposerSource(page, 'upload')
    await page.getByRole('textbox', { name: 'Question' }).fill('Who is the author of Faust: Der Tragodie erster Teil?')
    await page.getByRole('button', { name: 'Send' }).click()
    await waitForRunToFinish(page)
    await expect(page.getByRole('main').getByText(/faust-erster-teil/)).toHaveCount(0)
  })
})

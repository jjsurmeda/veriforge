import { existsSync } from 'node:fs'

import { expect, test } from '@playwright/test'

import { makeTestUser, docentFixtures } from '../support/seed'

const files = [docentFixtures.pdf, docentFixtures.jekyll, docentFixtures.faust]

test('uploads, edits, re-indexes, and deletes Docent sources', async ({ page }) => {
  expect(
    files.every((file) => existsSync(file)),
    `Docent fixtures are required: ${files.join(', ')}`,
  ).toBe(true)

  const user = makeTestUser()
  const collectionName = `Docent demo corpus ${Date.now()}`
  await page.goto('/signup')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(user.password)
  await page.getByRole('button', { name: 'Sign up' }).click()
  await page.waitForURL((url) => url.pathname === '/' || url.pathname.startsWith('/chat/'))

  await page.goto('/sources')
  await page.getByLabel('New collection name').fill(collectionName)
  await page.getByRole('button', { name: 'Create' }).click()
  await expect(page.getByRole('heading', { name: collectionName })).toBeVisible()

  await page.locator('input[type="file"]').setInputFiles(files)
  const documentRows = page.locator('main ul').locator('li')
  await expect(documentRows).toHaveCount(3, { timeout: 120_000 })
  await expect(documentRows.filter({ hasText: 'ready' })).toHaveCount(3, { timeout: 120_000 })
  await expect(page.getByText('1 page: scanned?')).toBeVisible()

  await page.getByRole('button', { name: 'AI_Engineering_Crash_Course.pdf' }).click()
  const tag = page.getByLabel('Add tag')
  await tag.fill('docent-demo')
  await tag.press('Enter')
  await page.getByRole('button', { name: 'Save tags' }).click()
  await expect(page.getByText('docent-demo')).toBeVisible()

  await page.getByRole('button', { name: 'Re-index' }).first().click()
  await expect(documentRows.filter({ hasText: 'ready' })).toHaveCount(3, { timeout: 120_000 })

  const firstDelete = page.getByRole('button', { name: 'Delete' }).first()
  await firstDelete.locator('..').hover()
  page.once('dialog', (dialog) => void dialog.accept())
  await firstDelete.click()
  await expect(page.getByText('2 documents')).toBeVisible({ timeout: 30_000 })
})

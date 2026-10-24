import { expect, test } from '@playwright/test'

import { mockApi } from '../support/mockApi'

// KI-74 / SR-6: the composer sets the filters the API accepts, and a filter
// reaches the run request as a narrowing value. The server intersects it with
// the ownership scope, so the request is the whole client-side contract.
test('a composer filter narrows the run to the chosen document and tag', async ({ page }) => {
  const api = await mockApi(page, {
    chats: [{ id: 'c1', title: 'Contracts' }],
    documents: [
      { id: 'd1', name: 'lease.pdf', mime: 'application/pdf', tags: ['legal'] },
      { id: 'd2', name: 'notes.md', mime: 'text/markdown', tags: ['draft'], shared: true },
    ],
  })
  await page.goto('/chat/c1')

  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByLabel('Source type').selectOption('document')
  await page.getByLabel('File type').selectOption('application/pdf')
  await page.getByRole('checkbox', { name: 'lease.pdf' }).check()
  await page.getByRole('button', { name: 'legal', exact: true }).click()
  await page.getByLabel('Date from').fill('2026-01-01')
  await page.getByLabel('Date to').fill('2026-06-30')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('button', { name: 'Filters, 5 active' })).toBeVisible()

  await page.getByRole('textbox', { name: 'Question' }).fill('What is the notice period?')
  await page.getByRole('button', { name: 'Send' }).click()

  await expect.poll(() => api.runBodies.length).toBe(1)
  expect(api.runBodies[0].filters).toEqual({
    source_type: 'document',
    mime: 'application/pdf',
    document_ids: ['d1'],
    tags: ['legal'],
    date_from: '2026-01-01T00:00:00Z',
    date_to: '2026-06-30T23:59:59Z',
  })
})

test('an untouched composer sends no filters', async ({ page }) => {
  const api = await mockApi(page, { chats: [{ id: 'c1', title: 'Contracts' }] })
  await page.goto('/chat/c1')
  await page.getByRole('textbox', { name: 'Question' }).fill('Hello there')
  await page.getByRole('button', { name: 'Send' }).click()
  await expect.poll(() => api.runBodies.length).toBe(1)
  expect(api.runBodies[0].filters ?? null).toBeNull()
})

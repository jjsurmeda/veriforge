import { expect, test, type Page } from '@playwright/test'

import { mockWorkspaceApi } from '../support/mockWorkspaceApi'

// OCR (beta) UI. Every call is mocked in the browser: no backend, no model call.
// Run the dev server on port 5206 and set PLAYWRIGHT_BASE_URL=http://localhost:5206.

const doc = (id: string, name: string, page_flags: unknown) => ({
  id, name, mime: 'application/pdf', sha256: id.repeat(64).slice(0, 64), status: 'ready',
  page_flags, error: null, tags: [], created_at: '2026-10-26T00:00:00Z',
})

async function openSources(page: Page, documents: unknown[]) {
  await mockWorkspaceApi(page, 'answer')
  await page.route((url) => url.pathname === '/chats/c1/documents', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(documents) }))
  await page.goto('/chat/c1')
  const toggle = page.getByRole('button', { name: 'Toggle workspace panel' })
  await toggle.waitFor()
  if ((await toggle.getAttribute('aria-pressed')) === 'false') await toggle.click()
  await page.getByRole('tab', { name: /^Sources/ }).click()
}

test('a scanned document shows an OCR badge and a low-confidence note', async ({ page }) => {
  await openSources(page, [
    doc('a', 'scan.pdf', [{ page: 1, flags: ['low_text', 'ocr'] }, { page: 2, flags: ['ocr', 'ocr_low_confidence'] }]),
    doc('b', 'digital.pdf', null),
  ])
  const scan = page.getByRole('listitem').filter({ hasText: 'scan.pdf' })
  await expect(scan.getByText('OCR', { exact: true })).toBeVisible()
  await expect(scan.getByText('low-confidence OCR')).toBeVisible()
  await expect(page.getByRole('listitem').filter({ hasText: 'digital.pdf' }).getByText('OCR', { exact: true })).toHaveCount(0)
})

test('the empty Sources panel says scanned PDFs and images are read with OCR (beta)', async ({ page }) => {
  await openSources(page, [])
  await expect(page.getByText(/read with OCR \(beta\)/)).toBeVisible()
})

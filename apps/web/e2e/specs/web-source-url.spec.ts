import { expect, test } from '@playwright/test'

import { mockApi } from '../support/mockApi'

// API mocked in the browser: no stack, no model call.
test('a web citation shows its page title and a safe link; an unsafe scheme is plain text', async ({ page }) => {
  await mockApi(page, { chats: [{ id: 'c1', title: 'Web chat' }] })
  await page.route(/\/chats\/c1\/messages$/, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        {
          id: 'm1', chat_id: 'c1', role: 'assistant', status: 'complete', run_id: null, metrics: null,
          created_at: '2026-10-24T09:00:00Z', content: 'Zebras sleep standing [1] and bad [2].',
          citations: [
            { n: 1, chunk_id: 'k1', document_name: 'Zebra facts', url: 'https://example.com/zebra', excerpt: 'Zebras sleep standing up.' },
            { n: 2, chunk_id: 'k2', document_name: 'Bad page', url: 'javascript:alert(1)', excerpt: 'Nope.' },
          ],
        },
      ]),
    }),
  )
  await page.goto('/chat/c1')
  const card = page.getByText('[1] Zebra facts')
  await expect(card).toBeVisible()
  const link = page.getByRole('link', { name: /example\.com/ }).first()
  await expect(link).toHaveAttribute('href', 'https://example.com/zebra')
  await expect(link).toHaveAttribute('target', '_blank')
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  await expect(page.locator('a[href^="javascript:"]')).toHaveCount(0)
  await expect(page.getByText('javascript:alert(1)').first()).toBeVisible()
})

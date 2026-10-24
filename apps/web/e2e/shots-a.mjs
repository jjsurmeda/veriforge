// Slice A after-shots against the mocked API. Run: node e2e/shots-a.mjs <outDir>
import { chromium } from '@playwright/test'
const out = process.argv[2]
const base = 'http://localhost:5201'
const chats = [{ id: 'c1', title: 'Why is the warranty period different in the two contracts', pinned: true }, { id: 'c2', title: 'Second chat' }]
const docs = [{ id: 'd1', name: 'lease.pdf', mime: 'application/pdf', tags: ['legal'] }, { id: 'd2', name: 'notes.md', mime: 'text/markdown', tags: ['draft'] }]
const { mockApi } = await import('./support/mockApi.ts').catch(() => ({}))
if (!mockApi) throw new Error('run with: npx tsx')
const browser = await chromium.launch()
for (const [vw, vh] of [[1440, 900], [390, 844]]) for (const theme of ['dark', 'light']) {
  const shoot = async (name, opts, path, act) => {
    const ctx = await browser.newContext({ viewport: { width: vw, height: vh } })
    const page = await ctx.newPage()
    await mockApi(page, opts)
    await page.goto(base + path)
    await page.waitForTimeout(500)
    await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme)
    if (act) await act(page)
    await page.waitForTimeout(300)
    await page.screenshot({ path: `${out}/after-${name}-${vw}-${theme}.png` })
    await ctx.close()
  }
  const mobile = vw < 1024
  const openNav = async (p) => { if (mobile) await p.getByRole('button', { name: 'Open navigation' }).click() }
  await shoot('index-empty', { chats: [] }, '/')
  await shoot('index-chats-error', { chatsFail: true }, '/')
  await shoot('thread-answer', { chats, documents: docs }, '/chat/c1', openNav)
  await shoot('thread-quota-blocked', { chats, quota: { blocked: true } }, '/chat/c1')
  await shoot('thread-filters', { chats, documents: docs }, '/chat/c1', async (p) => { await p.getByRole('button', { name: 'Filters', exact: true }).click(); await p.getByRole('button', { name: 'legal' }).click() })
  await shoot('profile-menu', { chats, documents: docs }, '/chat/c1', async (p) => { await openNav(p); await p.getByRole('button', { name: 'Profile menu' }).click() })
  await shoot('row-actions', { chats }, '/chat/c1', async (p) => { await openNav(p); await p.getByRole('button', { name: /^Actions for Second/ }).click() })
}
await browser.close()

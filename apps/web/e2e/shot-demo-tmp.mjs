// Throwaway: the six-question tour rehearsal (item 7). One live run each.
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const BASE = process.env.WEB_URL ?? 'http://localhost:5175'
const OUT = process.env.OUT ?? 'e2e/screenshots'
mkdirSync(OUT, { recursive: true })

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 940 } })
const page = await context.newPage()
const errors = []
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))

const shot = async (name, theme = 'dark') => {
  await page.evaluate((v) => document.documentElement.setAttribute('data-theme', v), theme)
  await page.waitForTimeout(450)
  await page.screenshot({ path: `${OUT}/${name}-${theme}.png` })
  console.log(`  wrote ${OUT}/${name}-${theme}.png`)
}

await page.goto(`${BASE}/login`)
await page.waitForTimeout(900)
for (const theme of ['dark', 'light']) await shot('item4-login', theme)

await page.getByRole('button', { name: 'Try the demo' }).click()
await page.waitForURL((u) => u.pathname === '/' || u.pathname.startsWith('/chat/'), { timeout: 30_000 })
await page.waitForTimeout(1500)
for (const theme of ['dark', 'light']) await shot('item4-demo-tour', theme)

const REGION = 'Six questions, six behaviours'

// The access token is in memory only (TRD §11), so it cannot be read out of
// the page; the refresh cookie can. Mint a token via /auth/refresh and use that
// for the direct API calls below.
const token = async () => {
  const res = await page.evaluate(async () => {
    const response = await fetch('/auth/refresh', { method: 'POST', credentials: 'include' })
    if (!response.ok) return null
    return (await response.json()).access_token
  })
  if (!res) throw new Error('no session: the refresh cookie is gone')
  return res
}

// The tour only renders on an empty index, so each question gets a fresh chat:
// the chat from the previous question is deleted so the next visit is empty.
const clearChats = async () => {
  const access = await token()
  const removed = await page.evaluate(async (t) => {
    const headers = { Authorization: `Bearer ${t}` }
    const list = await fetch('/chats', { headers }).then((r) => r.json())
    for (const chat of Array.isArray(list) ? list : []) {
      await fetch(`/chats/${chat.id}`, { method: 'DELETE', headers })
    }
    return Array.isArray(list) ? list.length : 0
  }, access)
  console.log(`  cleared ${removed} chat(s)`)
}

await clearChats()
await page.goto(`${BASE}/`)
await page.waitForTimeout(1200)
const chips = page.getByRole('region', { name: REGION }).getByRole('button')
const count = await chips.count()
console.log(`tour chips: ${count}`)

for (let i = 0; i < count; i += 1) {
  await page.goto(`${BASE}/`)
  await page.waitForTimeout(1200)
  const chip = page.getByRole('region', { name: REGION }).getByRole('button').nth(i)
  const label = (await chip.textContent())?.trim() ?? ''
  const slug = label.split('?')[0].slice(0, 28).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
  await chip.click()
  await page.waitForURL(/\/chat\//, { timeout: 30_000 })
  await page.waitForTimeout(50_000)

  const card = page.getByRole('region', { name: 'Evidence gates' })
  const hasCard = (await card.count()) > 0
  const body = await page.getByRole('main').innerText()
  const gateText = hasCard ? (await card.innerText()).replace(/\s+/g, ' ') : '(no gate card)'
  console.log(`\n  [${i + 1}/${count}] ${label}`)
  console.log(`      abstained=${body.includes('Abstained')} declined=${body.includes('Why it declined')}`)
  console.log(`      gates: ${gateText.slice(0, 220)}`)
  await shot(`tour-${i + 1}-${slug}`)
  if (i < count - 1) await clearChats()
}

console.log(`\nconsole errors: ${errors.length}`)
for (const e of errors.slice(0, 6)) console.log(`  ${e}`)
await browser.close()
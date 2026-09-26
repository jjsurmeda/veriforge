import { chromium } from '@playwright/test'

const BASE = process.env.WEB_URL ?? 'http://localhost:5174'
const OUT = 'e2e/screenshots'
const EMAIL = `ux${Date.now()}@example.com`
const PASSWORD = 'UxPass!2345'

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const consoleErrors = []
page.on('console', (message) => {
  if (message.type() === 'error') consoleErrors.push(message.text())
})

await page.goto(`${BASE}/signup`)
await page.getByLabel('Email').fill(EMAIL)
await page.getByLabel('Password').fill(PASSWORD)
await page.getByRole('button', { name: 'Sign up' }).click()
await page.waitForURL((url) => url.pathname === '/' || url.pathname.startsWith('/chat/'), {
  timeout: 30_000,
})
await page.waitForTimeout(1_500)

const sidebar = page.getByRole('complementary', { name: 'Chat navigation' })
const shot = async (name) => {
  await page.screenshot({ path: `${OUT}/ux-${name}.png` })
  console.log(`  wrote ${OUT}/ux-${name}.png`)
}

for (const theme of ['dark', 'light']) {
  await page.evaluate((value) => document.documentElement.setAttribute('data-theme', value), theme)
  await page.waitForTimeout(400)

  await sidebar.getByRole('button', { name: /^Chats$/ }).click()
  await page.waitForTimeout(400)
  await shot(`${theme}-sidebar-chats`)

  await sidebar.getByRole('button', { name: /^Library$/ }).click()
  await page.waitForTimeout(900)
  await shot(`${theme}-sidebar-library`)
}

await page.evaluate((value) => document.documentElement.setAttribute('data-theme', 'dark'), 'dark')
await sidebar.getByRole('button', { name: /^Chats$/ }).click()
await sidebar.getByRole('button', { name: 'New chat' }).click()
await page.waitForURL(/\/chat\//, { timeout: 30_000 })
await page.waitForTimeout(1_500)
// The panel starts open at 1440px (design-system.md §5), so only click when
// it is not.
const panel = page.getByRole('complementary', { name: /workspace|trace/i })
const panelOpen = await panel.count().catch(() => 0)
if (panelOpen === 0) {
  const panelToggle = page.getByRole('button', { name: 'Toggle workspace panel' })
  if (await panelToggle.isVisible().catch(() => false)) {
    await panelToggle.click()
    await page.waitForTimeout(800)
  }
}
await shot('dark-chat-right-panel')

await page.goto(`${BASE}/admin`)
await page.waitForTimeout(1_200)
await shot('dark-header')

console.log(consoleErrors.length ? `console errors: ${consoleErrors.length}` : 'console errors: 0')
for (const error of consoleErrors.slice(0, 5)) console.log(`  ${error}`)

await browser.close()

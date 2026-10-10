// Screenshots of the login page when the demo cannot start (KI-63).
//
// Two states, both themes, per docs/showcase.md: the demo switched off
// (`demo_disabled`, the 404) and the daily cap spent (`demo_capacity`, the
// 429). "Try the demo" must not look broken in either.
//
// No backend and no model: the page is served by `vite preview` and the one
// request it makes is intercepted with `page.route`, so nothing is spent and
// no account is minted. The two error codes are the exact bodies
// `demo/router.py` returns.
//
// Usage: npm run preview -- --port 5179 &  WEB_URL=http://localhost:5179 \
//          node e2e/shot-demo-unavailable.mjs
import { chromium } from '@playwright/test'
import { mkdirSync } from 'node:fs'

const BASE = process.env.WEB_URL ?? 'http://localhost:5179'
const OUT = process.env.OUT ?? 'e2e/screenshots'
mkdirSync(OUT, { recursive: true })

const STATES = [
  {
    slug: 'demo-off',
    status: 404,
    body: {
      error_code: 'demo_disabled',
      message: 'The demo is not available on this deployment.',
      detail: null,
    },
  },
  {
    slug: 'demo-full',
    status: 429,
    body: {
      error_code: 'demo_capacity',
      message: '50 demo account(s) already created in the last 24h; the cap is 50',
      detail: { retry_after: 3600 },
    },
  },
]

const browser = await chromium.launch()
const errors = []

for (const state of STATES) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const page = await context.newPage()
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  // Intercept the one request the demo button makes, so no account is minted
  // and nothing is spent.
  await page.route('**/auth/demo', (route) =>
    route.fulfill({
      status: state.status,
      contentType: 'application/json',
      body: JSON.stringify(state.body),
    }),
  )

  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Try the demo' }).click()
  const alert = page.getByRole('alert')
  await alert.waitFor({ timeout: 10_000 })
  const message = (await alert.innerText()).trim()
  console.log(`${state.slug}: ${state.status} -> "${message}"`)

  for (const theme of ['dark', 'light']) {
    await page.evaluate((v) => document.documentElement.setAttribute('data-theme', v), theme)
    await page.waitForTimeout(400)
    const path = `${OUT}/login-demo-${state.slug}-${theme}.png`
    await page.screenshot({ path })
    console.log(`  wrote ${path}`)
  }
  await context.close()
}

console.log(`console errors: ${errors.length}`)
for (const e of errors.slice(0, 5)) console.log(`  ${e}`)
await browser.close()
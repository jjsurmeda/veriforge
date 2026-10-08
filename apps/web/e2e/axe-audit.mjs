/**
 * The accessibility audit for lane E item 6: axe over the main screens, in
 * both themes, reporting the real violation count.
 *
 * Run against a running stack:
 *   WEB_URL=http://localhost:5175 EMAIL=… OUT=… node e2e/axe-audit.mjs [label]
 *
 * Writes the per-screen violation list to stdout as JSON and a summary table,
 * so the "before" and "after" numbers in the report are two runs of the same
 * script rather than two people's counts.
 *
 * Deliberately not an assertion: axe finds violations that are sometimes
 * correct (a `region` landmark that is intentionally repeated, an aria-live
 * region used for a status line). The count is evidence, and a human decides
 * which ones to fix.
 */
import AxeBuilder from '@axe-core/playwright'
import { chromium } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'

const BASE = process.env.WEB_URL ?? 'http://localhost:5175'
const EMAIL = process.env.EMAIL
const PASSWORD = process.env.PASSWORD ?? 'Showcase!2345'
const OUT = process.env.OUT ?? 'e2e/screenshots'
const LABEL = process.argv[2] ?? 'audit'
mkdirSync(OUT, { recursive: true })

/** The main screens the brief names: chat, Sources, Trace, Library. Plus the
 *  two this lane added, because a new page with no audit is a new page with
 *  unknown violations. */
const SCREENS = [
  { id: 'login', path: '/login' },
  { id: 'demo-tour', path: '/', needsDemo: true },
  { id: 'chat-trace', path: '/', needsDemo: true, tab: 'Trace' },
  { id: 'chat-sources', path: '/', needsDemo: true, tab: 'Sources' },
  { id: 'chat-citations', path: '/', needsDemo: true, tab: 'Citations' },
  { id: 'chat-metrics', path: '/', needsDemo: true, tab: 'Metrics' },
  { id: 'library', path: '/library' },
  { id: 'decision-layer', path: '/decision-layer', needsDemo: true },
]

const browser = await chromium.launch()
const context = await browser.newContext({ viewport: { width: 1440, height: 940 } })
const page = await context.newPage()

if (EMAIL) {
  await page.goto(`${BASE}/login`)
  await page.getByLabel('Email').fill(EMAIL)
  await page.getByLabel('Password').fill(PASSWORD)
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.waitForURL((u) => u.pathname === '/' || u.pathname.startsWith('/chat/'), { timeout: 30_000 })
  await page.waitForTimeout(800)
}

const results = []
for (const theme of ['dark', 'light']) {
  await page.evaluate((v) => document.documentElement.setAttribute('data-theme', v), theme)
  for (const screen of SCREENS) {
    if (screen.needsDemo && !EMAIL) continue
    await page.goto(`${BASE}${screen.path}`)
    await page.waitForTimeout(1200)
    if (screen.tab) {
      const tab = page.getByRole('tab', { name: new RegExp(`^${screen.tab}`) })
      if (await tab.count()) {
        await tab.first().click()
        await page.waitForTimeout(700)
      }
    }
    const scan = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze()
    const violations = scan.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.length,
      // One target per violation, enough to act on without a wall of CSS paths.
      target: v.nodes[0]?.target?.join(' ') ?? '',
      summary: v.nodes[0]?.failureSummary?.split('\n').slice(0, 3).join(' ').trim() ?? '',
    }))
    results.push({ screen: screen.id, theme, violations })
    const serious = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    console.log(
      `${theme.padEnd(5)} ${screen.id.padEnd(16)} ${String(violations.length).padStart(2)} violations (${serious.length} serious/critical)`,
    )
    for (const v of violations) {
      console.log(`      [${v.impact ?? 'minor'}] ${v.id}: ${v.help} (${v.nodes}x) @ ${v.target}`)
    }
    if (process.env.SHOTS) {
      await page.screenshot({ path: `${OUT}/axe-${LABEL}-${screen.id}-${theme}.png` })
    }
  }
}

const total = results.reduce((sum, row) => sum + row.violations.length, 0)
const seriousTotal = results.filter((row) =>
  row.violations.some((v) => v.impact === 'serious' || v.impact === 'critical'),
).length
console.log(`\n${LABEL}: ${total} violations across ${results.length} screen/theme pairs; ${seriousTotal} with a serious or critical finding`)
writeFileSync(`${OUT}/axe-${LABEL}.json`, JSON.stringify(results, null, 2))
console.log(`  wrote ${OUT}/axe-${LABEL}.json`)
await browser.close()
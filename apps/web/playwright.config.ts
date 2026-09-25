import { defineConfig, devices } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5174'
const hostname = new URL(baseURL).hostname.replace(/^\[|\]$/g, '')
if (!['localhost', '127.0.0.1', '::1'].includes(hostname)) {
  throw new Error('Playwright e2e is restricted to a local stack')
}

// Desktop and the 390px floor the design system's accessibility rule names
// (docs/design-system.md §9: no horizontal overflow or clipped controls).
const viewports = [
  { name: 'desktop-1440', viewport: { width: 1440, height: 900 } },
  { name: 'mobile-390', viewport: { width: 390, height: 844 } },
]

export default defineConfig({
  testDir: './e2e/specs',
  outputDir: './e2e/test-results',
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: [['list'], ['html', { outputFolder: './e2e/report', open: 'never' }]],
  use: {
    baseURL,
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    video: 'retain-on-failure',
  },
  projects: viewports.map(({ name, viewport }) => ({
    name,
    use: { ...devices['Desktop Chrome'], viewport },
  })),
})

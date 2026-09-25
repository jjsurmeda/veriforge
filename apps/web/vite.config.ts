/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig, type ProxyOptions } from 'vite'

const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

// API paths that collide with an SPA route (/library) must not swallow a
// top-level navigation: a document request is rewritten to the SPA entry
// instead of being proxied.
const bypassDocumentNavigation: ProxyOptions['bypass'] = (request) =>
  typeof request === 'string' || (request.headers.accept ?? '').includes('text/html')
    ? '/index.html'
    : undefined

const proxy = Object.fromEntries(
  [
    '/auth',
    '/chats',
    '/runs',
    '/models',
    '/model-roles',
    '/me',
    '/messages',
    '/admin/',
    '/healthz',
    '/library',
    '/web-sources',
    '/documents',
  ].map((path) => [
    path,
    { target: apiTarget, changeOrigin: true, bypass: bypassDocumentNavigation },
  ]),
)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})

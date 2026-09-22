/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

const apiTarget = process.env.API_PROXY_TARGET ?? 'http://localhost:8000'

const proxy = Object.fromEntries(
  ['/auth', '/chats', '/runs', '/models', '/model-roles', '/me', '/healthz'].map((p) => [
    p,
    { target: apiTarget, changeOrigin: true },
  ]),
)

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy },
  test: {
    environment: 'jsdom',
  },
})

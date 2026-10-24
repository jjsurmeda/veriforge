import type { Page, Route } from '@playwright/test'

// A browser-level API mock for specs that must run with no stack and no model
// calls (docs/conventions/playwright.md). Only the endpoints the shell,
// sidebar and composer read are covered; anything else answers 404.

export interface MockOptions {
  role?: string
  chats?: Array<{ id: string; title: string; pinned?: boolean }>
  chatsFail?: boolean
  quota?: Partial<Record<string, unknown>>
  documents?: Array<{ id: string; name: string; mime: string; tags: string[]; shared?: boolean }>
}

export interface MockApi {
  /** Bodies of every POST /chats/:id/runs, in order. */
  runBodies: Array<Record<string, unknown>>
}

const NOW = '2026-10-24T09:00:00Z'
const json = (route: Route, body: unknown, status = 200) =>
  route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })

export async function mockApi(page: Page, options: MockOptions = {}): Promise<MockApi> {
  const api: MockApi = { runBodies: [] }
  const chats = (options.chats ?? []).map((chat) => ({
    id: chat.id,
    title: chat.title,
    pinned: chat.pinned ?? false,
    model_id: null,
    created_at: NOW,
    starter_questions: [],
    active_run_id: null,
  }))
  const quota = {
    blocked: false,
    estimate: 1,
    limit_5h: 1000,
    limit_month: 10000,
    mode: 'auto',
    remaining_5h: 840,
    remaining_month: 9000,
    reset_at_5h: '2026-10-24T14:30:00Z',
    reset_at_month: '2026-11-01T00:00:00Z',
    used_5h: 160,
    ...options.quota,
  }
  const documents = (options.documents ?? []).map((doc) => ({
    created_at: NOW,
    editable: false,
    error: null,
    page_flags: null,
    sha256: doc.id,
    shared: doc.shared ?? false,
    status: 'ready',
    ...doc,
  }))

  await page.route(/^https?:\/\/[^/]+\/(auth|me|chats|library|models|rerankers|runs|documents|admin|model-roles|web-sources|healthz)(\/|\?|$)/, async (route) => {
    const request = route.request()
    if (request.resourceType() === 'document') return route.fallback()
    const url = new URL(request.url())
    const path = url.pathname
    const method = request.method()
    if (path === '/auth/refresh') return json(route, { access_token: 'mock-token' })
    if (path === '/auth/demo/limits') return json(route, { role: options.role ?? 'user', is_demo: false })
    if (path === '/me') return json(route, { id: 'u1', email: 'tester@example.com', role: options.role ?? 'user', plan_id: 'free', credits_5h: null, credits_month: null })
    if (path === '/me/quota') return json(route, quota)
    if (path === '/models') return json(route, [])
    if (path === '/library') return json(route, { documents, starter_questions: [] })
    if (path === '/chats' && method === 'GET') return options.chatsFail ? json(route, { detail: 'boom' }, 500) : json(route, chats)
    if (/^\/chats\/[^/]+$/.test(path)) return json(route, chats.find((chat) => path.endsWith(chat.id)) ?? chats[0])
    if (/\/messages$/.test(path) || /\/documents$/.test(path)) return json(route, [])
    if (/\/runs$/.test(path) && method === 'POST') {
      api.runBodies.push(request.postDataJSON() as Record<string, unknown>)
      return json(route, { run_id: 'run-1', message_id: 'm-1', mode: 'auto', model: 'mock' })
    }
    if (/\/stream$/.test(path)) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    return json(route, { detail: 'not mocked' }, 404)
  })
  return api
}

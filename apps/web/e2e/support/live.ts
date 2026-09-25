import { expect, type APIRequestContext } from '@playwright/test'

import type { TestUser } from './seed'

interface LoginResponse {
  access_token: string
}

interface LibraryResponse {
  documents: Array<{ name: string; shared: boolean }>
  starter_questions: string[]
}

interface ChatResponse {
  id: string
  include_library: boolean
}

interface RunResponse {
  run_id: string
  message_id: string
}

export async function accessToken(request: APIRequestContext, user: TestUser): Promise<string> {
  const response = await request.post('/auth/login', {
    data: { email: user.email, password: user.password },
  })
  expect(response.ok()).toBeTruthy()
  const body = (await response.json()) as LoginResponse
  return body.access_token
}

export async function sharedCorpusVisible(
  request: APIRequestContext,
  token: string,
): Promise<boolean> {
  const response = await request.get('/library', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok()).toBeTruthy()
  const library = (await response.json()) as LibraryResponse
  return library.documents.some((document) => document.shared)
}

export async function startSeededRun(
  request: APIRequestContext,
  user: TestUser,
  question: string,
  mode: 'auto' | 'fast' | 'deep' = 'fast',
): Promise<{ chatId: string; runId: string }> {
  const token = await accessToken(request, user)
  const chatResponse = await request.post('/chats', {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: `E2E ${new Date().toISOString()}` },
  })
  expect(chatResponse.ok()).toBeTruthy()
  const chat = (await chatResponse.json()) as ChatResponse
  expect(chat.include_library).toBe(true)
  const runResponse = await request.post(`/chats/${chat.id}/runs`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { message: question, mode, source: 'upload' },
  })
  expect(runResponse.ok()).toBeTruthy()
  const run = (await runResponse.json()) as RunResponse
  return { chatId: chat.id, runId: run.run_id }
}

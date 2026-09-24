import { expect, type APIRequestContext } from '@playwright/test'

import type { TestUser } from './seed'

interface LoginResponse {
  access_token: string
}

interface Collection {
  id: string
  name: string
  document_count: number
}

interface ChatResponse {
  id: string
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

export async function evalCollectionId(
  request: APIRequestContext,
  token: string,
): Promise<string> {
  const response = await request.get('/collections', {
    headers: { Authorization: `Bearer ${token}` },
  })
  expect(response.ok()).toBeTruthy()
  const collections = (await response.json()) as Collection[]
  const collection = collections.find((item) => item.name === 'eval-seed-corpus')
  expect(collection, 'eval-seed-corpus must be present').toBeTruthy()
  return (collection as Collection).id
}

export async function startSeededRun(
  request: APIRequestContext,
  user: TestUser,
  question: string,
  mode: 'auto' | 'fast' | 'deep' = 'fast',
): Promise<{ chatId: string; runId: string }> {
  const token = await accessToken(request, user)
  const collectionId = await evalCollectionId(request, token)
  const chatResponse = await request.post('/chats', {
    headers: { Authorization: `Bearer ${token}` },
    data: { title: `E2E ${new Date().toISOString()}`, collection_ids: [collectionId] },
  })
  expect(chatResponse.ok()).toBeTruthy()
  const chat = (await chatResponse.json()) as ChatResponse
  const runResponse = await request.post(`/chats/${chat.id}/runs`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      message: question,
      mode,
      source: 'upload',
      collection_ids: [collectionId],
    },
  })
  expect(runResponse.ok()).toBeTruthy()
  const run = (await runResponse.json()) as RunResponse
  return { chatId: chat.id, runId: run.run_id }
}

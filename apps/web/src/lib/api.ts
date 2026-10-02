import { client } from '../generated/client.gen'
import { authedFetch } from './auth'

// Same-origin (vite proxy in dev) with the auth/refresh fetch wrapper.
client.setConfig({ baseUrl: '', fetch: authedFetch })

/**
 * The generated client resolves a 4xx/5xx with `{ error }` instead of
 * throwing, so every caller has to check it. A query that reads only `.data`
 * renders an auth, network or server failure as an empty collection, which
 * looks exactly like "there are no rows". This is the one place that turns
 * the SDK result into a real success-or-throw, for TanStack Query to own.
 */
export function unwrap<T>(result: { data?: T; error?: unknown }): T {
  if (result.error) throw result.error
  if (result.data === undefined) throw new Error('The API returned an empty response.')
  return result.data
}
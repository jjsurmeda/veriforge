import { describe, expect, it } from 'vitest'

import { runFailureMessage } from './ChatView'

// KI-23: each terminal code gets copy that tells the user whether retrying
// can help. Quota and provider failures must never say "try again".
describe('runFailureMessage', () => {
  it('quota_exceeded names the limit and the reset, never "try again"', () => {
    const message = runFailureMessage('quota_exceeded', '15:30')

    expect(message).toContain('limit')
    expect(message).toContain('15:30')
    expect(message).not.toMatch(/try again/i)
  })

  it('quota_exceeded still reads sensibly when no reset time is known', () => {
    const message = runFailureMessage('quota_exceeded')

    expect(message).toContain('limit')
    expect(message).not.toMatch(/try again/i)
  })

  it('provider_key_invalid blames the key, not the user', () => {
    const message = runFailureMessage('provider_key_invalid')

    expect(message).toMatch(/API key/i)
    expect(message).not.toMatch(/try again/i)
  })

  it('provider_unavailable says the provider is down', () => {
    const message = runFailureMessage('provider_unavailable')

    expect(message).toMatch(/provider is unavailable/i)
    expect(message).not.toMatch(/try again/i)
  })

  it('keeps the two web-search codes working (unchanged behaviour)', () => {
    expect(runFailureMessage('web_search_unconfigured')).toBe(
      "Couldn't search the web because no web search provider is configured. Try your documents instead.",
    )
    expect(runFailureMessage('web_search_failed')).toBe(
      'The web search provider could not answer that question. Try again.',
    )
  })

  it('an unknown code still gets the generic retryable message', () => {
    expect(runFailureMessage('run_error')).toBe('The run could not finish. Try again.')
  })
})
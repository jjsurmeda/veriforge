import { describe, expect, it } from 'vitest'

import type { DocumentOut } from '../../../generated/types.gen'
import { shouldPoll } from './useDocuments'

function doc(status: string): DocumentOut {
  return {
    id: 'd1',
    collection_id: 'c1',
    name: 'doc.pdf',
    mime: 'application/pdf',
    sha256: 'ab',
    status,
    page_flags: null,
    error: null,
    tags: [],
    created_at: '2026-09-23T00:00:00Z',
  }
}

describe('shouldPoll', () => {
  it('polls while any document is live', () => {
    for (const status of ['queued', 'parsing', 'embedding']) {
      expect(shouldPoll([doc('ready'), doc(status)])).toBe(true)
    }
  })

  it('stops polling when every document is terminal', () => {
    expect(shouldPoll([doc('ready'), doc('failed')])).toBe(false)
  })

  it('does not poll an empty or missing list', () => {
    expect(shouldPoll([])).toBe(false)
    expect(shouldPoll(undefined)).toBe(false)
  })
})

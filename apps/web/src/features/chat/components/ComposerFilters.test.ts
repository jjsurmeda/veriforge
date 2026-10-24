import { describe, expect, it } from 'vitest'

import { activeFilterCount, compactFilters } from './ComposerFilters'

describe('composer filters', () => {
  it('counts a date range once and ignores empty lists', () => {
    expect(activeFilterCount({ date_from: '2026-01-01T00:00:00Z', date_to: '2026-02-01T00:00:00Z', tags: [], document_ids: null })).toBe(1)
    expect(activeFilterCount({ source_type: 'web', mime: 'application/pdf', tags: ['a'] })).toBe(3)
  })

  it('sends nothing when no filter is set', () => {
    expect(compactFilters({})).toBeUndefined()
    expect(compactFilters({ tags: [] })).toBeUndefined()
    expect(compactFilters({ tags: ['a'] })).toEqual({ tags: ['a'] })
  })
})

import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import type { ChunkOut, DocumentOut } from '../../../generated/types.gen'
import { DocumentViewer, groupChunks } from './DocumentViewer'

function chunk(partial: Partial<ChunkOut>): ChunkOut {
  return {
    id: 'ch1',
    section_id: 's1',
    ord: 0,
    page: 1,
    heading_path: 'Intro',
    text: 'chunk text',
    metadata: {},
    ...partial,
  }
}

function document(partial: Partial<DocumentOut>): DocumentOut {
  return {
    id: 'd1',
    collection_id: 'c1',
    name: 'doc.pdf',
    mime: 'application/pdf',
    sha256: 'abcdef0123456789',
    status: 'ready',
    page_flags: null,
    error: null,
    tags: [],
    created_at: '2026-09-23T00:00:00Z',
    ...partial,
  }
}

describe('groupChunks', () => {
  it('groups chunks by section preserving order', () => {
    const groups = groupChunks([
      chunk({ id: 'a', section_id: 's1', ord: 0 }),
      chunk({ id: 'b', section_id: 's2', ord: 0 }),
      chunk({ id: 'c', section_id: 's1', ord: 1 }),
    ])
    expect(groups.map(([sectionId]) => sectionId)).toEqual(['s1', 's2'])
    expect(groups[0]![1].map((entry) => entry.id)).toEqual(['a', 'c'])
  })
})

describe('DocumentViewer', () => {
  const noop = () => undefined

  it('shows flag icons with labels on flagged pages', () => {
    render(
      <DocumentViewer
        document={document({
          page_flags: [
            { page: 2, flags: ['low_text'] },
            { page: 4, flags: ['table_heavy'] },
          ],
        })}
        chunks={[
          chunk({ id: 'a', page: 2, ord: 0 }),
          chunk({ id: 'b', page: 4, ord: 1 }),
          chunk({ id: 'c', page: 7, ord: 2 }),
        ]}
        onClose={noop}
        onSaveTags={vi.fn()}
        onReindex={noop}
      />,
    )
    expect(screen.getByText('Scanned?')).toBeTruthy()
    expect(screen.getByText('Table-heavy')).toBeTruthy()
    expect(screen.getByText('page 7')).toBeTruthy()
  })

  it('groups chunks under their section heading path', () => {
    render(
      <DocumentViewer
        document={document({})}
        chunks={[
          chunk({ id: 'a', section_id: 's1', heading_path: 'Alpha', ord: 0 }),
          chunk({ id: 'b', section_id: 's2', heading_path: 'Beta', ord: 0 }),
        ]}
        onClose={noop}
        onSaveTags={vi.fn()}
        onReindex={noop}
      />,
    )
    expect(screen.getByText('Alpha')).toBeTruthy()
    expect(screen.getByText('Beta')).toBeTruthy()
  })

  it('surfaces the error and re-index action for failed documents', () => {
    render(
      <DocumentViewer
        document={document({ status: 'failed', error: 'Unsupported or unreadable document type' })}
        chunks={[]}
        onClose={noop}
        onSaveTags={vi.fn()}
        onReindex={noop}
      />,
    )
    expect(screen.getByText('Unsupported or unreadable document type')).toBeTruthy()
    expect(screen.getByText('Re-index document')).toBeTruthy()
  })
})

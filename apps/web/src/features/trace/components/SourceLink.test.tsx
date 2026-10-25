import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { SourceLink, safeHttpUrl } from './SourceLink'
import { CitationsTab } from './CitationsTab'

afterEach(cleanup)

describe('safeHttpUrl', () => {
  it('allows only http and https', () => {
    expect(safeHttpUrl('https://example.com/a')).toBe('https://example.com/a')
    expect(safeHttpUrl('http://example.com/')).toBe('http://example.com/')
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('data:text/html,<b>x</b>')).toBeNull()
    expect(safeHttpUrl('not a url')).toBeNull()
    expect(safeHttpUrl(null)).toBeNull()
  })
})

describe('SourceLink', () => {
  it('renders a safe link that opens in a new tab', () => {
    render(<SourceLink url="https://example.com/page" />)
    const link = screen.getByRole('link')
    expect(link.getAttribute('href')).toBe('https://example.com/page')
    expect(link.getAttribute('target')).toBe('_blank')
    expect(link.getAttribute('rel')).toBe('noopener noreferrer')
    expect(link.textContent).toContain('example.com')
  })
  it('renders an unsafe scheme as plain text', () => {
    render(<SourceLink url="javascript:alert(1)" />)
    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('javascript:alert(1)')).toBeTruthy()
  })
})

describe('CitationsTab web card', () => {
  it('shows the page title and link', () => {
    render(<CitationsTab chunks={[{ chunk_id: 'c1', document_name: 'Zebra facts', url: 'https://example.com/z', source_type: 'web', excerpt: 'x', fused_score: 1, dropped: false }]} />)
    expect(screen.getByText('Zebra facts')).toBeTruthy()
    expect(screen.getByRole('link').getAttribute('href')).toBe('https://example.com/z')
  })
})

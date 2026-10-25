import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { OcrBadge } from './OcrBadge'

afterEach(cleanup)

describe('OcrBadge', () => {
  it('renders nothing without OCR flags', () => {
    const { container } = render(<OcrBadge pageFlags={[{ page: 1, flags: ['low_text'] }]} />)
    expect(container.firstChild).toBeNull()
    cleanup()
    expect(render(<OcrBadge pageFlags={null} />).container.firstChild).toBeNull()
  })

  it('shows OCR when any page carries the ocr flag', () => {
    render(<OcrBadge pageFlags={[{ page: 1, flags: ['table_heavy'] }, { page: 3, flags: ['ocr'] }]} />)
    expect(screen.getByText('OCR')).toBeTruthy()
    expect(screen.queryByText(/low-confidence/)).toBeNull()
  })

  it('adds the low-confidence note and the skipped note', () => {
    render(<OcrBadge pageFlags={[{ page: 2, flags: ['ocr', 'ocr_low_confidence'] }, { page: 9, flags: ['ocr_skipped'] }]} />)
    expect(screen.getByText('low-confidence OCR')).toBeTruthy()
    expect(screen.getByText('scanned pages skipped')).toBeTruthy()
  })
})

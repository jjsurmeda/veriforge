import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { apiErrorMessage, UploadDropzone } from './UploadDropzone'

describe('apiErrorMessage', () => {
  it('reads the API error body message', () => {
    expect(apiErrorMessage({ error_code: 'unsupported_media_type', message: 'Unsupported media type' })).toBe(
      'Unsupported media type',
    )
  })

  it('falls back for unknown error shapes', () => {
    expect(apiErrorMessage(new Error('boom'))).toBe('Upload failed')
    expect(apiErrorMessage('nope')).toBe('Upload failed')
  })
})

describe('UploadDropzone', () => {
  it('surfaces a per-file error when the upload is rejected', async () => {
    const onUpload = vi.fn(async (file: File) => {
      if (file.name === 'evil.exe') {
        throw { error_code: 'unsupported_media_type', message: 'Unsupported media type' }
      }
    })
    render(<UploadDropzone disabled={false} onUpload={onUpload} />)

    const input = document.querySelector('input[type="file"]') as HTMLInputElement
    fireEvent.change(input, {
      target: {
        files: [
          new File(['%PDF-1.4'], 'paper.pdf', { type: 'application/pdf' }),
          new File(['MZ'], 'evil.exe', { type: 'application/octet-stream' }),
        ],
      },
    })

    await waitFor(() => {
      expect(screen.getByText('Unsupported media type')).toBeTruthy()
    })
    expect(screen.getByText('paper.pdf')).toBeTruthy()
    expect(screen.getByText('evil.exe')).toBeTruthy()
    expect(onUpload).toHaveBeenCalledTimes(2)
  })
})

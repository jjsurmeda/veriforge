import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

const { PanelError } = await import('./PanelError')

afterEach(cleanup)

describe('PanelError', () => {
  it('announces itself, keeps the design-system scale, and never leans on colour', () => {
    const { container } = render(
      <PanelError
        title="The Shared library could not be read."
        hint="Nothing was changed."
        action={<button>Try again</button>}
      />,
    )

    const alert = screen.getByRole('alert')
    // The sentence carries the state; `text-danger` is on the icon alone, so
    // the panel still reads correctly in monochrome or to a colour-blind eye.
    expect(container.querySelector('.text-danger')?.textContent).toBe('')
    expect(alert.textContent).toContain('could not be read')

    const title = screen.getByText('The Shared library could not be read.')
    expect(title.className).toContain('text-sm')
    expect(title.className).toContain('font-medium')
    expect(title.className).toContain('text-fg')

    const hint = screen.getByText('Nothing was changed.')
    expect(hint.className).toContain('text-xs')
    expect(hint.className).toContain('text-fg-muted')

    expect(container.innerHTML).not.toContain('font-serif')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('drops to the rail scale when compact', () => {
    const { container } = render(
      <PanelError compact title="Your chats could not be read." hint="Try again in a moment." />,
    )

    expect(screen.getByText('Your chats could not be read.').parentElement?.className).toContain('text-xs')
    expect(container.innerHTML).toContain('text-left')
    expect(container.innerHTML).not.toContain('text-center')
  })
})
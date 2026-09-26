import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

const { PanelEmpty } = await import('./PanelEmpty')

afterEach(cleanup)

describe('PanelEmpty', () => {
  it('uses only the design-system type scale: sans, body-small title, caption hint', () => {
    const { container } = render(
      <PanelEmpty title="Nothing here" hint="Something else will be." action={<button>Act</button>} />,
    )

    const title = screen.getByText('Nothing here')
    expect(title.className).toContain('text-sm')
    expect(title.className).toContain('font-medium')
    expect(title.className).toContain('text-fg')

    const hint = screen.getByText('Something else will be.')
    expect(hint.className).toContain('text-xs')
    expect(hint.className).toContain('text-fg-muted')

    expect(container.innerHTML).not.toContain('font-mono')
    expect(container.innerHTML).not.toContain('font-serif')
    expect(screen.getByRole('button', { name: 'Act' })).toBeTruthy()
  })
})

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@tanstack/react-router', () => ({ useNavigate: () => vi.fn() }))

vi.mock('../../../generated/sdk.gen', () => ({
  listModelsModelsGet: vi.fn(async () => ({
    data: [
      {
        model_id: 'nvidia/nemotron-3-super-120b-a12b:free',
        provider: 'openrouter',
        context_window: 262144,
        price_in: 0,
        price_out: 0,
        enabled: true,
        capabilities: null,
      },
      {
        model_id: 'openai/gpt-4o-mini',
        provider: 'openrouter',
        context_window: 128000,
        price_in: 0.15,
        price_out: 0.6,
        enabled: true,
        capabilities: null,
      },
    ],
  })),
}))

const { ChatComposer } = await import('./ChatComposer')
const { ModelPicker, isFree, shortModelName } = await import('./ModelPicker')
const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')

function withClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

Element.prototype.scrollIntoView = () => undefined
Element.prototype.hasPointerCapture = () => false
Element.prototype.setPointerCapture = () => undefined
Element.prototype.releasePointerCapture = () => undefined

afterEach(cleanup)

describe('model display helpers', () => {
  it('drops the provider prefix and the :free suffix', () => {
    expect(shortModelName('nvidia/nemotron-3-super-120b-a12b:free')).toBe('nemotron-3-super-120b-a12b')
    expect(shortModelName('gpt-4o-mini')).toBe('gpt-4o-mini')
  })

  it('treats only a zero price in and out as free', () => {
    const base = { provider: 'openrouter', context_window: 1, enabled: true, capabilities: null }
    expect(isFree({ ...base, model_id: 'a', price_in: 0, price_out: 0 })).toBe(true)
    expect(isFree({ ...base, model_id: 'b', price_in: 0, price_out: 0.6 })).toBe(false)
    expect(isFree({ ...base, model_id: 'c', price_in: null, price_out: null })).toBe(false)
  })
})

describe('ModelPicker', () => {
  it('lists the catalogue and fires onChange', async () => {
    const onChange = vi.fn()
    withClient(<ModelPicker value="openai/gpt-4o-mini" onChange={onChange} />)

    const trigger = screen.getByRole('combobox', { name: 'Model' })
    await waitFor(() => expect(trigger.textContent).toContain('gpt-4o-mini'))

    fireEvent.keyDown(trigger, { key: 'ArrowDown' })
    const option = await screen.findByRole('option', { name: /nemotron-3-super-120b-a12b/ })
    expect(option.textContent).toContain('Free')
    expect(option.textContent).toContain('262k')

    fireEvent.click(option)
    expect(onChange).toHaveBeenCalledWith('nvidia/nemotron-3-super-120b-a12b:free')
  })
})

describe('ChatComposer', () => {
  const noop = () => undefined

  it('renders no attach button and no context meter', () => {
    withClient(
      <ChatComposer
        streaming={false}
        modelId={null}
        onFiles={noop}
        onModelChange={noop}
        onSend={noop}
        onStop={noop}
      />,
    )

    expect(screen.queryByRole('button', { name: 'Add sources' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Run settings' })).toBeNull()
    expect(screen.queryByText(/source[s]?$/)).toBeNull()
    expect(document.querySelector('input[type="file"]')).toBeNull()
    expect(screen.getByRole('textbox', { name: 'Question' })).toBeTruthy()
  })

  it('accepts dropped files without any visible attach chrome', () => {
    const onFiles = vi.fn()
    withClient(
      <ChatComposer
        streaming={false}
        modelId={null}
        onFiles={onFiles}
        onModelChange={noop}
        onSend={noop}
        onStop={noop}
      />,
    )

    const file = new File(['hi'], 'note.txt', { type: 'text/plain' })
    fireEvent.drop(screen.getByRole('textbox', { name: 'Question' }), { dataTransfer: { files: [file] } })
    expect(onFiles).toHaveBeenCalledWith([file])
  })
})

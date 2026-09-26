import { useState } from 'react'
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
      {
        model_id: 'anthropic/claude-haiku-4.5',
        provider: 'anthropic',
        context_window: 200000,
        price_in: 1,
        price_out: 5,
        enabled: true,
        capabilities: null,
      },
    ],
  })),
}))

const { ChatComposer, runOptions } = await import('./ChatComposer')
const { ModelPicker, isFree, shortModelName } = await import('./ModelPicker')
const { TooltipProvider } = await import('../../../components/ui/primitives')
const { QueryClient, QueryClientProvider } = await import('@tanstack/react-query')

function withClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <TooltipProvider>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </TooltipProvider>,
  )
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
  it('renders every model from /models, grouped by provider', async () => {
    withClient(<ModelPicker value="openai/gpt-4o-mini" onChange={vi.fn()} />)

    const trigger = screen.getByRole('button', { name: 'Model' })
    await waitFor(() => expect(trigger.textContent).toContain('gpt-4o-mini'))
    fireEvent.click(trigger)

    const options = await screen.findAllByRole('option')
    expect(options).toHaveLength(3)
    expect(options.map((option) => option.textContent)).toEqual([
      expect.stringContaining('nemotron-3-super-120b-a12b'),
      expect.stringContaining('gpt-4o-mini'),
      expect.stringContaining('claude-haiku-4.5'),
    ])
    expect(screen.getByRole('group', { name: 'openrouter' })).toBeTruthy()
    expect(screen.getByRole('group', { name: 'anthropic' })).toBeTruthy()
    expect(screen.getByText('262k · Free')).toBeTruthy()
  })

  it('marks the current model and fires onChange for another', async () => {
    const onChange = vi.fn()
    withClient(<ModelPicker value="openai/gpt-4o-mini" onChange={onChange} />)

    const trigger = screen.getByRole('button', { name: 'Model' })
    await waitFor(() => expect(trigger.textContent).toContain('gpt-4o-mini'))
    fireEvent.click(trigger)
    const current = await screen.findByRole('option', { name: /gpt-4o-mini/ })
    expect(current.getAttribute('aria-selected')).toBe('true')

    fireEvent.click(screen.getByRole('option', { name: /claude-haiku-4.5/ }))
    expect(onChange).toHaveBeenCalledWith('anthropic/claude-haiku-4.5')
  })

  it('is keyboard navigable', async () => {
    const onChange = vi.fn()
    withClient(<ModelPicker value="openai/gpt-4o-mini" onChange={onChange} />)

    const trigger = screen.getByRole('button', { name: 'Model' })
    await waitFor(() => expect(trigger.textContent).toContain('gpt-4o-mini'))
    fireEvent.click(trigger)
    const listbox = await screen.findByRole('listbox', { name: 'Models' })
    fireEvent.keyDown(listbox, { key: 'ArrowDown' })
    await waitFor(() =>
      expect(listbox.getAttribute('aria-activedescendant')).toContain('claude-haiku-4.5'),
    )

    fireEvent.keyDown(listbox, { key: 'Enter' })
    expect(onChange).toHaveBeenCalledWith('anthropic/claude-haiku-4.5')
  })
})

describe('ChatComposer', () => {
  const noop = () => undefined

  function renderComposer(overrides: Record<string, unknown> = {}) {
    const props = {
      streaming: false,
      modelId: null,
      deep: false,
      web: false,
      onFiles: noop,
      onModelChange: noop,
      onToggleDeep: noop,
      onToggleWeb: noop,
      onSend: noop,
      onStop: noop,
      ...overrides,
    }
    return withClient(<ChatComposer {...props} />)
  }

  it('maps the toggles to mode and source in the run request', () => {
    const onSend = vi.fn()

    function Harness() {
      const [deep, setDeep] = useState(false)
      const [web, setWeb] = useState(false)
      return (
        <ChatComposer
          streaming={false}
          modelId={null}
          deep={deep}
          web={web}
          onFiles={noop}
          onModelChange={noop}
          onToggleDeep={setDeep}
          onToggleWeb={setWeb}
          onSend={onSend}
          onStop={noop}
        />
      )
    }
    withClient(<Harness />)

    const send = (value: string) => {
      fireEvent.change(screen.getByRole('textbox', { name: 'Question' }), {
        target: { value },
      })
      fireEvent.click(screen.getByRole('button', { name: 'Send' }))
    }

    send('plain question')
    expect(onSend).toHaveBeenLastCalledWith('plain question', { mode: 'auto', source: 'upload' })

    fireEvent.click(screen.getByRole('button', { name: 'Deep' }))
    expect(screen.getByRole('button', { name: 'Deep' }).getAttribute('aria-pressed')).toBe('true')
    send('deep question')
    expect(onSend).toHaveBeenLastCalledWith('deep question', { mode: 'deep', source: 'upload' })

    fireEvent.click(screen.getByRole('button', { name: 'Web' }))
    send('both question')
    expect(onSend).toHaveBeenLastCalledWith('both question', { mode: 'deep', source: 'both' })
  })

  it('runOptions covers both toggle states', () => {
    expect(runOptions(false, false)).toEqual({ mode: 'auto', source: 'upload' })
    expect(runOptions(true, false)).toEqual({ mode: 'deep', source: 'upload' })
    expect(runOptions(false, true)).toEqual({ mode: 'auto', source: 'both' })
    expect(runOptions(true, true)).toEqual({ mode: 'deep', source: 'both' })
  })

  it('opens the file picker from the + and hands the files over', () => {
    const onFiles = vi.fn()
    renderComposer({ onFiles })

    expect(screen.getByRole('button', { name: 'Add sources' })).toBeTruthy()
    const file = new File(['hi'], 'note.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Add sources to the chat'), {
      target: { files: [file] },
    })
    expect(onFiles).toHaveBeenCalledWith([file])
  })

  it('accepts dropped files', () => {
    const onFiles = vi.fn()
    renderComposer({ onFiles })

    const file = new File(['hi'], 'note.txt', { type: 'text/plain' })
    fireEvent.drop(screen.getByRole('textbox', { name: 'Question' }), {
      dataTransfer: { files: [file] },
    })
    expect(onFiles).toHaveBeenCalledWith([file])
  })
})

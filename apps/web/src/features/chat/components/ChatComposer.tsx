import { useRef } from 'react'

import { ModelPicker } from './ModelPicker'

interface Props {
  streaming: boolean
  modelId: string | null
  onModelChange: (modelId: string) => void
  onSend: (message: string) => void
  onStop: () => void
}

export function ChatComposer({ streaming, modelId, onModelChange, onSend, onStop }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming) return
    onSend(value)
    if (textareaRef.current) textareaRef.current.value = ''
  }

  return (
    <div className="border-t border-mist bg-graphite px-4 py-3">
      <div className="mx-auto max-w-[72ch]">
        <textarea
          ref={textareaRef}
          rows={3}
          placeholder={streaming ? 'Streaming…' : 'Ask a question'}
          disabled={streaming}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault()
              submit()
            }
          }}
          className="w-full resize-y rounded border border-mist bg-ink px-3 py-2 text-[0.9375rem] text-paper placeholder:text-paper/30 focus-visible:outline-2 focus-visible:outline-ember"
        />
        <div className="mt-2 flex items-center justify-between">
          <ModelPicker value={modelId} disabled={streaming} onChange={onModelChange} />
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="rounded bg-ember px-4 py-1.5 text-sm font-medium text-ink hover:brightness-110 focus-visible:outline-2 focus-visible:outline-paper"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              className="rounded border border-mist px-4 py-1.5 text-sm text-paper hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

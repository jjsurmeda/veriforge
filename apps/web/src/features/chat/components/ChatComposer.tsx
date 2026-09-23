import { useRef, useState } from 'react'

import { ModelPicker } from './ModelPicker'
import { ModePicker, type RunMode } from './ModePicker'
import { SourcePicker, type RunSource } from './SourcePicker'

interface Props {
  streaming: boolean
  modelId: string | null
  onModelChange: (modelId: string) => void
  onSend: (message: string, options: { mode: RunMode; source: RunSource }) => void
  onStop: () => void
}

export function ChatComposer({ streaming, modelId, onModelChange, onSend, onStop }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mode, setMode] = useState<RunMode>('auto')
  const [source, setSource] = useState<RunSource>('auto')
  const [deepNotice, setDeepNotice] = useState(false)

  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming) return
    onSend(value, { mode, source })
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
        {deepNotice && (
          <p className="mt-1 text-xs text-paper/60">
            Deep mode ships in slice 5 — this run will execute as Auto.
          </p>
        )}
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <ModelPicker value={modelId} disabled={streaming} onChange={onModelChange} />
            <ModePicker
              value={mode}
              disabled={streaming}
              onChange={setMode}
              onDeepBlocked={() => {
                setDeepNotice(true)
                window.setTimeout(() => setDeepNotice(false), 5000)
              }}
            />
            <SourcePicker value={source} disabled={streaming} onChange={setSource} />
          </div>
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

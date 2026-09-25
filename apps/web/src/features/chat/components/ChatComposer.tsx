import { useRef, useState } from 'react'
import { ArrowUp, CircleAlert, Square } from 'lucide-react'

import type { QuotaOut } from '../../../generated/types.gen'
import { ModelPicker } from './ModelPicker'
import { ModePicker, type RunMode } from './ModePicker'
import { SourcePicker, type RunSource } from './SourcePicker'

interface Props {
  streaming: boolean
  modelId: string | null
  quota?: QuotaOut
  error?: string | null
  emptyThread?: boolean
  onFiles: (files: File[]) => void
  onModelChange: (modelId: string) => void
  onSend: (message: string, options: { mode: RunMode; source: RunSource }) => void
  onStop: () => void
}

export function ChatComposer({
  streaming,
  modelId,
  quota,
  error,
  emptyThread = false,
  onFiles,
  onModelChange,
  onSend,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mode, setMode] = useState<RunMode>('auto')
  const [source, setSource] = useState<RunSource>('auto')
  const [dragOver, setDragOver] = useState(false)
  const blocked = quota?.blocked ?? false

  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming || blocked) return
    onSend(value, { mode, source })
    if (textareaRef.current) {
      textareaRef.current.value = ''
      textareaRef.current.style.height = 'auto'
    }
  }

  return (
    <div className="sticky bottom-0 z-20 bg-main px-3 pb-3 pt-6 sm:px-6 sm:pb-4 sm:pt-8">
      <div className="pointer-events-none absolute inset-x-0 bottom-full h-6 bg-gradient-to-t from-main to-transparent" aria-hidden="true" />
      <div className="relative mx-auto max-w-[720px]">
        {error && (
          <div role="alert" className="mb-2 flex items-start gap-2 rounded-lg border border-border/30 bg-raised px-3 py-2 text-sm text-danger">
            <CircleAlert size={16} strokeWidth={1.75} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        <div
          onDragOver={(event) => {
            event.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragOver(false)
            if (event.dataTransfer.files.length > 0) {
              onFiles(Array.from(event.dataTransfer.files))
            }
          }}
          className={`rounded-3xl border bg-surface p-2 transition-[border-color] duration-150 focus-within:border-border-strong/60 ${dragOver ? 'border-fg-muted' : 'border-border'}`}
        >
          <textarea
            ref={textareaRef}
            aria-label="Question"
            rows={2}
            placeholder={blocked ? 'Credit limit reached' : streaming ? 'Streaming…' : emptyThread ? 'Ask anything' : 'Ask a follow-up'}
            disabled={streaming || blocked}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            onInput={(event) => {
              const target = event.currentTarget
              target.style.height = 'auto'
              target.style.height = `${Math.min(target.scrollHeight, 160)}px`
            }}
            className="block max-h-40 min-h-14 w-full resize-none rounded-2xl border-0 bg-transparent px-3 py-2.5 text-base leading-6 text-fg outline-none placeholder:text-fg-muted/80 disabled:cursor-not-allowed disabled:opacity-60"
          />
          <div className="flex items-center justify-between gap-2 px-1 pt-2">
            <div className="flex min-w-0 items-center gap-1 overflow-x-auto">
              <ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} />
              <div className="hidden sm:block"><SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} /></div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <div className="hidden sm:block"><ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} /></div>
              {streaming ? (
                <button type="button" aria-label="Stop" onClick={onStop} className="pressable inline-flex size-8 items-center justify-center rounded-full bg-fg-strong text-on-strong hover:bg-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
                  <Square size={15} fill="currentColor" strokeWidth={1.75} aria-hidden="true" />
                  <span className="sr-only">Stop</span>
                </button>
              ) : (
                <button type="button" aria-label="Send" onClick={submit} disabled={blocked} className="pressable inline-flex size-8 items-center justify-center rounded-full bg-fg-strong text-on-strong hover:bg-fg disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
                  <ArrowUp size={18} strokeWidth={1.75} aria-hidden="true" />
                  <span className="sr-only">Send</span>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

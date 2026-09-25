import { useRef, useState } from 'react'
import { ArrowUp, CircleAlert, Paperclip, Plus, Square, X } from 'lucide-react'

import { PopoverClose, PopoverContent, PopoverRoot, PopoverTrigger } from '../../../components/ui/primitives'

import type { QuotaOut } from '../../../generated/types.gen'
import { ModelPicker } from './ModelPicker'
import { ModePicker, type RunMode } from './ModePicker'
import { SourcePicker, type RunSource } from './SourcePicker'

interface Props {
  streaming: boolean
  modelId: string | null
  quota?: QuotaOut
  sourceCount: number
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
  sourceCount,
  error,
  emptyThread = false,
  onFiles,
  onModelChange,
  onSend,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<RunMode>('auto')
  const [source, setSource] = useState<RunSource>('auto')
  const [settingsOpen, setSettingsOpen] = useState(false)
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

  const openFilePicker = () => fileInputRef.current?.click()

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
              <PopoverRoot open={settingsOpen} onOpenChange={setSettingsOpen}>
                <PopoverTrigger asChild><button type="button" aria-label="Run settings" aria-expanded={settingsOpen} disabled={streaming || blocked} className="icon-button size-8 shrink-0 disabled:cursor-not-allowed disabled:opacity-50"><Plus size={17} strokeWidth={1.75} aria-hidden="true" /></button></PopoverTrigger>
                <PopoverContent side="top" align="start" className="w-[min(28rem,calc(100vw-1.5rem))] p-3"><div className="mb-2 flex items-center justify-between px-1"><p className="text-xs font-medium text-fg">Run settings</p><PopoverClose asChild><button type="button" aria-label="Close settings" className="icon-button size-7"><X size={14} strokeWidth={1.75} aria-hidden="true" /></button></PopoverClose></div><div className="space-y-3 rounded-xl border border-border bg-surface p-3"><ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} /><ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} /><SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} /></div></PopoverContent>
              </PopoverRoot>
              <button
                type="button"
                aria-label="Add sources"
                onClick={openFilePicker}
                disabled={streaming || blocked}
                className="pressable inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-sm text-fg-muted hover:bg-raised hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              >
                <Paperclip size={14} strokeWidth={1.75} aria-hidden="true" />
                {sourceCount} source{sourceCount === 1 ? '' : 's'}
              </button>
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
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            aria-label="Source files"
            onChange={(event) => {
              onFiles(Array.from(event.currentTarget.files ?? []))
              event.currentTarget.value = ''
            }}
          />
        </div>
      </div>
    </div>
  )
}

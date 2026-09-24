import { useRef, useState } from 'react'
import { CircleAlert, Send, Settings2, Square } from 'lucide-react'

import type { CollectionOut, QuotaOut } from '../../../generated/types.gen'
import { CollectionPicker } from './CollectionPicker'
import { ModelPicker } from './ModelPicker'
import { ModePicker, type RunMode } from './ModePicker'
import { SourcePicker, type RunSource } from './SourcePicker'

interface Props {
  streaming: boolean
  modelId: string | null
  quota?: QuotaOut
  collections: CollectionOut[]
  collectionIds: string[]
  error?: string | null
  onModelChange: (modelId: string) => void
  onCollectionChange: (collectionIds: string[]) => void
  onSend: (message: string, options: { mode: RunMode; source: RunSource }) => void
  onStop: () => void
}

export function ChatComposer({
  streaming,
  modelId,
  quota,
  collections,
  collectionIds,
  error,
  onModelChange,
  onCollectionChange,
  onSend,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mode, setMode] = useState<RunMode>('auto')
  const [source, setSource] = useState<RunSource>('auto')
  const [settingsOpen, setSettingsOpen] = useState(false)

  const blocked = quota?.blocked ?? false
  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming || blocked) return
    onSend(value, { mode, source })
    if (textareaRef.current) textareaRef.current.value = ''
  }

  return (
    <div className="border-t border-border bg-surface/95 px-4 py-4 shadow-[0_-10px_30px_rgb(24_34_56_/_0.06)] backdrop-blur">
      <div className="mx-auto max-w-[72ch]">
        {error && (
          <div role="alert" className="mb-3 flex items-start gap-2 rounded-lg border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
            <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}
        <div className="rounded-xl border border-border bg-background p-2 shadow-sm transition-[border-color,box-shadow] duration-200 focus-within:border-primary/50 focus-within:shadow-md motion-reduce:transition-none">
          <textarea
            ref={textareaRef}
            aria-label="Question"
            rows={3}
            placeholder={blocked ? 'Credit limit reached' : streaming ? 'Streaming…' : 'Ask a question'}
            disabled={streaming || blocked}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                submit()
              }
            }}
            className="min-h-20 w-full resize-y rounded-lg border-0 bg-transparent px-2 py-2 text-[0.9375rem] leading-6 text-foreground outline-none placeholder:text-muted-foreground/70 disabled:cursor-not-allowed disabled:opacity-60"
          />
          <div className="flex items-center justify-between gap-2 border-t border-border/70 px-1 pt-2">
            <button
              type="button"
              aria-label="Run settings"
              aria-expanded={settingsOpen}
              onClick={() => setSettingsOpen((open) => !open)}
              disabled={streaming || blocked}
              className="inline-flex min-h-8 items-center gap-2 rounded-lg px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-primary-soft hover:text-primary active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
            >
              <Settings2 size={15} aria-hidden="true" />
              <span className="hidden sm:inline">Settings</span>
              <span className="font-mono text-[0.65rem] uppercase tracking-[0.08em] text-muted-foreground/80">
                {mode} · {source}
              </span>
            </button>
            <div className="flex items-center gap-2">
              {collectionIds.length > 0 && (
                <span className="hidden rounded-full bg-secondary-soft px-2 py-1 font-mono text-[0.65rem] text-secondary sm:inline-flex">
                  {collectionIds.length} {collectionIds.length === 1 ? 'source' : 'sources'}
                </span>
              )}
              {streaming ? (
                <button
                  type="button"
                  onClick={onStop}
                  className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-danger px-4 py-2 text-sm font-semibold text-white shadow-sm transition-[filter,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:brightness-105 hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger motion-reduce:transform-none motion-reduce:transition-none"
                >
                  <Square size={14} fill="currentColor" aria-hidden="true" />
                  Stop
                </button>
              ) : (
                <button
                  type="button"
                  onClick={submit}
                  disabled={blocked}
                  className="inline-flex min-h-9 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transform-none motion-reduce:transition-none"
                >
                  <Send size={15} aria-hidden="true" />
                  Send
                </button>
              )}
            </div>
          </div>
          {settingsOpen && (
            <div className="mt-3 grid gap-3 border-t border-border/70 px-1 pt-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
              <div className="grid content-start gap-3 rounded-lg bg-surface p-3">
                <ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} />
                <div className="grid grid-cols-2 gap-3">
                  <ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} />
                  <SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} />
                </div>
              </div>
              <CollectionPicker
                collections={collections}
                value={collectionIds}
                onChange={onCollectionChange}
                disabled={streaming || blocked}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

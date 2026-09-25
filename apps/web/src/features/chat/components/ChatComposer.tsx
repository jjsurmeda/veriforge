import { useRef, useState } from 'react'
import { ArrowUp, CircleAlert, Plus, Square, X } from 'lucide-react'

import { PopoverClose, PopoverContent, PopoverRoot, PopoverTrigger } from '../../../components/ui/primitives'

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
  emptyThread?: boolean
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
  emptyThread = false,
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
  const selectedCollections = collections.filter((collection) => collectionIds.includes(collection.id))

  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming || blocked) return
    onSend(value, { mode, source })
    if (textareaRef.current) {
      textareaRef.current.value = ''
      textareaRef.current.style.height = 'auto'
    }
  }

  const removeCollection = (collectionId: string) => {
    onCollectionChange(collectionIds.filter((id) => id !== collectionId))
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
        <div className="rounded-3xl border border-border bg-surface p-2 shadow-none transition-[border-color,box-shadow] duration-150 focus-within:border-border-strong/60 focus-within:shadow-none">
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
          {selectedCollections.length > 0 && (
            <div className="flex flex-wrap gap-1.5 px-2 pb-1">
              {selectedCollections.map((collection) => (
                <span key={collection.id} className="inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-raised px-2 py-1 text-xs text-fg-muted">
                  <span className="max-w-[12rem] truncate">{collection.name}</span>
                  <button type="button" aria-label={`Remove ${collection.name} collection`} onClick={() => removeCollection(collection.id)} className="icon-button size-4 rounded-full text-fg-muted hover:text-danger">
                    <X size={11} strokeWidth={1.75} aria-hidden="true" />
                  </button>
                </span>
              ))}
            </div>
          )}
          <div className="flex items-center justify-between gap-2 px-1 pt-2">
            <div className="flex min-w-0 items-center gap-1 overflow-x-auto">
              <PopoverRoot open={settingsOpen} onOpenChange={setSettingsOpen}>
                <PopoverTrigger asChild><button type="button" aria-label="Run settings" aria-expanded={settingsOpen} disabled={streaming || blocked} className="icon-button size-8 shrink-0 disabled:cursor-not-allowed disabled:opacity-50"><Plus size={17} strokeWidth={1.75} aria-hidden="true" /></button></PopoverTrigger>
                <PopoverContent side="top" align="start" className="w-[min(28rem,calc(100vw-1.5rem))] p-3"><div className="mb-2 flex items-center justify-between px-1"><p className="text-xs font-medium text-fg">Run settings</p><PopoverClose asChild><button type="button" aria-label="Close settings" className="icon-button size-7"><X size={14} strokeWidth={1.75} aria-hidden="true" /></button></PopoverClose></div><div className="grid gap-3 sm:grid-cols-2"><div className="space-y-2 rounded-xl border border-border bg-surface p-3"><ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} /><ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} /><SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} /></div><CollectionPicker collections={collections} value={collectionIds} onChange={onCollectionChange} disabled={streaming || blocked} /></div></PopoverContent>
              </PopoverRoot>
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

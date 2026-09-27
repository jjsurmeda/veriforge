import { useRef, useState, type ReactNode } from 'react'
import { ArrowUp, CircleAlert, Globe2, Layers3, Plus, Square } from 'lucide-react'

import type { QuotaOut } from '../../../generated/types.gen'
import { IconButton } from '../../../components/ui/IconButton'
import {
  TooltipContent,
  TooltipRoot,
  TooltipTrigger,
} from '../../../components/ui/primitives'
import { ModelPicker } from './ModelPicker'

// Narrower than the API's RunCreateRequest on purpose: the composer only
// sends these, while the eval runner still uses fast and web.
export type RunMode = 'auto' | 'deep'
export type RunSource = 'upload' | 'both'

export function runOptions(deep: boolean, web: boolean): { mode: RunMode; source: RunSource } {
  return { mode: deep ? 'deep' : 'auto', source: web ? 'both' : 'upload' }
}

interface Props {
  streaming: boolean
  modelId: string | null
  quota?: QuotaOut
  error?: string | null
  emptyThread?: boolean
  deep: boolean
  web: boolean
  onFiles: (files: File[]) => void
  onModelChange: (modelId: string) => void
  onToggleDeep: (value: boolean) => void
  onToggleWeb: (value: boolean) => void
  onSend: (message: string, options: { mode: RunMode; source: RunSource }) => void
  onStop: () => void
}

function ToggleChip({
  icon,
  label,
  pressed,
  disabled,
  onToggle,
}: {
  icon: ReactNode
  label: string
  pressed: boolean
  disabled?: boolean
  onToggle: (value: boolean) => void
}) {
  return (
    <button
      type="button"
      aria-pressed={pressed}
      disabled={disabled}
      onClick={() => onToggle(!pressed)}
      className={`pressable inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs transition-[background-color,color,border-color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-40 ${
        pressed
          ? 'border border-border-strong bg-raised text-fg'
          : 'border border-transparent text-fg-muted hover:bg-raised-hover hover:text-fg'
      }`}
    >
      {icon}
      {label}
    </button>
  )
}

export function ChatComposer({
  streaming,
  modelId,
  quota,
  error,
  emptyThread = false,
  deep,
  web,
  onFiles,
  onModelChange,
  onToggleDeep,
  onToggleWeb,
  onSend,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const blocked = quota?.blocked ?? false
  const disabled = streaming || blocked

  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || disabled) return
    onSend(value, runOptions(deep, web))
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
              <TooltipRoot>
                <TooltipTrigger asChild>
                  <IconButton
                    size={32}
                    aria-label="Add sources"
                    disabled={disabled}
                    onClick={() => fileInputRef.current?.click()}
                    className="shrink-0 border border-border bg-surface text-fg-muted hover:bg-raised-hover hover:text-fg"
                  >
                    <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
                  </IconButton>
                </TooltipTrigger>
                <TooltipContent>Add sources</TooltipContent>
              </TooltipRoot>
              <ToggleChip
                icon={<Layers3 size={14} strokeWidth={1.75} aria-hidden="true" />}
                label="Deep"
                pressed={deep}
                disabled={disabled}
                onToggle={onToggleDeep}
              />
              <ToggleChip
                icon={<Globe2 size={14} strokeWidth={1.75} aria-hidden="true" />}
                label="Web"
                pressed={web}
                disabled={disabled}
                onToggle={onToggleWeb}
              />
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <ModelPicker value={modelId} disabled={disabled} onChange={onModelChange} />
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
            aria-label="Add sources to the chat"
            onChange={(event) => {
              const files = Array.from(event.currentTarget.files ?? [])
              event.currentTarget.value = ''
              if (files.length > 0) onFiles(files)
            }}
          />
        </div>
      </div>
    </div>
  )
}

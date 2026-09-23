import { useEffect, useRef, useState } from 'react'

import type { QuotaOut } from '../../../generated/types.gen'
import { ModelPicker } from './ModelPicker'
import { ModePicker, type RunMode } from './ModePicker'
import { SourcePicker, type RunSource } from './SourcePicker'

interface Props {
  streaming: boolean
  modelId: string | null
  quota?: QuotaOut
  error?: string | null
  onModelChange: (modelId: string) => void
  onSend: (message: string, options: { mode: RunMode; source: RunSource }) => void
  onStop: () => void
}

const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

function countdown(target: string, now: number): string {
  const seconds = Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000))
  if (seconds === 0) return 'now'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

export function ChatComposer({
  streaming,
  modelId,
  quota,
  error,
  onModelChange,
  onSend,
  onStop,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [mode, setMode] = useState<RunMode>('auto')
  const [source, setSource] = useState<RunSource>('auto')
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(timer)
  }, [])

  const blocked = quota?.blocked ?? false
  const submit = () => {
    const value = textareaRef.current?.value.trim() ?? ''
    if (!value || streaming || blocked) return
    onSend(value, { mode, source })
    if (textareaRef.current) textareaRef.current.value = ''
  }

  return (
    <div className="border-t border-mist bg-graphite px-4 py-3">
      <div className="mx-auto max-w-[72ch]">
        {quota && (
          <div className="mb-2 space-y-1 text-xs text-paper/60" aria-live="polite">
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <span>
                5h <span className="font-mono text-paper">{number.format(quota.remaining_5h)}</span>
                <span className="text-paper/40"> / {number.format(quota.limit_5h)}</span>
                <span className="ml-1 text-paper/40">resets {countdown(quota.reset_at_5h, now)}</span>
              </span>
              <span>
                month <span className="font-mono text-paper">{number.format(quota.remaining_month)}</span>
                <span className="text-paper/40"> / {number.format(quota.limit_month)}</span>
                <span className="ml-1 text-paper/40">resets {countdown(quota.reset_at_month, now)}</span>
              </span>
            </div>
            {blocked && (
              <p role="alert" className="text-amber-verdict">
                Credit limit reached. New questions resume when the oldest 5h credit ages out
                {quota.reset_at_5h ? ` (${countdown(quota.reset_at_5h, now)})` : ''}.
              </p>
            )}
          </div>
        )}
        {error && (
          <p role="alert" className="mb-2 text-sm text-rust">
            {error}
          </p>
        )}
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
          className="w-full resize-y rounded border border-mist bg-ink px-3 py-2 text-[0.9375rem] text-paper placeholder:text-paper/30 focus-visible:outline-2 focus-visible:outline-ember disabled:cursor-not-allowed disabled:opacity-60"
        />
        <div className="mt-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} />
            <ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} />
            <SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} />
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
              disabled={blocked}
              className="rounded border border-mist px-4 py-1.5 text-sm text-paper hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember disabled:cursor-not-allowed disabled:opacity-50"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

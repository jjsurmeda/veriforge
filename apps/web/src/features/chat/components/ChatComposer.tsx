import { useEffect, useRef, useState } from 'react'

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

const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

function countdown(target: string, now: number): string {
  const seconds = Math.max(0, Math.floor((new Date(target).getTime() - now) / 1000))
  if (seconds === 0) return 'now'
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
}

function quotaPercent(remaining: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min(100, Math.max(0, (remaining / limit) * 100))
}

function QuotaMeter({ quota, now }: { quota: QuotaOut; now: number }) {
  const windows = [
    { label: '5h', remaining: quota.remaining_5h, limit: quota.limit_5h, reset: quota.reset_at_5h },
    {
      label: 'month',
      remaining: quota.remaining_month,
      limit: quota.limit_month,
      reset: quota.reset_at_month,
    },
  ]
  return (
    <div className="mb-3 grid gap-2 sm:grid-cols-2" aria-label="Credit quota" aria-live="polite">
      {windows.map((window) => {
        const percent = quotaPercent(window.remaining, window.limit)
        return (
          <div
            key={window.label}
            role="group"
            aria-label={`${window.label} quota`}
            className="rounded-sm border border-mist/60 bg-ink/30 px-2.5 py-2"
          >
            <div className="flex items-baseline justify-between gap-2">
              <span className="font-mono text-[0.65rem] tracking-[0.08em] text-paper/50">
                {window.label}
              </span>
              <span className="font-mono text-xs text-paper/85">
                {number.format(window.remaining)} <span className="text-paper/40">/ {number.format(window.limit)}</span>
              </span>
            </div>
            <div
              className="mt-1.5 h-1 overflow-hidden rounded-full bg-mist/50"
              role="progressbar"
              aria-label={`${window.label} credits remaining`}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(percent)}
            >
              <div
                className={`h-full rounded-full ${quota.blocked ? 'bg-amber-verdict' : 'bg-patina'}`}
                style={{ width: `${percent}%` }}
              />
            </div>
            <p className="mt-1 text-[0.65rem] text-paper/45">resets {countdown(window.reset, now)}</p>
          </div>
        )
      })}
      {quota.blocked && (
        <p role="alert" className="col-span-full text-xs text-amber-verdict">
          Credit limit reached. New questions resume when the oldest 5h credit ages out
          {quota.reset_at_5h ? ` (${countdown(quota.reset_at_5h, now)})` : ''}.
        </p>
      )}
    </div>
  )
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
    <div className="border-t border-mist bg-graphite/95 px-4 py-3">
      <div className="mx-auto max-w-[72ch]">
        {quota && <QuotaMeter quota={quota} now={now} />}
        {error && (
          <p role="alert" className="mb-2 text-sm text-rust">
            {error}
          </p>
        )}
        <div className="mb-2">
          <CollectionPicker
            collections={collections}
            value={collectionIds}
            onChange={onCollectionChange}
            disabled={streaming || blocked}
          />
        </div>
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
           className="min-h-24 w-full resize-y rounded-sm border border-mist bg-ink px-3 py-2.5 text-[0.9375rem] leading-6 text-paper placeholder:text-paper/35 transition-colors duration-150 hover:border-paper/35 focus:border-ember/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none"
        />
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <ModelPicker value={modelId} disabled={streaming || blocked} onChange={onModelChange} />
            <ModePicker value={mode} disabled={streaming || blocked} onChange={setMode} />
            <SourcePicker value={source} disabled={streaming || blocked} onChange={setSource} />
          </div>
          {streaming ? (
            <button
              type="button"
              onClick={onStop}
              className="min-h-8 rounded-sm bg-ember px-4 py-1.5 text-sm font-medium text-ink transition-[filter,transform] duration-150 hover:brightness-110 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-paper motion-reduce:transition-none"
            >
              Stop
            </button>
          ) : (
            <button
              type="button"
              onClick={submit}
              disabled={blocked}
              className="min-h-8 rounded-sm border border-mist bg-ink/40 px-4 py-1.5 text-sm text-paper transition-[background-color,border-color,transform] duration-150 hover:border-paper/50 hover:bg-mist/30 active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
            >
              Send
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

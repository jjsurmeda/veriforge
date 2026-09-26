import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Search } from 'lucide-react'

import type { ModelOut } from '../../../generated/types.gen'
import { useModels } from '../hooks/useModels'
import { PopoverContent, PopoverRoot, PopoverTrigger } from '../../../components/ui/primitives'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

const SEARCH_THRESHOLD = 8

export function shortModelName(modelId: string): string {
  const withoutProvider = modelId.includes('/') ? modelId.slice(modelId.indexOf('/') + 1) : modelId
  return withoutProvider.replace(/:free$/, '')
}

export function isFree(model: ModelOut): boolean {
  return model.price_in === 0 && model.price_out === 0
}

function contextLabel(contextWindow: number | null): string {
  if (!contextWindow) return ''
  return contextWindow >= 1000 ? `${Math.round(contextWindow / 1000)}k` : String(contextWindow)
}

function metaLabel(model: ModelOut): string {
  return [contextLabel(model.context_window), isFree(model) ? 'Free' : '']
    .filter(Boolean)
    .join(' · ')
}

export function groupByProvider(models: ModelOut[]): Array<[string, ModelOut[]]> {
  const groups = new Map<string, ModelOut[]>()
  for (const model of models) {
    const bucket = groups.get(model.provider) ?? []
    bucket.push(model)
    groups.set(model.provider, bucket)
  }
  return [...groups.entries()]
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  const all = models ?? []
  const selected = all.find((model) => model.model_id === value)

  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)

  const groups = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const matched = needle
      ? all.filter((model) => shortModelName(model.model_id).toLowerCase().includes(needle))
      : all
    return groupByProvider(matched)
  }, [all, query])
  const flat = useMemo(() => groups.flatMap(([, entries]) => entries), [groups])
  const searchable = all.length > SEARCH_THRESHOLD
  // Read through a ref so opening resets the cursor once, not again every
  // time the models query settles.
  const flatRef = useRef(flat)
  flatRef.current = flat

  useEffect(() => {
    if (!open) return
    setQuery('')
    const current = flatRef.current.findIndex((model) => model.model_id === value)
    setActive(current === -1 ? 0 : current)
    if (searchable) searchRef.current?.focus()
  }, [open, searchable, value])

  const cursor = Math.min(active, Math.max(flat.length - 1, 0))

  useEffect(() => {
    if (!open || flat.length === 0) return
    document
      .getElementById(`model-option-${flat[cursor]?.model_id ?? ''}`)
      ?.scrollIntoView?.({ block: 'nearest' })
  }, [open, cursor, flat])

  const choose = (modelId: string) => {
    onChange(modelId)
    setOpen(false)
  }

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => {
        const next = event.key === 'ArrowDown' ? index + 1 : index - 1
        return Math.min(Math.max(next, 0), Math.max(flat.length - 1, 0))
      })
      return
    }
    if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault()
      setActive(event.key === 'Home' ? 0 : Math.max(flat.length - 1, 0))
      return
    }
    if (event.key === 'Enter' && flat[cursor]) {
      event.preventDefault()
      choose(flat[cursor].model_id)
      return
    }
    if (event.key === 'Tab') setOpen(false)
  }

  return (
    <PopoverRoot open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label="Model"
          aria-expanded={open}
          disabled={disabled}
          className="inline-flex h-8 min-w-0 max-w-[13rem] items-center gap-1.5 overflow-hidden rounded-lg px-2.5 text-sm text-fg-muted outline-none transition-[background-color,color] duration-150 ease-out hover:bg-raised hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-40"
        >
          <span className="truncate">{selected ? shortModelName(selected.model_id) : 'Model'}</span>
          <ChevronDown
            size={13}
            strokeWidth={1.75}
            className={`shrink-0 transition-transform duration-150 ${open ? 'rotate-180' : ''}`}
            aria-hidden="true"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        aria-label="Model"
        align="end"
        side="top"
        className="w-[19rem] p-0"
        onKeyDown={onKeyDown}
      >
        {searchable && (
          <div className="border-b border-border p-1.5">
            <label className="relative block">
              <Search
                size={13}
                strokeWidth={1.75}
                className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-fg-muted"
                aria-hidden="true"
              />
              <input
                ref={searchRef}
                value={query}
                onChange={(event) => {
                  setQuery(event.currentTarget.value)
                  setActive(0)
                }}
                placeholder="Search models"
                aria-label="Search models"
                aria-controls="model-listbox"
                className="h-8 w-full rounded-lg border border-border bg-surface pl-7 pr-2 text-xs text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
              />
            </label>
          </div>
        )}
        <div
          id="model-listbox"
          role="listbox"
          aria-label="Models"
          aria-activedescendant={flat[cursor] ? `model-option-${flat[cursor].model_id}` : undefined}
          className="max-h-72 overflow-y-auto p-1"
        >
          {flat.length === 0 && (
            <p className="px-2.5 py-3 text-xs text-fg-muted">No models match.</p>
          )}
          {groups.map(([provider, entries]) => (
            <div key={provider} role="group" aria-label={provider}>
              <p className="px-2.5 pb-1 pt-2 text-2xs uppercase tracking-[0.12em] text-fg-subtle">
                {provider}
              </p>
              {entries.map((model) => {
                const index = flat.indexOf(model)
                const current = model.model_id === value
                return (
                  <div
                    key={model.model_id}
                    id={`model-option-${model.model_id}`}
                    role="option"
                    aria-selected={current}
                    onPointerMove={() => setActive(index)}
                    onClick={() => choose(model.model_id)}
                    className={`flex cursor-default items-start gap-2 rounded-lg px-2.5 py-1.5 outline-none ${
                      index === cursor ? 'bg-raised' : ''
                    }`}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-fg">
                        {shortModelName(model.model_id)}
                      </span>
                      <span className="block truncate text-2xs text-fg-muted">
                        {metaLabel(model)}
                      </span>
                    </span>
                    {current && (
                      <Check
                        size={14}
                        strokeWidth={1.75}
                        className="mt-0.5 shrink-0 text-fg"
                        aria-hidden="true"
                      />
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </PopoverContent>
    </PopoverRoot>
  )
}

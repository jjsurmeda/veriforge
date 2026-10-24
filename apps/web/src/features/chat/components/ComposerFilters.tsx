import { useMemo } from 'react'
import { SlidersHorizontal } from 'lucide-react'

import type { RunFilters } from '../../../generated/types.gen'
import { PopoverContent, PopoverRoot, PopoverTrigger } from '../../../components/ui/primitives'
import { useChatDocuments, useLibrary } from '../../library/hooks/useDocuments'

// SR-6 filters, narrowing only: the server injects the ownership scope first
// and intersects these with it (TRD 9.2), so a control here can never widen
// what a run may read. `page` is an API-only filter and has no control.
export function activeFilterCount(filters: RunFilters): number {
  return (
    (filters.source_type ? 1 : 0) +
    (filters.document_ids?.length ? 1 : 0) +
    (filters.tags?.length ? 1 : 0) +
    (filters.date_from || filters.date_to ? 1 : 0) +
    (filters.mime ? 1 : 0)
  )
}

/** Drops empty values so an untouched panel sends no `filters` at all. */
export function compactFilters(filters: RunFilters): RunFilters | undefined {
  return activeFilterCount(filters) === 0 ? undefined : filters
}

const MIME_LABELS: Record<string, string> = {
  'application/pdf': 'PDF',
  'text/plain': 'Text',
  'text/markdown': 'Markdown',
  'text/html': 'HTML',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'Word',
}

const fieldClass =
  'h-9 w-full rounded-lg border border-border bg-surface px-2 text-xs text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring'
const labelClass = 'mb-1 block text-2xs font-medium uppercase tracking-[0.1em] text-fg-subtle'

function toggle<T>(list: T[] | null | undefined, item: T): T[] | null {
  const current = list ?? []
  const next = current.includes(item) ? current.filter((entry) => entry !== item) : [...current, item]
  return next.length > 0 ? next : null
}

const dayOf = (iso: string | null | undefined) => (iso ? iso.slice(0, 10) : '')

interface Props {
  chatId: string | null
  value: RunFilters
  onChange: (value: RunFilters) => void
  disabled?: boolean
}

export function ComposerFilters({ chatId, value, onChange, disabled }: Props) {
  const library = useLibrary()
  const own = useChatDocuments(chatId)
  const documents = useMemo(() => {
    const byId = new Map<string, { id: string; name: string; mime: string; tags: string[] }>()
    for (const doc of [...(library.data?.documents ?? []), ...(own.data ?? [])]) {
      byId.set(doc.id, doc)
    }
    return [...byId.values()]
  }, [library.data, own.data])
  const tags = useMemo(() => [...new Set(documents.flatMap((doc) => doc.tags))].sort(), [documents])
  const mimes = useMemo(() => [...new Set(documents.map((doc) => doc.mime))].sort(), [documents])
  const count = activeFilterCount(value)
  const set = (patch: Partial<RunFilters>) => onChange({ ...value, ...patch })

  return (
    <PopoverRoot>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={count > 0 ? `Filters, ${count} active` : 'Filters'}
          disabled={disabled}
          className={`pressable inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-2.5 text-xs transition-[background-color,color,border-color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-40 max-lg:h-11 ${
            count > 0
              ? 'border border-border-strong bg-raised text-fg'
              : 'border border-transparent text-fg-muted hover:bg-raised-hover hover:text-fg'
          }`}
        >
          <SlidersHorizontal size={14} strokeWidth={1.75} aria-hidden="true" />
          Filters
          {count > 0 && <span className="font-mono tabular-nums text-2xs">{count}</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-[min(22rem,calc(100vw-1.5rem))] space-y-3 p-3">
        <p className="text-xs text-fg-muted">Narrow what this question may read. Filters never widen your access.</p>
        <div>
          <label htmlFor="filter-source" className={labelClass}>Source type</label>
          <select id="filter-source" className={fieldClass} value={value.source_type ?? ''} onChange={(event) => set({ source_type: event.currentTarget.value || null })}>
            <option value="">Any</option>
            <option value="document">Documents</option>
            <option value="web">Web</option>
          </select>
        </div>
        <div>
          <label htmlFor="filter-mime" className={labelClass}>File type</label>
          <select id="filter-mime" className={fieldClass} value={value.mime ?? ''} onChange={(event) => set({ mime: event.currentTarget.value || null })}>
            <option value="">Any</option>
            {mimes.map((mime) => <option key={mime} value={mime}>{MIME_LABELS[mime] ?? mime}</option>)}
          </select>
        </div>
        <fieldset>
          <legend className={labelClass}>Documents</legend>
          {documents.length === 0 ? (
            <p className="text-xs text-fg-muted">No documents yet.</p>
          ) : (
            <div className="max-h-32 space-y-0.5 overflow-y-auto">
              {documents.map((doc) => (
                <label key={doc.id} className="flex min-h-8 items-center gap-2 rounded-md px-1 text-xs text-fg hover:bg-raised-hover max-lg:min-h-11">
                  <input type="checkbox" checked={value.document_ids?.includes(doc.id) ?? false} onChange={() => set({ document_ids: toggle(value.document_ids, doc.id) })} />
                  <span className="truncate">{doc.name}</span>
                </label>
              ))}
            </div>
          )}
        </fieldset>
        {tags.length > 0 && (
          <fieldset>
            <legend className={labelClass}>Tags</legend>
            <div className="flex flex-wrap gap-1">
              {tags.map((tag) => {
                const on = value.tags?.includes(tag) ?? false
                return (
                  <button key={tag} type="button" aria-pressed={on} onClick={() => set({ tags: toggle(value.tags, tag) })} className={`pressable min-h-8 rounded-full border px-2.5 text-xs focus-visible:outline-2 focus-visible:outline-focus-ring max-lg:min-h-11 ${on ? 'border-border-strong bg-raised text-fg' : 'border-border text-fg-muted hover:bg-raised-hover'}`}>{tag}</button>
                )
              })}
            </div>
          </fieldset>
        )}
        <div className="grid grid-cols-2 gap-2">
          <div>
            <label htmlFor="filter-from" className={labelClass}>Date from</label>
            <input id="filter-from" type="date" className={fieldClass} value={dayOf(value.date_from)} onChange={(event) => set({ date_from: event.currentTarget.value ? `${event.currentTarget.value}T00:00:00Z` : null })} />
          </div>
          <div>
            <label htmlFor="filter-to" className={labelClass}>Date to</label>
            <input id="filter-to" type="date" className={fieldClass} value={dayOf(value.date_to)} onChange={(event) => set({ date_to: event.currentTarget.value ? `${event.currentTarget.value}T23:59:59Z` : null })} />
          </div>
        </div>
        <button type="button" disabled={count === 0} onClick={() => onChange({})} className="pressable min-h-8 text-xs text-fg-muted underline-offset-2 hover:text-fg hover:underline focus-visible:outline-2 focus-visible:outline-focus-ring disabled:opacity-40 max-lg:min-h-11">
          Clear filters
        </button>
      </PopoverContent>
    </PopoverRoot>
  )
}

import type { DocumentOut, PageFlag } from '../../../generated/types.gen'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function StatusChip({ status }: { status: string }) {
  if (LIVE_STATUSES.has(status)) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded border border-ember/60 px-2 py-0.5 text-xs text-ember">
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-ember" aria-hidden />
        {status}
      </span>
    )
  }
  if (status === 'ready') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded border border-patina/60 px-2 py-0.5 text-xs text-patina">
        <span aria-hidden>✓</span> ready
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded border border-rust/60 px-2 py-0.5 text-xs text-rust">
      <span aria-hidden>✕</span> {status}
    </span>
  )
}

export function flagSummary(pageFlags: PageFlag[] | null): string | null {
  if (!pageFlags || pageFlags.length === 0) return null
  const kinds = new Set(pageFlags.flatMap((flag) => flag.flags))
  const parts: string[] = []
  if (kinds.has('low_text')) parts.push('scanned?')
  if (kinds.has('table_heavy')) parts.push('table-heavy')
  return `${pageFlags.length} page${pageFlags.length === 1 ? '' : 's'}: ${parts.join(', ')}`
}

export function DocumentList({
  documents,
  onView,
  onReindex,
  onDelete,
}: {
  documents: DocumentOut[]
  onView: (documentId: string) => void
  onReindex: (documentId: string) => void
  onDelete: (documentId: string) => void
}) {
  if (documents.length === 0) {
    return <p className="px-1 py-4 text-sm text-paper/40">No documents yet — drop one above.</p>
  }
  return (
    <ul className="space-y-1">
      {documents.map((document) => {
        const flags = flagSummary(document.page_flags)
        return (
          <li
            key={document.id}
            className="flex items-center gap-3 rounded border border-mist bg-graphite px-3 py-2"
          >
            <button
              type="button"
              onClick={() => onView(document.id)}
              className="min-w-0 flex-1 truncate text-left text-sm text-paper hover:underline focus-visible:outline-2 focus-visible:outline-ember"
            >
              {document.name}
            </button>
            <StatusChip status={document.status} />
            {flags && (
              <span className="hidden shrink-0 items-center gap-1 text-xs text-amber-verdict sm:inline-flex">
                <span aria-hidden>⚠</span> {flags}
              </span>
            )}
            {document.tags.length > 0 && (
              <span className="hidden shrink-0 text-xs text-paper/40 md:inline">
                {document.tags.join(', ')}
              </span>
            )}
            <button
              type="button"
              onClick={() => onReindex(document.id)}
              className="shrink-0 rounded border border-mist px-2 py-0.5 text-xs text-paper/70 hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
            >
              Re-index
            </button>
            <button
              type="button"
              onClick={() => onDelete(document.id)}
              className="shrink-0 rounded border border-mist px-2 py-0.5 text-xs text-rust hover:border-rust focus-visible:outline-2 focus-visible:outline-ember"
            >
              Delete
            </button>
          </li>
        )
      })}
    </ul>
  )
}

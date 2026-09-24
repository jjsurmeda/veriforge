import { AlertTriangle, Check, CircleX, Eye, FileText, LoaderCircle, RotateCcw, Trash2 } from 'lucide-react'

import type { DocumentOut, PageFlag } from '../../../generated/types.gen'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function StatusChip({ status }: { status: string }) {
  if (LIVE_STATUSES.has(status)) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-info/30 bg-info-soft px-2 py-1 text-xs font-medium text-info">
        <LoaderCircle size={12} className="animate-spin" aria-hidden="true" />
        {status}
      </span>
    )
  }
  if (status === 'ready') {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-success/30 bg-success-soft px-2 py-1 text-xs font-medium text-success">
        <Check size={12} aria-hidden="true" /> ready
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-danger/30 bg-danger-soft px-2 py-1 text-xs font-medium text-danger">
      <CircleX size={12} aria-hidden="true" /> {status}
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
    return (
      <div className="rounded-xl border border-dashed border-border-strong bg-surface px-4 py-10 text-center shadow-sm">
        <FileText size={24} className="mx-auto text-muted-foreground" aria-hidden="true" />
        <p className="mt-3 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">Documents</p>
        <p className="mt-2 text-sm text-foreground">No documents yet.</p>
        <p className="mt-1 text-xs text-muted-foreground">Drop a document above to start building evidence.</p>
      </div>
    )
  }
  return (
    <ul className="space-y-1">
      {documents.map((document) => {
        const flags = flagSummary(document.page_flags)
        return (
          <li
            key={document.id}
             className="group flex items-center gap-3 rounded-xl border border-border bg-surface px-3 py-2.5 shadow-sm transition-[border-color,box-shadow,transform] duration-180 hover:-translate-y-px hover:border-primary/30 hover:shadow-md motion-reduce:transform-none motion-reduce:transition-none"

          >
            <button
              type="button"
              onClick={() => onView(document.id)}
              className="inline-flex min-w-0 flex-1 items-center gap-2 truncate rounded-md px-1 py-1 text-left text-sm text-foreground hover:bg-primary-soft focus-visible:outline-2 focus-visible:outline-primary"
            >
              <Eye size={14} className="shrink-0 text-muted-foreground group-hover:text-primary" aria-hidden="true" />
              {document.name}
            </button>
            <StatusChip status={document.status} />
            {flags && (
              <span className="hidden shrink-0 items-center gap-1 text-xs text-warning sm:inline-flex">
                <AlertTriangle size={13} aria-hidden="true" /> {flags}
              </span>
            )}
            {document.tags.length > 0 && (
              <span className="hidden shrink-0 text-xs text-muted-foreground md:inline">
                {document.tags.join(', ')}
              </span>
            )}
            <button
              type="button"
              onClick={() => onReindex(document.id)}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-border bg-surface-muted px-2 py-1 text-xs text-muted-foreground transition-[color,background-color,border-color,transform] duration-180 hover:border-secondary/40 hover:bg-secondary-soft hover:text-secondary active:translate-y-px focus-visible:outline-2 focus-visible:outline-secondary motion-reduce:transition-none"
            >
              <RotateCcw size={12} aria-hidden="true" />
              Re-index
            </button>
            <button
              type="button"
              onClick={() => onDelete(document.id)}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-transparent px-2 py-1 text-xs text-muted-foreground transition-[color,background-color,border-color,transform] duration-180 hover:border-danger/30 hover:bg-danger-soft hover:text-danger active:translate-y-px focus-visible:outline-2 focus-visible:outline-danger motion-reduce:transition-none"
            >
              <Trash2 size={12} aria-hidden="true" />
              Delete
            </button>
          </li>
        )
      })}
    </ul>
  )
}

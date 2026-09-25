import { AlertTriangle, Check, CircleX, Eye, FileText, LoaderCircle, RotateCcw, Trash2 } from 'lucide-react'

import type { DocumentOut, PageFlag } from '../../../generated/types.gen'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function StatusChip({ status }: { status: string }) {
  if (LIVE_STATUSES.has(status)) return <span className="inline-flex items-center gap-1.5 rounded-full border border-border/30 bg-raised px-2 py-1 text-xs font-medium text-fg-muted"><LoaderCircle size={12} strokeWidth={1.75} className="animate-spin" aria-hidden="true" />{status}</span>
  if (status === 'ready') return <span className="inline-flex items-center gap-1.5 rounded-full border border-border/30 bg-raised px-2 py-1 text-xs font-medium text-success"><Check size={12} strokeWidth={1.75} aria-hidden="true" />ready</span>
  return <span className="inline-flex items-center gap-1.5 rounded-full border border-border/30 bg-raised px-2 py-1 text-xs font-medium text-danger"><CircleX size={12} strokeWidth={1.75} aria-hidden="true" />{status}</span>
}

export function flagSummary(pageFlags: PageFlag[] | null): string | null {
  if (!pageFlags || pageFlags.length === 0) return null
  const kinds = new Set(pageFlags.flatMap((flag) => flag.flags))
  const parts: string[] = []
  if (kinds.has('low_text')) parts.push('scanned?')
  if (kinds.has('table_heavy')) parts.push('table-heavy')
  return `${pageFlags.length} page${pageFlags.length === 1 ? '' : 's'}: ${parts.join(', ')}`
}

export function DocumentList({ documents, onView, onReindex, onDelete }: { documents: DocumentOut[]; onView: (documentId: string) => void; onReindex: (documentId: string) => void; onDelete: (documentId: string) => void }) {
  if (documents.length === 0) return <div className="rounded-xl border border-dashed border-border-strong bg-surface px-4 py-12 text-center"><FileText size={24} strokeWidth={1.75} className="mx-auto text-fg-muted" aria-hidden="true" /><p className="mt-3 text-sm text-fg">No documents yet.</p><p className="mt-1 text-xs text-fg-muted">Drop a document above to start building evidence.</p></div>
  return <ul className="divide-y divide-border rounded-xl border border-border bg-surface">{documents.map((document) => { const flags = flagSummary(document.page_flags); return <li key={document.id} className="group flex min-h-14 flex-wrap items-center gap-3 px-3 py-2 transition-colors duration-150 hover:bg-raised-hover"><button type="button" onClick={() => onView(document.id)} className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left text-sm text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"><Eye size={14} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />{document.name}</button><StatusChip status={document.status} />{flags && <span className="hidden shrink-0 items-center gap-1 text-xs text-warning sm:inline-flex"><AlertTriangle size={13} strokeWidth={1.75} aria-hidden="true" />{flags}</span>}{document.tags.length > 0 && <span className="hidden shrink-0 text-xs text-fg-muted md:inline">{document.tags.join(', ')}</span>}<button type="button" onClick={() => onReindex(document.id)} className="pressable inline-flex min-h-9 shrink-0 items-center gap-1 rounded-lg border border-border bg-raised px-2 text-xs text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"><RotateCcw size={12} strokeWidth={1.75} aria-hidden="true" />Re-index</button><button type="button" onClick={() => onDelete(document.id)} className="pressable inline-flex min-h-9 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-fg-muted hover:bg-raised hover:text-danger focus-visible:outline-2 focus-visible:outline-danger"><Trash2 size={12} strokeWidth={1.75} aria-hidden="true" />Delete</button></li> })}</ul>
}

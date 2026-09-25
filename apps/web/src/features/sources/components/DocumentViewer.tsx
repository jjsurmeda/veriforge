import { useState } from 'react'
import { AlertTriangle, Check, RotateCcw, Tag, X } from 'lucide-react'

import type { ChunkOut, DocumentOut } from '../../../generated/types.gen'
import { StatusChip } from './DocumentList'

const FLAG_LABELS: Record<string, string> = { low_text: 'Scanned?', table_heavy: 'Table-heavy' }

export function PageFlags({ document, page }: { document: DocumentOut; page: number | null }) {
  if (page === null) return null
  const entry = (document.page_flags ?? []).find((flag) => flag.page === page)
  if (!entry) return null
  return <span className="inline-flex items-center gap-2 text-xs text-warning">{entry.flags.map((flag) => <span key={flag} className="inline-flex items-center gap-1"><AlertTriangle size={12} strokeWidth={1.75} aria-hidden="true" />{FLAG_LABELS[flag] ?? flag}</span>)}</span>
}

export function groupChunks(chunks: ChunkOut[]): [string, ChunkOut[]][] {
  const groups = new Map<string, ChunkOut[]>()
  for (const chunk of chunks) {
    const group = groups.get(chunk.section_id) ?? []
    group.push(chunk)
    groups.set(chunk.section_id, group)
  }
  return [...groups.entries()]
}

function TagEditor({ tags, onSave }: { tags: string[]; onSave: (tags: string[]) => Promise<unknown> }) {
  const [draft, setDraft] = useState<string[]>(tags)
  const [input, setInput] = useState('')
  const [saving, setSaving] = useState(false)
  const dirty = JSON.stringify(draft) !== JSON.stringify(tags)
  const addTag = () => {
    const tag = input.trim()
    if (tag && !draft.includes(tag)) setDraft((current) => [...current, tag])
    setInput('')
  }
  const save = async () => {
    setSaving(true)
    try { await onSave(draft) } finally { setSaving(false) }
  }
  return <div className="flex flex-wrap items-center gap-2"><span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"><Tag size={13} strokeWidth={1.75} aria-hidden="true" />Tags:</span>{draft.map((tag) => <span key={tag} className="inline-flex items-center gap-1 rounded-full border border-border bg-surface-raised px-2 py-1 text-xs text-foreground">{tag}<button type="button" aria-label={`Remove tag ${tag}`} onClick={() => setDraft((current) => current.filter((entry) => entry !== tag))} className="icon-button size-4 rounded-full text-muted-foreground hover:text-danger"><X size={12} strokeWidth={1.75} aria-hidden="true" /></button></span>)}<input value={input} onChange={(event) => setInput(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === 'Enter') addTag() }} placeholder="add tag" aria-label="Add tag" className="h-8 w-28 rounded-lg border border-border bg-surface px-2.5 text-xs text-foreground placeholder:text-muted-foreground focus-visible:outline-2 focus-visible:outline-accent" />{dirty && <button type="button" disabled={saving} onClick={() => void save()} className="pressable inline-flex min-h-8 items-center gap-1 rounded-lg border border-success/40 bg-success-soft px-2.5 text-xs font-medium text-success disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-success"><Check size={12} strokeWidth={1.75} aria-hidden="true" />{saving ? 'Saving…' : 'Save tags'}</button>}</div>
}

export function DocumentViewer({ document, chunks, onClose, onSaveTags, onReindex }: { document: DocumentOut; chunks: ChunkOut[]; onClose: () => void; onSaveTags: (tags: string[]) => Promise<unknown>; onReindex: () => void }) {
  return <div className="flex h-full flex-col border-l border-border bg-surface-muted"><div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3"><div className="min-w-0"><h2 className="truncate text-sm font-semibold text-foreground">{document.name}</h2><p className="truncate font-mono text-[0.65rem] text-muted-foreground">{document.mime} · sha256 {document.sha256.slice(0, 12)}…</p></div><div className="flex shrink-0 items-center gap-2"><StatusChip status={document.status} /><button type="button" onClick={onClose} aria-label="Close viewer" className="pressable inline-flex min-h-9 items-center gap-1 rounded-lg border border-border bg-surface px-2.5 text-xs text-muted-foreground hover:bg-surface-hover hover:text-foreground focus-visible:outline-2 focus-visible:outline-accent"><X size={13} strokeWidth={1.75} aria-hidden="true" />Close</button></div></div><div className="flex-1 space-y-4 overflow-y-auto p-4">{document.status === 'failed' && <div className="rounded-lg border border-danger/30 bg-danger-soft px-3 py-2"><p className="text-sm text-danger">{document.error ?? 'Ingestion failed'}</p><button type="button" onClick={onReindex} className="pressable mt-2 inline-flex min-h-9 items-center gap-1 rounded-lg border border-danger/40 px-2.5 text-xs font-medium text-danger hover:bg-danger-soft focus-visible:outline-2 focus-visible:outline-danger"><RotateCcw size={13} strokeWidth={1.75} aria-hidden="true" />Re-index document</button></div>}<TagEditor tags={document.tags} onSave={onSaveTags} />{document.status !== 'ready' && document.status !== 'failed' && <p className="text-sm text-info">Ingestion in progress — chunks appear when ready.</p>}{document.status === 'ready' && chunks.length === 0 && <p className="text-sm text-muted-foreground">No text could be extracted from this document.</p>}{groupChunks(chunks).map(([sectionId, sectionChunks]) => <section key={sectionId}><h3 className="mb-1 text-xs text-muted-foreground">{sectionChunks[0]?.heading_path || 'Untitled section'}</h3><div className="space-y-2">{sectionChunks.map((chunk) => <article key={chunk.id} className="rounded-lg border border-border bg-surface px-3 py-2"><header className="mb-1 flex items-center gap-3 text-xs text-muted-foreground"><span>chunk {chunk.ord + 1}</span>{chunk.page !== null && <span>page {chunk.page}</span>}<PageFlags document={document} page={chunk.page} /></header><p className="whitespace-pre-wrap text-sm leading-6 text-foreground">{chunk.text}</p></article>)}</div></section>)}</div></div>
}

import { useState } from 'react'

import type { ChunkOut, DocumentOut } from '../../../generated/types.gen'
import { StatusChip } from './DocumentList'

const FLAG_LABELS: Record<string, string> = {
  low_text: 'Scanned?',
  table_heavy: 'Table-heavy',
}

export function PageFlags({ document, page }: { document: DocumentOut; page: number | null }) {
  if (page === null) return null
  const entry = (document.page_flags ?? []).find((flag) => flag.page === page)
  if (!entry) return null
  return (
    <span className="inline-flex items-center gap-2 text-xs text-amber-verdict">
      {entry.flags.map((flag) => (
        <span key={flag} className="inline-flex items-center gap-1">
          <span aria-hidden>⚠</span>
          {FLAG_LABELS[flag] ?? flag}
        </span>
      ))}
    </span>
  )
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

function TagEditor({
  tags,
  onSave,
}: {
  tags: string[]
  onSave: (tags: string[]) => Promise<unknown>
}) {
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
    try {
      await onSave(draft)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-xs text-paper/40">Tags:</span>
      {draft.map((tag) => (
        <span
          key={tag}
          className="inline-flex items-center gap-1 rounded border border-mist px-2 py-0.5 text-xs text-paper/80"
        >
          {tag}
          <button
            type="button"
            aria-label={`Remove tag ${tag}`}
            onClick={() => setDraft((current) => current.filter((entry) => entry !== tag))}
            className="text-paper/40 hover:text-rust focus-visible:outline-2 focus-visible:outline-ember"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={(event) => setInput(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') addTag()
        }}
        placeholder="add tag"
        aria-label="Add tag"
        className="w-24 rounded border border-mist bg-ink px-2 py-0.5 text-xs text-paper placeholder:text-paper/30 focus-visible:outline-2 focus-visible:outline-ember"
      />
      {dirty && (
        <button
          type="button"
          disabled={saving}
          onClick={() => void save()}
          className="rounded border border-patina/60 px-2 py-0.5 text-xs text-patina focus-visible:outline-2 focus-visible:outline-ember disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save tags'}
        </button>
      )}
    </div>
  )
}

export function DocumentViewer({
  document,
  chunks,
  onClose,
  onSaveTags,
  onReindex,
}: {
  document: DocumentOut
  chunks: ChunkOut[]
  onClose: () => void
  onSaveTags: (tags: string[]) => Promise<unknown>
  onReindex: () => void
}) {
  return (
    <div className="flex h-full flex-col border-l border-mist bg-graphite">
      <div className="flex items-center justify-between gap-3 border-b border-mist px-4 py-3">
        <div className="min-w-0">
          <h2 className="truncate font-display text-base text-paper">{document.name}</h2>
          <p className="truncate font-mono text-xs text-paper/40">
            {document.mime} · sha256 {document.sha256.slice(0, 12)}…
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusChip status={document.status} />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close viewer"
            className="rounded border border-mist px-2 py-1 text-xs text-paper/70 hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
          >
            Close
          </button>
        </div>
      </div>

      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        {document.status === 'failed' && (
          <div className="rounded border border-rust bg-rust/10 px-3 py-2">
            <p className="text-sm text-rust">{document.error ?? 'Ingestion failed'}</p>
            <button
              type="button"
              onClick={onReindex}
              className="mt-2 rounded border border-rust px-2.5 py-1 text-xs text-rust hover:bg-rust/10 focus-visible:outline-2 focus-visible:outline-ember"
            >
              Re-index document
            </button>
          </div>
        )}

        <TagEditor tags={document.tags} onSave={onSaveTags} />

        {document.status !== 'ready' && document.status !== 'failed' && (
          <p className="text-sm text-ember">Ingestion in progress — chunks appear when ready.</p>
        )}
        {document.status === 'ready' && chunks.length === 0 && (
          <p className="text-sm text-paper/40">No text could be extracted from this document.</p>
        )}

        {groupChunks(chunks).map(([sectionId, sectionChunks]) => (
          <section key={sectionId}>
            <h3 className="mb-1 font-mono text-xs text-paper/50">
              {sectionChunks[0]?.heading_path || 'Untitled section'}
            </h3>
            <div className="space-y-2">
              {sectionChunks.map((chunk) => (
                <article
                  key={chunk.id}
                  className="rounded border border-mist bg-ink px-3 py-2"
                >
                  <header className="mb-1 flex items-center gap-3 text-xs text-paper/40">
                    <span>chunk {chunk.ord + 1}</span>
                    {chunk.page !== null && <span>page {chunk.page}</span>}
                    <PageFlags document={document} page={chunk.page} />
                  </header>
                  <p className="whitespace-pre-wrap text-sm text-paper/85">{chunk.text}</p>
                </article>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}

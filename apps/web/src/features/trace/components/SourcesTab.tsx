import { useState } from 'react'
import { ChevronDown, FileText, Globe2 } from 'lucide-react'

import type { MessageOut, RetrievedChunk } from '../../../generated/types.gen'

interface Props {
  chunks: RetrievedChunk[]
  message?: MessageOut | null
  query?: string | null
  onOpenDocument?: (documentId: string) => void
}

function SourceName({ chunk }: { chunk: RetrievedChunk }) {
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {chunk.source_type === 'web' ? <Globe2 size={13} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" /> : <FileText size={13} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />}
      <span className="truncate">{chunk.document_name ?? (chunk.source_type === 'web' ? 'Web source' : 'Source')}</span>
    </span>
  )
}

function chunkForCitation(citation: NonNullable<MessageOut['citations']>[number], chunks: RetrievedChunk[]): RetrievedChunk {
  return chunks.find((chunk) => citation.chunk_id != null && chunk.chunk_id === citation.chunk_id) ?? chunks[citation.n - 1] ?? {
    chunk_id: citation.chunk_id ?? `citation-${citation.n}`,
    document_id: citation.document_id ?? null,
    document_name: citation.document_name ?? null,
    page: citation.page ?? null,
    excerpt: citation.excerpt ?? null,
    rerank_score: citation.rerank_score ?? null,
    source_type: 'document',
  }
}

export function SourcesTab({ chunks, message, query, onOpenDocument }: Props) {
  const [alsoOpen, setAlsoOpen] = useState(false)
  if (chunks.length === 0 && !message?.citations?.length) {
    return (
      <div className="px-4 py-10 text-center">
        <p className="text-sm text-fg">No sources were retrieved.</p>
        <p className="mx-auto mt-2 max-w-[28ch] text-xs leading-5 text-fg-muted">Evidence will appear here when retrieval finds a matching document or web source.</p>
      </div>
    )
  }

  const cited = message?.citations?.length
    ? message.citations.map((citation) => chunkForCitation(citation, chunks))
    : chunks.slice(0, Math.min(chunks.length, 4))
  const citedIds = new Set(cited.map((chunk) => chunk.chunk_id))
  const alsoRetrieved = chunks.filter((chunk) => !citedIds.has(chunk.chunk_id))

  return (
    <div>
      {query && <p className="border-b border-border px-4 py-3 text-xs text-fg-muted">Results for <span className="text-fg">‘{query.length > 42 ? `${query.slice(0, 42)}…` : query}’</span></p>}
      <section aria-labelledby="cited-sources-heading">
        <h3 id="cited-sources-heading" className="px-4 pb-1 pt-3 text-[11px] font-medium uppercase tracking-[0.1em] text-fg-subtle">Cited ({cited.length})</h3>
        <ol className="divide-y divide-border">
          {cited.map((chunk, index) => {
            const documentId = chunk.document_id ?? null
            const content = (
              <>
                <div className="mb-1 flex items-center justify-between gap-3">
                  <span className="flex min-w-0 items-center gap-2 text-xs font-medium text-fg"><span className="inline-flex h-4 min-w-4 items-center justify-center rounded bg-raised px-1 font-mono text-[10px] tabular-nums text-fg-muted">{index + 1}</span><SourceName chunk={chunk} /></span>
                  {chunk.page != null && <span className="shrink-0 font-mono text-[0.65rem] text-fg-muted">p.{chunk.page}</span>}
                </div>
                <p className="line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-fg-muted">{chunk.excerpt}</p>
              </>
            )
            return (
              <li key={`${chunk.chunk_id}-${index}`} id={`trace-source-${index + 1}`} className="px-4 py-3 transition-colors duration-150 hover:bg-raised-hover">
                {documentId && onOpenDocument ? <button type="button" onClick={() => onOpenDocument(documentId)} className="w-full text-left focus-visible:outline-2 focus-visible:outline-focus-ring">{content}</button> : content}
              </li>
            )
          })}
        </ol>
      </section>
      {alsoRetrieved.length > 0 && (
        <section aria-labelledby="also-retrieved-heading" className="border-t border-border">
          <button type="button" aria-expanded={alsoOpen} onClick={() => setAlsoOpen((value) => !value)} className="flex min-h-10 w-full items-center justify-between px-4 text-left text-xs text-fg-muted hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring">
            <span id="also-retrieved-heading">Also retrieved ({alsoRetrieved.length})</span>
            <ChevronDown size={14} strokeWidth={1.75} className={alsoOpen ? 'rotate-180' : ''} aria-hidden="true" />
          </button>
          {alsoOpen && <ol className="divide-y divide-border border-t border-border">{alsoRetrieved.map((chunk) => <li key={chunk.chunk_id} className="px-4 py-3 text-xs text-fg-muted"><SourceName chunk={chunk} /><p className="mt-1 line-clamp-2">{chunk.excerpt}</p></li>)}</ol>}
        </section>
      )}
    </div>
  )
}

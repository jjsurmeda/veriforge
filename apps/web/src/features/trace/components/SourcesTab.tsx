import type { RetrievedChunk } from '../../../generated/types.gen'

interface Props {
  chunks: RetrievedChunk[]
  query?: string | null
  onOpenDocument?: (documentId: string) => void
}

function Score({ label, value }: { label: string; value: number | null | undefined }) {
  return <span className="font-mono text-[0.62rem] tabular-nums text-muted-foreground">{label} {value !== null && value !== undefined ? value.toFixed(3) : '—'}</span>
}

export function SourcesTab({ chunks, query, onOpenDocument }: Props) {
  if (chunks.length === 0) {
    return (
      <div className="px-4 py-10 text-center">
        <p className="text-sm text-foreground">No sources were retrieved.</p>
        <p className="mx-auto mt-2 max-w-[28ch] text-xs leading-5 text-muted-foreground">Evidence will appear here when retrieval finds a matching document or web source.</p>
      </div>
    )
  }
  return (
    <div>
      {query && <p className="border-b border-border px-4 py-3 text-xs text-muted-foreground">Results for <span className="text-foreground">‘{query.length > 42 ? `${query.slice(0, 42)}…` : query}’</span></p>}
      <ol className="divide-y divide-border">
        {chunks.map((chunk, index) => {
          const documentId = chunk.document_id ?? null
          const content = (
            <>
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="truncate text-xs font-medium text-foreground">[{index + 1}] {chunk.document_name ?? (chunk.source_type === 'web' ? 'Web source' : 'Source')}</span>
                {chunk.page !== null && chunk.page !== undefined && <span className="shrink-0 font-mono text-[0.65rem] text-muted-foreground">p.{chunk.page}</span>}
              </div>
              <p className="mb-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{chunk.excerpt}</p>
              <div className="flex flex-wrap gap-x-3 gap-y-1"><Score label="vec" value={chunk.vector_score} /><Score label="bm25" value={chunk.bm25_score} /><Score label="fused" value={chunk.fused_score} /><Score label="rerank" value={chunk.rerank_score} /></div>
            </>
          )
          return (
            <li key={chunk.chunk_id} id={`trace-source-${index + 1}`} className="px-4 py-3 transition-colors duration-150 hover:bg-surface-hover">
              {documentId && onOpenDocument ? <button type="button" onClick={() => onOpenDocument(documentId)} className="w-full text-left focus-visible:outline-2 focus-visible:outline-accent">{content}</button> : content}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

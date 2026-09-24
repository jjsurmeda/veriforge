import type { RetrievedChunk } from '../../../generated/types.gen'

interface Props {
  chunks: RetrievedChunk[]
}

function Score({ label, value }: { label: string; value: number | null | undefined }) {
  return (
    <span className="font-mono text-[0.65rem] text-muted-foreground">
      {label} {value !== null && value !== undefined ? value.toFixed(3) : '—'}
    </span>
  )
}

export function SourcesTab({ chunks }: Props) {
  if (chunks.length === 0) {
    return (
      <div className="border-y border-border px-4 py-5">
        <p className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground/80">Sources</p>
        <p className="mt-2 text-xs text-foreground">No sources were retrieved.</p>
        <p className="mt-1 text-xs leading-5 text-muted-foreground/80">
          Evidence will appear here when retrieval finds a matching document or web source.
        </p>
      </div>
    )
  }
  return (
    <ol className="divide-y divide-border">
      {chunks.map((chunk, index) => (
        <li key={chunk.chunk_id} className="px-4 py-3">
          <div className="mb-1 flex items-baseline justify-between gap-3">
            <span className="truncate font-mono text-xs text-foreground">
              [{index + 1}] {chunk.document_name ?? (chunk.source_type === 'web' ? 'Web source' : 'Source')}
            </span>
            {chunk.page !== null && (
              <span className="shrink-0 font-mono text-xs text-muted-foreground">p.{chunk.page}</span>
            )}
          </div>
          <p className="mb-2 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-foreground">
            {chunk.excerpt}
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <Score label="vec" value={chunk.vector_score} />
            <Score label="bm25" value={chunk.bm25_score} />
            <Score label="fused" value={chunk.fused_score} />
            <Score label="rerank" value={chunk.rerank_score} />
          </div>
        </li>
      ))}
    </ol>
  )
}

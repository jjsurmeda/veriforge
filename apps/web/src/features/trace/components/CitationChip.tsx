import type { CitationOut, RetrievedChunk } from '../../../generated/types.gen'

export interface ChipSource {
  documentName: string | null
  page: number | null
  excerpt: string | null
  rerankScore: number | null
  sourceType: string
}

export function chipSourceFromCitation(citation: CitationOut): ChipSource {
  return {
    documentName: citation.document_name ?? null,
    page: citation.page ?? null,
    excerpt: citation.excerpt ?? null,
    rerankScore: citation.rerank_score ?? null,
    sourceType: 'document',
  }
}

export function chipSourceFromChunk(chunk: RetrievedChunk): ChipSource {
  return {
    documentName: chunk.document_name ?? null,
    page: chunk.page ?? null,
    excerpt: chunk.excerpt ?? '',
    rerankScore: chunk.rerank_score ?? null,
    sourceType: chunk.source_type ?? 'document',
  }
}

interface Props {
  n: number
  source: ChipSource | undefined
}

export function CitationChip({ n, source }: Props) {
  if (!source) {
    return <sup className="ml-0.5 font-mono text-xs text-paper/40">[{n}]</sup>
  }
  return (
    <span className="group relative inline">
      <sup
        tabIndex={0}
        className="ml-0.5 cursor-help rounded-sm font-mono text-xs text-ember focus-visible:outline-2 focus-visible:outline-ember"
      >
        [{n}]
      </sup>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-2 w-80 -translate-x-1/2 rounded border border-mist bg-graphite p-3 text-left opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <span className="mb-1 flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-xs text-paper">
            {source.documentName ?? (source.sourceType === 'web' ? 'Web source' : 'Source')}
          </span>
          {source.page !== null && (
            <span className="shrink-0 font-mono text-xs text-paper/50">p.{source.page}</span>
          )}
        </span>
        <span className="mb-2 block max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-paper/80">
          {source.excerpt ?? '(source expired)'}
        </span>
        <span className="block font-mono text-[0.65rem] text-paper/50">
          rerank {source.rerankScore !== null ? source.rerankScore.toFixed(3) : '—'}
        </span>
      </span>
    </span>
  )
}

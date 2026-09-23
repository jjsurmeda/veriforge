import type { CitationOut, RetrievedChunk } from '../../../generated/types.gen'

export interface ChipSource {
  documentName: string | null
  page: number | null
  excerpt: string | null
  rerankScore: number | null
  sourceType: string
  verdict: string | null
  pSupported: number | null
}

export function chipSourceFromCitation(citation: CitationOut): ChipSource {
  return {
    documentName: citation.document_name ?? null,
    page: citation.page ?? null,
    excerpt: citation.excerpt ?? null,
    rerankScore: citation.rerank_score ?? null,
    sourceType: 'document',
    verdict: citation.verdict ?? null,
    pSupported: citation.p_supported ?? null,
  }
}

export function chipSourceFromChunk(chunk: RetrievedChunk): ChipSource {
  return {
    documentName: chunk.document_name ?? null,
    page: chunk.page ?? null,
    excerpt: chunk.excerpt ?? '',
    rerankScore: chunk.rerank_score ?? null,
    sourceType: chunk.source_type ?? 'document',
    verdict: null,
    pSupported: null,
  }
}

export type VerdictTone = 'pending' | 'supported' | 'partial' | 'unsupported'

const VERDICT_SEVERITY: Record<string, number> = {
  supported: 0,
  partial: 1,
  unsupported: 2,
  contradicted: 3,
}

export function worstVerdict(
  claims: Array<{ citation_ids?: string[]; verdict?: string | null }>,
  n: number,
): string | null {
  let worst: string | null = null
  let worstSeverity = -1
  for (const claim of claims) {
    const ids = claim.citation_ids ?? []
    if (!ids.includes(String(n))) continue
    const verdict = claim.verdict
    if (!verdict) continue
    const severity = VERDICT_SEVERITY[verdict] ?? 0
    if (severity > worstSeverity) {
      worst = verdict
      worstSeverity = severity
    }
  }
  return worst
}

export function verdictTone(verdict: string | null): VerdictTone {
  if (verdict === 'supported') return 'supported'
  if (verdict === 'partial') return 'partial'
  if (verdict === 'unsupported' || verdict === 'contradicted') return 'unsupported'
  return 'pending'
}

const TONE_TEXT: Record<VerdictTone, string> = {
  pending: 'text-paper/40',
  supported: 'text-patina',
  partial: 'text-amber-verdict',
  unsupported: 'text-rust',
}

const TONE_GLYPH: Record<VerdictTone, string> = {
  pending: '',
  supported: '✓',
  partial: '~',
  unsupported: '×',
}

const TONE_LABEL: Record<VerdictTone, string> = {
  pending: 'unverified',
  supported: 'supported',
  partial: 'partially supported',
  unsupported: 'unsupported',
}

interface Props {
  n: number
  source: ChipSource | undefined
  verdict?: string | null
}

export function CitationChip({ n, source, verdict }: Props) {
  const tone = verdictTone(verdict ?? source?.verdict ?? null)
  const glyph = TONE_GLYPH[tone]
  return (
    <span className="group relative inline">
      <sup
        tabIndex={0}
        aria-label={`Citation ${n}: ${TONE_LABEL[tone]}`}
        className={`ml-0.5 cursor-help rounded-sm font-mono text-xs transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-ember ${TONE_TEXT[tone]} ${
          tone === 'unsupported' ? 'underline decoration-dotted underline-offset-2' : ''
        }`}
      >
        [{n}
        {glyph !== '' && (
          <span aria-hidden="true" className="ml-px">
            {glyph}
          </span>
        )}
        ]
      </sup>
      <span
        role="tooltip"
        className="pointer-events-none invisible absolute bottom-full left-1/2 z-20 mb-2 w-80 -translate-x-1/2 rounded border border-mist bg-graphite p-3 text-left opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
      >
        <span className="mb-1 flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-xs text-paper">
            {source?.documentName ?? (source?.sourceType === 'web' ? 'Web source' : 'Source')}
          </span>
          {source?.page !== null && source?.page !== undefined && (
            <span className="shrink-0 font-mono text-xs text-paper/50">p.{source.page}</span>
          )}
        </span>
        <span className="mb-2 block max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-paper/80">
          {source?.excerpt ?? '(source expired)'}
        </span>
        <span className="block font-mono text-[0.65rem] text-paper/50">
          rerank {source?.rerankScore !== null && source?.rerankScore !== undefined ? source.rerankScore.toFixed(3) : '—'}
          {source?.pSupported !== null && source?.pSupported !== undefined && (
            <span> · support {source.pSupported.toFixed(2)}</span>
          )}
          <span> · {TONE_LABEL[tone]}</span>
        </span>
      </span>
    </span>
  )
}

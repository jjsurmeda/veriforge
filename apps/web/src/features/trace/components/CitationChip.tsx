import { FileText, Globe2 } from 'lucide-react'

import { HoverCardContent, HoverCardRoot, HoverCardTrigger } from '../../../components/ui/primitives'

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
  return { documentName: citation.document_name ?? null, page: citation.page ?? null, excerpt: citation.excerpt ?? null, rerankScore: citation.rerank_score ?? null, sourceType: 'document', verdict: citation.verdict ?? null, pSupported: citation.p_supported ?? null }
}

export function chipSourceFromChunk(chunk: RetrievedChunk): ChipSource {
  return { documentName: chunk.document_name ?? null, page: chunk.page ?? null, excerpt: chunk.excerpt ?? '', rerankScore: chunk.rerank_score ?? null, sourceType: chunk.source_type ?? 'document', verdict: null, pSupported: null }
}

export type VerdictTone = 'pending' | 'supported' | 'partial' | 'unsupported'

const VERDICT_SEVERITY: Record<string, number> = { supported: 0, partial: 1, unsupported: 2, contradicted: 3 }

export function worstVerdict(claims: Array<{ citation_ids?: string[]; verdict?: string | null }>, n: number): string | null {
  let worst: string | null = null
  let worstSeverity = -1
  for (const claim of claims) {
    if (!(claim.citation_ids ?? []).includes(String(n)) || !claim.verdict) continue
    const severity = VERDICT_SEVERITY[claim.verdict] ?? 0
    if (severity > worstSeverity) {
      worst = claim.verdict
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

const TONE_LABEL: Record<VerdictTone, string> = { pending: 'unverified', supported: 'supported', partial: 'partially supported', unsupported: 'unsupported' }
const TONE_DOT: Record<VerdictTone, string> = { pending: 'bg-fg-muted', supported: 'bg-success', partial: 'bg-warning', unsupported: 'bg-danger' }

export function CitationChip({ n, source, verdict, onOpen, onHover, highlighted = false }: { n: number; source?: ChipSource; verdict?: string | null; onOpen?: () => void; onHover?: (hovered: boolean) => void; highlighted?: boolean }) {
  const tone = verdictTone(verdict ?? source?.verdict ?? null)
  const label = source?.documentName ?? (source?.sourceType === 'web' ? 'Web source' : `Source ${n}`)

  return (
    <HoverCardRoot openDelay={200} closeDelay={100}>
      <HoverCardTrigger asChild>
        <sup role="button" tabIndex={0} aria-label={`Citation ${n}: ${TONE_LABEL[tone]}`} onClick={onOpen} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen?.() } }} onMouseEnter={() => onHover?.(true)} onMouseLeave={() => onHover?.(false)} onFocus={() => onHover?.(true)} onBlur={() => onHover?.(false)} data-highlighted={highlighted ? 'true' : undefined} className={`source-pill mx-0.5 align-baseline text-decoration underline decoration-transparent ${highlighted ? 'bg-raised-hover text-fg' : ''}`}>
          {n}
        </sup>
      </HoverCardTrigger>
      <HoverCardContent side="top" align="center" className="w-80" role="tooltip">
        <div className="mb-1 flex items-center gap-2">
          {source?.sourceType === 'web' ? <Globe2 size={14} strokeWidth={1.75} className="text-fg-muted" aria-hidden="true" /> : <FileText size={14} strokeWidth={1.75} className="text-fg-muted" aria-hidden="true" />}
          <span className="truncate text-[13px] font-medium text-fg">{label}</span>
          {source?.page !== null && source?.page !== undefined && <span className="ml-auto shrink-0 font-mono text-[11px] text-fg-muted">p.{source.page}</span>}
        </div>
        <p className="line-clamp-4 whitespace-pre-wrap text-xs leading-5 text-fg-muted">{source?.excerpt ?? '(source expired)'}</p>
        <div className="mt-2 flex items-center justify-between gap-3 border-t border-border pt-2 font-mono text-[10px] text-fg-muted">
          <span className="inline-flex items-center gap-1.5"><span className={`size-1.5 rounded-full ${TONE_DOT[tone]}`} aria-hidden="true" />{TONE_LABEL[tone]}</span>
          <span>rerank {source?.rerankScore != null ? source.rerankScore.toFixed(3) : '—'}</span>
          <span>support {source?.pSupported != null ? source.pSupported.toFixed(2) : '—'}</span>
        </div>
      </HoverCardContent>
    </HoverCardRoot>
  )
}

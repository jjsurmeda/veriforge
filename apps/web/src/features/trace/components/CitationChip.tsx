import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { FileText, Globe2 } from 'lucide-react'

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
const TONE_DOT: Record<VerdictTone, string> = { pending: 'bg-muted-foreground', supported: 'bg-success', partial: 'bg-warning', unsupported: 'bg-danger' }
const TONE_GLYPH: Record<VerdictTone, string> = { pending: '', supported: '✓', partial: '~', unsupported: '×' }

export function CitationChip({ n, source, verdict, onOpen }: { n: number; source?: ChipSource; verdict?: string | null; onOpen?: () => void }) {
  const tone = verdictTone(verdict ?? source?.verdict ?? null)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [visible, setVisible] = useState(false)
  const [placement, setPlacement] = useState<'above' | 'below'>('above')
  const [alignment, setAlignment] = useState<'center' | 'left' | 'right'>('center')
  const tooltipRef = useRef<HTMLSpanElement>(null)
  const label = source?.documentName ?? (source?.sourceType === 'web' ? 'Web source' : `Source ${n}`)
  const shortLabel = label.length > 18 ? `[${n}]` : label

  useEffect(() => {
    if (!hovered && !focused) {
      setVisible(false)
      return
    }
    const timer = window.setTimeout(() => setVisible(true), 320)
    return () => window.clearTimeout(timer)
  }, [focused, hovered])

  useLayoutEffect(() => {
    if (!visible) return
    const updatePosition = () => {
      const tooltip = tooltipRef.current
      if (!tooltip) return
      const rect = tooltip.getBoundingClientRect()
      setPlacement(rect.top < 8 ? 'below' : 'above')
      if (rect.left < 8) setAlignment('left')
      else if (rect.right > window.innerWidth - 8) setAlignment('right')
      else setAlignment('center')
    }
    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [visible])

  const placementClass = placement === 'above' ? 'bottom-full mb-2' : 'top-full mt-2'
  const alignmentClass = alignment === 'left' ? 'left-0' : alignment === 'right' ? 'right-0' : 'left-1/2 -translate-x-1/2'

  return (
    <span className="relative inline-block align-baseline">
      <sup role="button" tabIndex={0} aria-label={`Citation ${n}: ${TONE_LABEL[tone]}`} onClick={onOpen} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen?.() } }} onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} className="source-pill mx-0.5 align-baseline text-decoration underline decoration-transparent">
        {source?.sourceType === 'web' ? <Globe2 size={12} strokeWidth={1.75} aria-hidden="true" /> : <FileText size={12} strokeWidth={1.75} aria-hidden="true" />}
        <span className="max-w-28 truncate">{shortLabel}</span>
        {TONE_GLYPH[tone] && <span aria-hidden="true">{TONE_GLYPH[tone]}</span>}
        <span className={`size-1.5 rounded-full ${TONE_DOT[tone]}`} aria-hidden="true" />
      </sup>
      <span ref={tooltipRef} role="tooltip" aria-hidden={!visible} className={`pointer-events-none absolute z-30 w-80 max-w-[calc(100vw-1rem)] rounded-xl border border-border bg-surface-raised p-3 text-left shadow-lg transition-opacity duration-150 ${visible ? 'visible opacity-100' : 'invisible opacity-0'} ${placementClass} ${alignmentClass}`}>
        <span className="mb-1 flex items-baseline justify-between gap-2"><span className="truncate text-xs font-medium text-foreground">{label}</span>{source?.page !== null && source?.page !== undefined && <span className="shrink-0 font-mono text-[0.65rem] text-muted-foreground">p.{source.page}</span>}</span>
        <span className="mb-2 block max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-muted-foreground">{source?.excerpt ?? '(source expired)'}</span>
        <span className="block font-mono text-[0.62rem] tabular-nums text-muted-foreground">rerank {source?.rerankScore !== null && source?.rerankScore !== undefined ? source.rerankScore.toFixed(3) : '—'}{source?.pSupported !== null && source?.pSupported !== undefined && <span> · support {source.pSupported.toFixed(2)}</span>} · {TONE_LABEL[tone]}</span>
      </span>
    </span>
  )
}

import { useLayoutEffect, useRef, useState } from 'react'

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
  pending: 'text-muted-foreground',
  supported: 'text-success',
  partial: 'text-warning',
  unsupported: 'text-danger',
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

type TooltipPlacement = 'above' | 'below'
type TooltipAlignment = 'center' | 'left' | 'right'

export function CitationChip({ n, source, verdict }: Props) {
  const tone = verdictTone(verdict ?? source?.verdict ?? null)
  const glyph = TONE_GLYPH[tone]
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [placement, setPlacement] = useState<TooltipPlacement>('above')
  const [alignment, setAlignment] = useState<TooltipAlignment>('center')
  const tooltipRef = useRef<HTMLSpanElement>(null)
  const open = hovered || focused

  useLayoutEffect(() => {
    if (!open) return

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
  }, [open])

  const placementClass = placement === 'above' ? 'bottom-full mb-2' : 'top-full mt-2'
  const alignmentClass =
    alignment === 'left'
      ? 'left-0 translate-x-0'
      : alignment === 'right'
        ? 'right-0 translate-x-0'
        : 'left-1/2 -translate-x-1/2'

  return (
    <span className="relative inline-block align-baseline">
      <sup
        tabIndex={0}
        aria-label={`Citation ${n}: ${TONE_LABEL[tone]}`}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className={`ml-0.5 cursor-help rounded-sm font-mono text-xs transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ember ${TONE_TEXT[tone]} ${
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
        ref={tooltipRef}
        role="tooltip"
        aria-hidden={!open}
        className={`pointer-events-none absolute z-30 w-80 max-w-[calc(100vw-1rem)] rounded-lg border border-border bg-surface p-3 text-left shadow-lg transition-opacity duration-150 motion-reduce:transition-none ${open ? 'visible opacity-100' : 'invisible opacity-0'} ${placementClass} ${alignmentClass}`}
      >
        <span className="mb-1 flex items-baseline justify-between gap-2">
          <span className="truncate font-mono text-xs text-foreground">
            {source?.documentName ?? (source?.sourceType === 'web' ? 'Web source' : 'Source')}
          </span>
          {source?.page !== null && source?.page !== undefined && (
            <span className="shrink-0 font-mono text-xs text-muted-foreground">p.{source.page}</span>
          )}
        </span>
        <span className="mb-2 block max-h-32 overflow-y-auto whitespace-pre-wrap text-xs leading-5 text-foreground">
          {source?.excerpt ?? '(source expired)'}
        </span>
        <span className="block font-mono text-[0.65rem] text-muted-foreground">
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

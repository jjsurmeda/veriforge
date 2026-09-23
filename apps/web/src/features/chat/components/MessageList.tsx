import type { ReactNode } from 'react'

import type { MessageOut } from '../../../generated/types.gen'
import {
  CitationChip,
  chipSourceFromCitation,
  chipSourceFromChunk,
  worstVerdict,
  type ChipSource,
} from '../../trace/components/CitationChip'
import { SourcesTab } from '../../trace/components/SourcesTab'
import type { RunLive } from '../store'

interface Props {
  messages: MessageOut[]
  live: RunLive | undefined
  onSuggestion?: (question: string) => void
}

const CITATION_RE = /\[(\d{1,2})\]/g

function renderWithCitations(
  content: string,
  lookup: (n: number) => ChipSource | undefined,
  verdictFor: (n: number) => string | null,
): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  CITATION_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = CITATION_RE.exec(content)) !== null) {
    if (match.index > last) nodes.push(content.slice(last, match.index))
    const n = Number(match[1])
    nodes.push(
      <CitationChip
        key={`${match.index}-${n}`}
        n={n}
        source={lookup(n)}
        verdict={verdictFor(n)}
      />,
    )
    last = match.index + match[0].length
  }
  if (last < content.length) nodes.push(content.slice(last))
  return nodes
}

function StatusLabel({ status }: { status: string | null }) {
  if (status === 'cancelled') {
    return <span className="ml-2 text-xs text-paper/50">Cancelled</span>
  }
  if (status === 'failed') {
    return <span className="ml-2 text-xs text-rust">Failed</span>
  }
  if (status === 'abstained') {
    return <span className="ml-2 text-xs text-amber-verdict">Abstained</span>
  }
  return null
}

function fmt(n: number | null | undefined, digits = 2): string {
  return n !== null && n !== undefined ? n.toFixed(digits) : '—'
}

function AnswerFooter({ metrics }: { metrics: Record<string, unknown> | null | undefined }) {
  if (!metrics) return null
  const latency = metrics.latency_ms as Record<string, number> | undefined
  const totalMs = latency ? Object.values(latency).reduce((a, b) => a + b, 0) : null
  const faithfulness = metrics.faithfulness as number | null | undefined
  const minSupport = metrics.min_support as number | null | undefined
  const tokensIn = metrics.tokens_in as number | undefined
  const tokensOut = metrics.tokens_out as number | undefined
  const credits = metrics.credits as number | undefined
  const contextUsed = metrics.context_used as number | undefined
  const contextWindow = metrics.context_window as number | undefined
  const hasAnything =
    faithfulness !== null ||
    faithfulness !== undefined ||
    totalMs !== null ||
    tokensIn !== undefined
  if (!hasAnything) return null
  return (
    <div className="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-mist/40 pt-2 font-mono text-[0.65rem] text-paper/50">
      {faithfulness !== null && faithfulness !== undefined && (
        <span>
          faithful <span className="text-patina">{fmt(faithfulness)}</span>
        </span>
      )}
      {minSupport !== null && minSupport !== undefined && (
        <span>min support {fmt(minSupport)}</span>
      )}
      {totalMs !== null && <span>{(totalMs / 1000).toFixed(1)}s</span>}
      {tokensIn !== undefined && tokensOut !== undefined && (
        <span>
          tokens {tokensIn}/{tokensOut}
        </span>
      )}
      {credits !== undefined && <span>{credits} credits</span>}
      {contextUsed !== undefined && contextWindow !== undefined && (
        <span>
          context {(contextUsed / 1000).toFixed(1)}k/{(contextWindow / 1000).toFixed(0)}k
        </span>
      )}
    </div>
  )
}

function RevisionBanner({ diff }: { diff: string }) {
  return (
    <details className="mt-3 rounded border border-amber-verdict/60">
      <summary className="cursor-pointer px-4 py-2 text-xs text-amber-verdict">
        Reviewer revised this answer — show what changed
      </summary>
      <pre className="overflow-x-auto whitespace-pre-wrap px-4 py-2 font-mono text-[0.65rem] leading-5 text-paper/70">
        {diff}
      </pre>
    </details>
  )
}

function SuggestionsRow({
  questions,
  onSelect,
}: {
  questions: string[]
  onSelect: (question: string) => void
}) {
  return (
    <div className="mx-auto max-w-[72ch] px-4 pb-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-paper/40">Suggested follow-ups:</span>
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelect(question)}
            className="rounded border border-mist bg-graphite px-2.5 py-1 text-xs text-paper/80 hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  )
}

export function MessageList({ messages, live, onSuggestion }: Props) {
  const lastMessage = messages[messages.length - 1]
  const liveSuggestions =
    live !== undefined && live.suggestions.length > 0 ? live.suggestions : []
  const persistedSuggestions =
    lastMessage !== undefined &&
    lastMessage.role === 'assistant'
      ? ((lastMessage.metrics?.suggestions as string[] | undefined) ?? [])
      : []
  const suggestions =
    liveSuggestions.length > 0
      ? liveSuggestions
      : live === undefined || live.status === 'completed'
        ? persistedSuggestions
        : []
  const showSuggestions = onSuggestion !== undefined && suggestions.length > 0
  return (
    <div className="mx-auto flex max-w-[72ch] flex-col gap-6 py-6">
      {messages.map((message) => {
        const isAssistant = message.role === 'assistant'
        const isLivePlaceholder =
          isAssistant && message.status === null && live !== undefined
        const content =
          isLivePlaceholder && live.text ? live.text : message.content
        const citations = message.citations ?? []
        const lookup = isLivePlaceholder
          ? (n: number) => {
              const chunk = live.chunks[n - 1]
              return chunk ? chipSourceFromChunk(chunk) : undefined
            }
          : (n: number) => {
              const citation = citations.find((c) => c.n === n)
              return citation ? chipSourceFromCitation(citation) : undefined
            }
        const verdictFor = isLivePlaceholder
          ? (n: number) => worstVerdict(live.claims, n)
          : (n: number) => citations.find((c) => c.n === n)?.verdict ?? null
        const footerMetrics = isLivePlaceholder ? live.metrics : message.metrics
        const revisionDiff = isLivePlaceholder
          ? live.revision?.diff
          : (message.metrics?.revised === true
              ? (message.metrics?.revision_diff as string | undefined)
              : undefined)
        return (
          <div key={message.id} className="px-4">
            <div className="mb-1 font-mono text-xs text-paper/40">
              {isAssistant ? 'Veriforge' : 'You'}
              <StatusLabel status={message.status} />
            </div>
            <div className="whitespace-pre-wrap text-[0.9375rem] leading-6 text-paper">
              {renderWithCitations(content, lookup, verdictFor)}
              {isLivePlaceholder && live.hold && (
                <span className="ml-2 inline-block animate-pulse text-xs text-amber-verdict" role="status">
                  Verifying…
                </span>
              )}
              {isLivePlaceholder && live.status === 'streaming' && !live.hold && (
                <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-ember align-text-bottom" />
              )}
            </div>
            {revisionDiff && <RevisionBanner diff={revisionDiff} />}
            {isLivePlaceholder && live.chunks.length > 0 && (
              <details className="mt-3 rounded border border-mist/60">
                <summary className="cursor-pointer px-4 py-2 font-mono text-xs text-paper/60">
                  Sources ({live.chunks.length})
                </summary>
                <SourcesTab chunks={live.chunks} />
              </details>
            )}
            {!isLivePlaceholder && citations.length > 0 && (
              <details className="mt-3 rounded border border-mist/60">
                <summary className="cursor-pointer px-4 py-2 font-mono text-xs text-paper/60">
                  Sources ({citations.length})
                </summary>
                <ol className="divide-y divide-mist/50">
                  {citations.map((citation) => (
                    <li key={citation.n} className="px-4 py-3">
                      <div className="mb-1 flex items-baseline justify-between gap-3">
                        <span className="truncate font-mono text-xs text-paper">
                          [{citation.n}]{' '}
                          {citation.document_name ?? 'Source'}
                        </span>
                        {citation.page != null && (
                          <span className="shrink-0 font-mono text-xs text-paper/50">
                            p.{citation.page}
                          </span>
                        )}
                      </div>
                      <p className="mb-1 whitespace-pre-wrap text-xs leading-5 text-paper/70">
                        {citation.excerpt ?? '(source expired)'}
                      </p>
                      <span className="font-mono text-[0.65rem] text-paper/50">
                        rerank{' '}
                        {citation.rerank_score != null
                          ? citation.rerank_score.toFixed(3)
                          : '—'}
                        {citation.p_supported != null && (
                          <span> · support {citation.p_supported.toFixed(2)}</span>
                        )}
                      </span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
            {isAssistant && <AnswerFooter metrics={footerMetrics} />}
          </div>
        )
      })}
      {messages.length === 0 && (
        <p className="px-4 text-sm text-paper/40">Ask anything to start the conversation.</p>
      )}
      {showSuggestions && (
        <SuggestionsRow questions={suggestions} onSelect={onSuggestion!} />
      )}
    </div>
  )
}

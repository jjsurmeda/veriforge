import { Bot, ChevronDown, CircleAlert, CircleX, FileText, Layers3, Search, UserRound } from 'lucide-react'

import type { ReactNode } from 'react'

import { formatCredits } from '../../../lib/format'
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
  onAbstainAction?: (action: AbstainAction) => void
}

const CITATION_RE = /\[(\d{1,2})\]/g

type AbstainAction = 'web' | 'deep'

function isAbstainAction(value: string): value is AbstainAction {
  return value === 'web' || value === 'deep'
}

function abstentionActions(
  live: RunLive | undefined,
  lastMessage: MessageOut | undefined,
): AbstainAction[] {
  if (live?.abstain) {
    return (live.abstain.offered_actions ?? []).filter(isAbstainAction)
  }
  if (lastMessage?.status !== 'abstained') return []
  const actions: AbstainAction[] = []
  if (lastMessage.content.includes('Searching the web')) actions.push('web')
  if (lastMessage.content.includes('Deep mode')) actions.push('deep')
  return actions
}

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
    return (
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-muted-foreground">
        <span className="inline-block h-px w-3 bg-current" aria-hidden="true" /> Cancelled
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-danger">
        <CircleX size={13} aria-hidden="true" /> Failed
      </span>
    )
  }
  if (status === 'abstained') {
    return (
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-warning">
        <CircleAlert size={13} aria-hidden="true" /> Abstained
      </span>
    )
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
    <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-border/40 pt-2 font-mono text-[0.65rem] text-muted-foreground">
      {faithfulness !== null && faithfulness !== undefined && (
        <span>
          faithful <span className="text-success">{fmt(faithfulness)}</span>
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
      {credits !== undefined && <span>{formatCredits(credits)} credits</span>}
      {contextUsed !== undefined && contextWindow !== undefined && (
        <span>
          context {(contextUsed / 1000).toFixed(1)}k/{(contextWindow / 1000).toFixed(0)}k
        </span>
      )}
    </div>
  )
}

function DiffLine({ line }: { line: string }) {
  const isAddition = line.startsWith('+') && !line.startsWith('+++')
  const isRemoval = line.startsWith('-') && !line.startsWith('---')
  const isHunk = line.startsWith('@@')
  const tone = isAddition
    ? 'bg-success-soft text-success'
    : isRemoval
      ? 'bg-danger-soft text-danger'
      : isHunk
        ? 'text-warning'
        : 'text-muted-foreground'
  return <span className={`block whitespace-pre-wrap px-3 ${tone}`}>{line || ' '}</span>
}

function RevisionBanner({ diff }: { diff: string }) {
  return (
    <details className="group mt-3 overflow-hidden rounded-lg border border-border border-l-2 border-l-warning/80 bg-surface-muted open:bg-surface-muted">
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs text-warning transition-colors duration-180 hover:bg-warning-soft focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-warning motion-reduce:transition-none [&::-webkit-details-marker]:hidden">
        <span>Reviewer revised this answer — show what changed</span>
        <ChevronDown size={14} aria-hidden="true" className="text-warning/70 transition-transform duration-180 group-open:rotate-180 motion-reduce:transition-none" />
      </summary>
      <div className="max-h-48 overflow-auto border-t border-border/50 py-2 font-mono text-[0.65rem] leading-5">
        {diff.split('\n').map((line, index) => (
          <DiffLine key={`${index}-${line}`} line={line} />
        ))}
      </div>
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
    <div className="mx-auto max-w-[72ch] px-4 pb-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[0.65rem] uppercase tracking-[0.1em] text-foreground/45">
          Suggested follow-ups:
        </span>
        {questions.map((question) => (
          <button
            key={question}
            type="button"
            onClick={() => onSelect(question)}
            className="min-h-8 rounded-sm border border-border bg-surface-muted px-2.5 py-1.5 text-left text-xs text-foreground transition-[background-color,border-color,transform] duration-150 hover:border-paper/50 hover:bg-surface-muted active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            {question}
          </button>
        ))}
      </div>
    </div>
  )
}

function AbstentionActions({
  actions,
  onSelect,
}: {
  actions: AbstainAction[]
  onSelect: (action: AbstainAction) => void
}) {
  return (
    <div
      className="mx-auto max-w-[72ch] border-l-2 border-warning/60 px-4 pb-3 pl-5"
      role="group"
      aria-label="Abstention actions"
    >
      <p className="mb-2 text-xs text-foreground/55">Try another path:</p>
      <div className="flex flex-wrap gap-2">
        {actions.includes('web') && (
          <button
            type="button"
            onClick={() => onSelect('web')}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-warning/50 bg-warning-soft px-3 py-1.5 text-xs text-warning transition-[background-color,border-color,transform] duration-180 hover:border-warning hover:bg-warning-soft active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            <Search size={14} aria-hidden="true" />
            Searching the web
          </button>
        )}
        {actions.includes('deep') && (
          <button
            type="button"
            onClick={() => onSelect('deep')}
            className="inline-flex min-h-9 items-center gap-2 rounded-lg border border-warning/50 bg-warning-soft px-3 py-1.5 text-xs text-warning transition-[background-color,border-color,transform] duration-180 hover:border-warning hover:bg-warning-soft active:translate-y-px focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            <Layers3 size={14} aria-hidden="true" />
            Deep mode
          </button>
        )}
      </div>
    </div>
  )
}

export function MessageList({ messages, live, onSuggestion, onAbstainAction }: Props) {
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
  const abstainActions = abstentionActions(live, lastMessage)
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
          <div key={message.id} className={`message-enter flex px-4 ${isAssistant ? 'justify-start' : 'justify-end'}`}>
            <div className={`flex max-w-[88%] items-end gap-2 ${isAssistant ? '' : 'flex-row-reverse'}`}>
              <span
                className={`mb-1 flex size-8 shrink-0 items-center justify-center rounded-xl shadow-sm ${
                  isAssistant ? 'bg-secondary-soft text-secondary' : 'bg-primary-soft text-primary'
                }`}
                aria-hidden="true"
              >
                {isAssistant ? <Bot size={16} /> : <UserRound size={16} />}
              </span>
              <div className="min-w-0">
                <div className={`mb-1 flex items-center gap-2 ${isAssistant ? 'justify-start' : 'justify-end'}`}>
                  <StatusLabel status={message.status} />
                </div>
                <div
                  className={`whitespace-pre-wrap rounded-xl px-4 py-3 text-[0.9375rem] leading-6 shadow-sm transition-[background-color,border-color,box-shadow,transform] duration-200 ${
                    isAssistant
                      ? 'rounded-tl-sm border border-border bg-surface text-foreground'
                      : 'rounded-tr-sm bg-primary text-on-primary'
                  }`}
                >
                  {renderWithCitations(content, lookup, verdictFor)}
                  {isLivePlaceholder && live.hold && (
                    <span className="ml-2 inline-flex items-center gap-1 align-middle text-xs text-warning" role="status">
                      <CircleAlert size={13} aria-hidden="true" />
                      Verifying…
                    </span>
                  )}
                  {isLivePlaceholder && live.status === 'streaming' && !live.hold && (
                    <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse rounded-full bg-accent align-text-bottom" />
                  )}
                </div>
                {revisionDiff && <RevisionBanner diff={revisionDiff} />}
            {isLivePlaceholder && live.chunks.length > 0 && (
              <details className="group mt-3 overflow-hidden rounded-lg border border-border/70 bg-surface-muted open:bg-surface-muted">
                <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 font-mono text-xs text-muted-foreground transition-colors duration-180 hover:bg-surface-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary motion-reduce:transition-none [&::-webkit-details-marker]:hidden">
                  <span className="inline-flex items-center gap-1.5"><FileText size={13} aria-hidden="true" /> Sources ({live.chunks.length})</span>
                  <ChevronDown size={14} aria-hidden="true" className="transition-transform duration-180 group-open:rotate-180 motion-reduce:transition-none" />
                </summary>
                <SourcesTab chunks={live.chunks} />
              </details>
            )}
            {!isLivePlaceholder && citations.length > 0 && (
              <div className="mt-3">
                <p className="mb-1.5 flex items-center gap-1.5 font-mono text-[0.65rem] uppercase tracking-[0.1em] text-foreground/45">
                  <FileText size={12} aria-hidden="true" /> Sources
                </p>
                <div className="flex gap-2 overflow-x-auto pb-1" role="list">
                  {citations.map((citation) => (
                    <details
                      key={citation.n}
                      role="listitem"
                      className="group w-56 shrink-0 overflow-hidden rounded-lg border border-border/70 bg-surface-muted transition-[border-color] duration-150 open:border-border hover:border-border"
                    >
                      <summary className="flex min-h-9 cursor-pointer list-none flex-col gap-0.5 px-3 py-2 focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-primary [&::-webkit-details-marker]:hidden">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate font-mono text-xs text-foreground">
                            [{citation.n}] {citation.document_name ?? 'Source'}
                          </span>
                          {citation.page != null && (
                            <span className="shrink-0 font-mono text-[0.65rem] text-muted-foreground">
                              p.{citation.page}
                            </span>
                          )}
                        </span>
                        <span className="line-clamp-2 text-[0.7rem] leading-4 text-foreground/60">
                          {citation.excerpt ?? '(source expired)'}
                        </span>
                      </summary>
                      <div className="border-t border-border/50 px-3 py-2">
                        <p className="mb-1.5 whitespace-pre-wrap text-xs leading-5 text-foreground/70">
                          {citation.excerpt ?? '(source expired)'}
                        </p>
                        <span className="font-mono text-[0.65rem] text-muted-foreground">
                          rerank{' '}
                          {citation.rerank_score != null
                            ? citation.rerank_score.toFixed(3)
                            : '—'}
                          {citation.p_supported != null && (
                            <span> · support {citation.p_supported.toFixed(2)}</span>
                          )}
                        </span>
                      </div>
                    </details>
                  ))}
                </div>
              </div>
            )}
            {isAssistant && <AnswerFooter metrics={footerMetrics} />}
              </div>
            </div>
          </div>
        )
      })}
      {abstainActions.length > 0 && onAbstainAction && (
        <AbstentionActions actions={abstainActions} onSelect={onAbstainAction} />
      )}
      {messages.length === 0 && (
        <div className="flex min-h-[42vh] items-center px-4">
          <div className="w-full max-w-[52ch] border-l-2 border-border pl-5">
            <p className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-foreground/45">
              Workspace ready
            </p>
            <p className="mt-2 text-sm text-foreground/70">Ask anything to start the conversation.</p>
            <p className="mt-1 text-xs leading-5 text-foreground/45">
              Citations, reviewer verdicts, and source details stay one step away while you work.
            </p>
          </div>
        </div>
      )}
      {showSuggestions && (
        <SuggestionsRow questions={suggestions} onSelect={onSuggestion!} />
      )}
    </div>
  )
}

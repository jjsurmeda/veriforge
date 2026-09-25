import { useState, type ReactNode } from 'react'
import {
  Bot,
  Check,
  ChevronDown,
  CircleAlert,
  CircleX,
  Copy,
  FileText,
  Layers3,
  Link2,
  Search,
  UserRound,
} from 'lucide-react'

import { formatCredits } from '../../../lib/format'
import type { MessageOut } from '../../../generated/types.gen'
import {
  CitationChip,
  chipSourceFromCitation,
  chipSourceFromChunk,
  verdictTone,
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
  onOpenSources?: (sourceNumber?: number, messageId?: string) => void
  onSelectMessage?: (messageId: string) => void
  onShowSteps?: () => void
  optimisticQuestion?: string | null
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
  onOpen?: (sourceNumber: number) => void,
  onHover?: (sourceNumber: number | null) => void,
  highlighted?: number | null,
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
        onOpen={onOpen ? () => onOpen(n) : undefined}
        onHover={onHover ? (value) => onHover(value ? n : null) : undefined}
        highlighted={highlighted === n}
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
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-fg-muted">
        <span className="inline-block h-px w-3 bg-current" aria-hidden="true" /> Cancelled
      </span>
    )
  }
  if (status === 'failed') {
    return (
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-danger">
        <CircleX size={13} strokeWidth={1.75} aria-hidden="true" /> Failed
      </span>
    )
  }
  if (status === 'abstained') {
    return (
      <span className="ml-2 inline-flex items-center gap-1 text-xs text-warning">
        <CircleAlert size={13} strokeWidth={1.75} aria-hidden="true" /> Abstained
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
    <div className="mt-4 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-border pt-2 font-mono text-[0.65rem] tabular-nums text-fg-muted">
      {faithfulness !== null && faithfulness !== undefined && <span>faithful <span className="text-success">{fmt(faithfulness)}</span></span>}
      {minSupport !== null && minSupport !== undefined && <span>min support {fmt(minSupport)}</span>}
      {totalMs !== null && <span>{(totalMs / 1000).toFixed(1)}s</span>}
      {tokensIn !== undefined && tokensOut !== undefined && <span>tokens {tokensIn}/{tokensOut}</span>}
      {credits !== undefined && <span>{formatCredits(credits)} credits</span>}
      {contextUsed !== undefined && contextWindow !== undefined && <span>context {(contextUsed / 1000).toFixed(1)}k/{(contextWindow / 1000).toFixed(0)}k</span>}
    </div>
  )
}

function DiffLine({ line }: { line: string }) {
  const isAddition = line.startsWith('+') && !line.startsWith('+++')
  const isRemoval = line.startsWith('-') && !line.startsWith('---')
  const isHunk = line.startsWith('@@')
  const tone = isAddition
    ? 'bg-raised text-success'
    : isRemoval
      ? 'bg-raised text-danger'
      : isHunk
        ? 'text-warning'
        : 'text-fg-muted'
  return <span className={`block whitespace-pre-wrap px-3 ${tone}`}>{line || ' '}</span>
}

function RevisionBanner({ diff }: { diff: string }) {
  return (
    <details className="group mt-4 overflow-hidden rounded-lg border border-border bg-sidebar open:bg-sidebar">
      <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs text-warning transition-colors duration-150 hover:bg-raised focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-warning [&::-webkit-details-marker]:hidden">
        <span>Reviewer revised this answer — show what changed</span>
        <ChevronDown size={14} strokeWidth={1.75} aria-hidden="true" className="text-warning/70 transition-transform duration-150 group-open:rotate-180" />
      </summary>
      <div className="max-h-48 overflow-auto border-t border-border/50 py-2 font-mono text-[0.65rem] leading-5">
        {diff.split('\n').map((line, index) => <DiffLine key={`${index}-${line}`} line={line} />)}
      </div>
    </details>
  )
}

function SuggestionsRow({ questions, onSelect }: { questions: string[]; onSelect: (question: string) => void }) {
  return (
    <section className="mx-auto w-full max-w-[720px] px-1 pb-4" aria-labelledby="related-follow-ups-heading">
      <div className="rounded-xl border border-border bg-surface p-2">
        <span id="related-follow-ups-heading" className="block px-2 py-1 text-xs font-medium text-fg">Related</span>
        <span className="block px-2 pb-1 text-[0.65rem] text-fg-muted">Suggested follow-ups:</span>
        <div className="divide-y divide-border">
          {questions.map((question) => (
            <button key={question} type="button" onClick={() => onSelect(question)} className="flex min-h-11 w-full items-center gap-2 rounded-none px-3 text-left text-sm text-fg transition-colors duration-150 hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring">
              <Search size={14} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />
              <span className="min-w-0 flex-1">{question}</span>
            </button>
          ))}
        </div>
      </div>
    </section>
  )
}

function AbstentionActions({ actions, onSelect }: { actions: AbstainAction[]; onSelect: (action: AbstainAction) => void }) {
  return (
    <div className="mx-auto w-full max-w-[720px] border-l-2 border-border/60 px-1 pb-4 pl-4" role="group" aria-label="Abstention actions">
      <p className="mb-2 text-xs text-fg-muted">Try another path:</p>
      <div className="flex flex-wrap gap-2">
        {actions.includes('web') && (
          <button type="button" onClick={() => onSelect('web')} className="pressable inline-flex min-h-9 items-center gap-2 rounded-lg border border-border/40 px-3 py-1.5 text-xs text-warning hover:bg-raised focus-visible:outline-2 focus-visible:outline-focus-ring">
            <Search size={14} strokeWidth={1.75} aria-hidden="true" /> Searching the web
          </button>
        )}
        {actions.includes('deep') && (
          <button type="button" onClick={() => onSelect('deep')} className="pressable inline-flex min-h-9 items-center gap-2 rounded-lg border border-border/40 px-3 py-1.5 text-xs text-warning hover:bg-raised focus-visible:outline-2 focus-visible:outline-focus-ring">
            <Layers3 size={14} strokeWidth={1.75} aria-hidden="true" /> Deep mode
          </button>
        )}
      </div>
    </div>
  )
}

function MessageActions({ message, content, onShowSteps }: { message: MessageOut; content: string; onShowSteps?: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    if (!navigator.clipboard) return
    await navigator.clipboard.writeText(content)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1600)
  }
  const link = async () => {
    if (!navigator.clipboard) return
    const url = `${window.location.origin}${window.location.pathname}#message-${message.id}`
    await navigator.clipboard.writeText(url)
  }
  return (
    <div className="mt-3 flex items-center gap-0.5" aria-label="Answer actions">
      <button type="button" aria-label={copied ? 'Copied' : 'Copy answer'} title={copied ? 'Copied' : 'Copy answer'} onClick={() => void copy()} className="icon-button size-8">
        {copied ? <Check size={15} strokeWidth={1.75} className="text-success" aria-hidden="true" /> : <Copy size={15} strokeWidth={1.75} aria-hidden="true" />}
      </button>
      <button type="button" aria-label="Link to message" title="Link to message" onClick={() => void link()} className="icon-button size-8">
        <Link2 size={15} strokeWidth={1.75} aria-hidden="true" />
      </button>
      {onShowSteps && <button type="button" onClick={onShowSteps} className="ml-2 text-xs text-fg-muted underline decoration-transparent hover:text-fg hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">Show steps</button>}
    </div>
  )
}

function SourceCardRow({ message, onOpenSources, hoveredCitation, onHoverCitation }: { message: MessageOut; onOpenSources?: (sourceNumber?: number) => void; hoveredCitation: number | null; onHoverCitation: (citation: number | null) => void }) {
  const citations = message.citations ?? []
  if (citations.length === 0) return null
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[0.68rem] font-medium uppercase tracking-[0.1em] text-fg-muted"><FileText size={12} strokeWidth={1.75} aria-hidden="true" /> Sources</p>
        <button type="button" aria-label={`Open ${citations.length} sources`} onClick={() => onOpenSources?.()} className="source-pill">
          <Layers3 size={13} strokeWidth={1.75} aria-hidden="true" /> {citations.length} sources
        </button>
      </div>
      <div className="flex gap-2 overflow-x-auto pb-1" role="list">
        {citations.map((citation) => {
          const tone = verdictTone(citation.verdict ?? null)
          return (
             <details key={citation.n} role="listitem" data-highlighted={hoveredCitation === citation.n ? 'true' : undefined} onMouseEnter={() => onHoverCitation(citation.n)} onMouseLeave={() => onHoverCitation(null)} className={`group w-56 shrink-0 overflow-hidden rounded-lg border bg-surface transition-[border-color,background-color] duration-150 open:bg-raised hover:border-border-strong ${hoveredCitation === citation.n ? 'border-border-strong bg-raised-hover' : 'border-border'}`}>

              <summary onClick={() => onOpenSources?.(citation.n)} className="flex min-h-16 cursor-pointer list-none flex-col gap-1 px-3 py-2 focus-visible:outline-2 focus-visible:outline-focus-ring [&::-webkit-details-marker]:hidden">
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-medium text-fg">[{citation.n}] {citation.document_name ?? 'Source'}</span>
                  <span className={`size-1.5 shrink-0 rounded-full ${tone === 'supported' ? 'bg-success' : tone === 'partial' ? 'bg-warning' : tone === 'unsupported' ? 'bg-danger' : 'bg-fg-muted'}`} aria-label={tone} />
                </span>
                <span className="line-clamp-2 text-[0.7rem] leading-4 text-fg-muted">{citation.excerpt ?? '(source expired)'}</span>
                {citation.page != null && <span className="font-mono text-[0.62rem] text-fg-muted">p.{citation.page}</span>}
              </summary>
              <div className="border-t border-border px-3 py-2">
                <p className="mb-1.5 line-clamp-3 whitespace-pre-wrap text-xs leading-5 text-fg-muted">{citation.excerpt ?? '(source expired)'}</p>
                <span className="font-mono text-[0.62rem] tabular-nums text-fg-muted">rerank {citation.rerank_score != null ? citation.rerank_score.toFixed(3) : '—'}{citation.p_supported != null && <span> · support {citation.p_supported.toFixed(2)}</span>}</span>
              </div>
            </details>
          )
        })}
      </div>
    </div>
  )
}

export function MessageList({ messages, live, onSuggestion, onAbstainAction, onOpenSources, onSelectMessage, onShowSteps, optimisticQuestion }: Props) {
  const [hoveredCitation, setHoveredCitation] = useState<number | null>(null)
  const optimisticUserId = 'optimistic-user'
  const optimisticAssistantId = 'optimistic-assistant'
  const displayedMessages = optimisticQuestion && !messages.some((message) => message.role === 'user' && message.content === optimisticQuestion)
    ? [
        ...messages,
        { id: optimisticUserId, chat_id: '', role: 'user', content: optimisticQuestion, status: 'complete', created_at: new Date().toISOString() },
        { id: optimisticAssistantId, chat_id: '', role: 'assistant', content: '', status: null, created_at: new Date().toISOString() },
      ]
    : messages
  const lastAssistantMessage = [...displayedMessages].reverse().find((message) => message.role === 'assistant')
  const liveSuggestions = live !== undefined && live.suggestions.length > 0 ? live.suggestions : []
  const persistedSuggestions = lastAssistantMessage?.role === 'assistant' ? ((lastAssistantMessage.metrics?.suggestions as string[] | undefined) ?? []) : []
  const suggestions = liveSuggestions.length > 0 ? liveSuggestions : live === undefined || live.status === 'completed' ? persistedSuggestions : []
  const showSuggestions = onSuggestion !== undefined && suggestions.length > 0
  const abstainActions = abstentionActions(live, lastAssistantMessage)

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-8 px-4 py-8 sm:px-6">
      {displayedMessages.map((message) => {
        const isAssistant = message.role === 'assistant'
        const isLivePlaceholder = isAssistant && message.status === null && (live !== undefined || message.id === optimisticAssistantId)
        const content = isLivePlaceholder ? (live?.text ?? '') : message.content
        const citations = message.citations ?? []
        const lookup = isLivePlaceholder
          ? (n: number) => {
              const chunk = live?.chunks[n - 1]
              return chunk ? chipSourceFromChunk(chunk) : undefined
            }
          : (n: number) => {
              const citation = citations.find((c) => c.n === n)
              return citation ? chipSourceFromCitation(citation) : undefined
            }
        const verdictFor = isLivePlaceholder ? (n: number) => worstVerdict(live?.claims ?? [], n) : (n: number) => citations.find((c) => c.n === n)?.verdict ?? null
        const footerMetrics = isLivePlaceholder ? live?.metrics : message.metrics
        const revisionDiff = isLivePlaceholder ? live?.revision?.diff : message.metrics?.revised === true ? (message.metrics?.revision_diff as string | undefined) : undefined
        return (
          <article key={message.id} id={`message-${message.id}`} onClick={() => isAssistant && onSelectMessage?.(message.id)} className={`message-enter flex w-full ${isAssistant ? 'cursor-pointer justify-start' : 'justify-end'}`}>
            {isAssistant ? (
              <div className="w-full min-w-0">
                <div className="mb-3 flex items-center gap-2">
                  <span className="flex size-5 items-center justify-center rounded-md border border-border bg-surface text-fg" aria-hidden="true"><Bot size={14} strokeWidth={1.75} /></span>
                  <span className="text-[0.8rem] font-medium text-fg-muted">Answer</span>
                  <StatusLabel status={message.status} />
                </div>
                {isLivePlaceholder && !live?.hold && (
                  <div className="mb-3 rounded-lg border border-border bg-sidebar p-3" role="status" aria-label="Working">
                    <div className="mb-2 flex items-center justify-between gap-3"><span className="thinking-shimmer text-sm font-medium">Working</span><span className="inline-flex items-center gap-1 text-fg-muted" aria-hidden="true"><span className="thinking-dot size-1 rounded-full bg-current" /><span className="thinking-dot size-1 rounded-full bg-current" /><span className="thinking-dot size-1 rounded-full bg-current" /></span></div>
                    <ol className="space-y-1.5">{[...(live?.steps ?? [])].reverse().slice(0, 4).map((step) => <li key={`${step.seq ?? 0}-${step.node}`} className="flex items-center gap-2 text-xs text-fg-muted"><span className="text-fg-subtle">{step.type === 'step.completed' ? '✓' : '•'}</span><span>{step.label}</span></li>)}{live?.plan && <li className="text-xs text-fg-muted">Planning{live.plan.sub_questions.length > 0 ? `: ${live.plan.sub_questions.map((question) => question.question).join(' · ')}` : ''}</li>}{live?.thinking && <li className="line-clamp-2 text-xs text-fg-muted">{live.thinking}</li>}</ol>
                  </div>
                )}
                <div className="answer-prose text-fg">
                  {renderWithCitations(content, lookup, verdictFor, onOpenSources, (value) => setHoveredCitation(value), hoveredCitation)}
                  {isLivePlaceholder && live?.hold && <span className="ml-2 inline-flex items-center gap-1 align-middle font-sans text-xs text-warning" role="status"><CircleAlert size={13} strokeWidth={1.75} aria-hidden="true" /> Verifying…</span>}
                  {isLivePlaceholder && live?.status === 'streaming' && !live.hold && <span className="ml-0.5 inline-block h-4 w-0.5 animate-pulse rounded-sm bg-fg-muted align-text-bottom" aria-hidden="true" />}
                </div>
                {revisionDiff && <RevisionBanner diff={revisionDiff} />}
                {isLivePlaceholder && (live?.chunks.length ?? 0) > 0 && (
                  <details className="group mt-4 overflow-hidden rounded-lg border border-border bg-sidebar open:bg-raised">
                    <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 px-3 py-2 text-xs text-fg-muted transition-colors duration-150 hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring [&::-webkit-details-marker]:hidden">
                      <span className="inline-flex items-center gap-1.5"><FileText size={13} strokeWidth={1.75} aria-hidden="true" /> Sources ({live?.chunks.length ?? 0})</span>
                      <ChevronDown size={14} strokeWidth={1.75} aria-hidden="true" className="transition-transform duration-150 group-open:rotate-180" />
                   </summary>
                     <SourcesTab chunks={live?.chunks ?? []} />

                  </details>
                )}
                 {!isLivePlaceholder && <SourceCardRow message={message} onOpenSources={onOpenSources} hoveredCitation={hoveredCitation} onHoverCitation={setHoveredCitation} />}

                 {isAssistant && <MessageActions message={message} content={content} onShowSteps={onShowSteps} />}

                <AnswerFooter metrics={footerMetrics} />
              </div>
            ) : (
              <div className="flex max-w-[80%] items-start gap-2">
                <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-fg-muted" aria-hidden="true"><UserRound size={14} strokeWidth={1.75} /></span>
                <div className="min-w-0 rounded-3xl rounded-br-lg bg-raised px-4 py-2.5 text-[0.9375rem] leading-6 text-fg">
                  <div className="whitespace-pre-wrap">{renderWithCitations(content, lookup, verdictFor, onOpenSources)}</div>
                  <div className="mt-1 flex justify-end"><StatusLabel status={message.status} /></div>
                </div>
              </div>
            )}
          </article>
        )
      })}
      {abstainActions.length > 0 && onAbstainAction && <AbstentionActions actions={abstainActions} onSelect={onAbstainAction} />}
      {messages.length === 0 && optimisticQuestion && (
        <div className="sr-only" role="status">Question sent. Waiting for the assistant.</div>
      )}
      {displayedMessages.length === 0 && !optimisticQuestion && (
        <div className="flex min-h-[42vh] items-center justify-center px-4 text-center">
          <div className="max-w-[32rem]">
            <p className="text-sm text-fg-muted">Ask anything to start the conversation.</p>
            <p className="mt-2 text-xs leading-5 text-fg-subtle">Citations, reviewer verdicts, and source details stay one step away while you work.</p>
          </div>
        </div>
      )}
      {showSuggestions && <SuggestionsRow questions={suggestions} onSelect={onSuggestion!} />}
    </div>
  )
}

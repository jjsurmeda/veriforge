import type { ReactNode } from 'react'

import type { MessageOut } from '../../../generated/types.gen'
import {
  CitationChip,
  chipSourceFromCitation,
  chipSourceFromChunk,
  type ChipSource,
} from '../../trace/components/CitationChip'
import { SourcesTab } from '../../trace/components/SourcesTab'
import type { RunLive } from '../store'

interface Props {
  messages: MessageOut[]
  live: RunLive | undefined
}

const CITATION_RE = /\[(\d{1,2})\]/g

function renderWithCitations(
  content: string,
  lookup: (n: number) => ChipSource | undefined,
): ReactNode[] {
  const nodes: ReactNode[] = []
  let last = 0
  CITATION_RE.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = CITATION_RE.exec(content)) !== null) {
    if (match.index > last) nodes.push(content.slice(last, match.index))
    const n = Number(match[1])
    nodes.push(<CitationChip key={`${match.index}-${n}`} n={n} source={lookup(n)} />)
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

export function MessageList({ messages, live }: Props) {
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
        return (
          <div key={message.id} className="px-4">
            <div className="mb-1 font-mono text-xs text-paper/40">
              {isAssistant ? 'Veriforge' : 'You'}
              <StatusLabel status={message.status} />
            </div>
            <div className="whitespace-pre-wrap text-[0.9375rem] leading-6 text-paper">
              {renderWithCitations(content, lookup)}
              {isLivePlaceholder && live.status === 'streaming' && (
                <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-ember align-text-bottom" />
              )}
            </div>
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
                      </span>
                    </li>
                  ))}
                </ol>
              </details>
            )}
          </div>
        )
      })}
      {messages.length === 0 && (
        <p className="px-4 text-sm text-paper/40">Ask anything to start the conversation.</p>
      )}
    </div>
  )
}

import type { MessageOut } from '../../../generated/types.gen'
import type { RunLive } from '../store'

interface Props {
  messages: MessageOut[]
  live: RunLive | undefined
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
        return (
          <div key={message.id} className="px-4">
            <div className="mb-1 font-mono text-xs text-paper/40">
              {isAssistant ? 'Veriforge' : 'You'}
              <StatusLabel status={message.status} />
            </div>
            <div className="whitespace-pre-wrap text-[0.9375rem] leading-6 text-paper">
              {content}
              {isLivePlaceholder && live.status === 'streaming' && (
                <span className="ml-0.5 inline-block h-4 w-2 animate-pulse bg-ember align-text-bottom" />
              )}
            </div>
          </div>
        )
      })}
      {messages.length === 0 && (
        <p className="px-4 text-sm text-paper/40">Ask anything to start the conversation.</p>
      )}
    </div>
  )
}

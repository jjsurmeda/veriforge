import { useEffect, useState } from 'react'

import { useChat, useMessages } from '../hooks/useChat'
import { useCancelRun, useCreateRun } from '../hooks/useRuns'
import { useRunStream } from '../hooks/useRunStream'
import { usePatchChat } from '../hooks/useChatList'
import { useChatRunStore } from '../store'
import { ChatComposer } from '../components/ChatComposer'
import { ChatSidebar } from '../components/ChatSidebar'
import { MessageList } from '../components/MessageList'
import type { RunMode } from '../components/ModePicker'
import type { RunSource } from '../components/SourcePicker'
import { TracePanel } from '../../trace/components/TracePanel'
import { useTrace } from '../../trace/hooks/useTrace'

export function ChatView({ chatId }: { chatId: string }) {
  const chat = useChat(chatId)
  const messages = useMessages(chatId)
  const patchChat = usePatchChat()
  const createRun = useCreateRun(chatId)
  const cancelRun = useCancelRun()

  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  useEffect(() => {
    setActiveRunId(chat.data?.active_run_id ?? null)
  }, [chat.data?.active_run_id])

  const { resume } = useRunStream(activeRunId, chatId)
  const live = useChatRunStore((s) => (activeRunId ? s.runs[activeRunId] : undefined))
  const trace = useTrace(activeRunId)
  const streaming =
    live !== undefined && (live.status === 'connecting' || live.status === 'streaming')

  const onSend = async (
    message: string,
    options: { mode: RunMode; source: RunSource },
  ) => {
    // Deep routes to Auto in slice 4 — slice 5 replaces the fallback with
    // the real Plan/Hop/Controller path (TRD §17 row 5). The composer
    // already surfaced the notice; we forward 'auto' here.
    const wireMode = options.mode === 'deep' ? 'auto' : options.mode
    const run = await createRun.mutateAsync({
      message,
      modelId: chat.data?.model_id,
      mode: wireMode,
      source: options.source,
    })
    useChatRunStore.getState().begin(run!.run_id, run!.message_id)
    setActiveRunId(run!.run_id)
  }

  return (
    <div className="flex h-screen bg-ink text-paper">
      <ChatSidebar currentChatId={chatId} />
      <main className="flex min-w-0 flex-1 flex-col">
        {chat.isError ? (
          <p className="p-6 text-sm text-paper/60">Chat not found.</p>
        ) : (
          <>
            <div className="flex-1 overflow-y-auto">
              <MessageList messages={messages.data ?? []} live={live} />
              {live?.status === 'connection_lost' && (
                <div className="mx-auto max-w-[72ch] px-4 pb-4">
                  <button
                    type="button"
                    onClick={resume}
                    className="rounded border border-rust px-3 py-1.5 text-sm text-rust hover:bg-rust/10 focus-visible:outline-2 focus-visible:outline-ember"
                  >
                    Connection lost — resume
                  </button>
                </div>
              )}
            </div>
            <ChatComposer
              streaming={streaming}
              modelId={chat.data?.model_id ?? null}
              onModelChange={(modelId) =>
                void patchChat.mutateAsync({ chatId, patch: { model_id: modelId } })
              }
              onSend={(message, options) => void onSend(message, options)}
              onStop={() => activeRunId && cancelRun.mutate(activeRunId)}
            />
          </>
        )}
      </main>
      {trace && (
        <TracePanel
          steps={trace.steps}
          decisions={trace.decisions}
          thinking={trace.thinking}
          streaming={trace.streaming}
        />
      )}
    </div>
  )
}

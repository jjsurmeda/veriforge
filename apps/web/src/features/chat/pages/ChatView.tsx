import { useEffect, useRef, useState } from 'react'

import { useChat, useMessages } from '../hooks/useChat'
import { useCancelRun, useCreateRun } from '../hooks/useRuns'
import { useRunStream } from '../hooks/useRunStream'
import { useQuota } from '../hooks/useQuota'
import { useCollections } from '../../sources/hooks/useCollections'
import { usePatchChat } from '../hooks/useChatList'
import { useChatRunStore } from '../store'
import { ChatComposer } from '../components/ChatComposer'
import { ChatSidebar } from '../components/ChatSidebar'
import { MessageList } from '../components/MessageList'
import type { RunMode } from '../components/ModePicker'
import type { RunSource } from '../components/SourcePicker'
import { TracePanel } from '../../trace/components/TracePanel'
import { useTrace } from '../../trace/hooks/useTrace'

function runFailureMessage(code: string): string {
  if (code === 'web_search_unconfigured') {
    return "Couldn't search the web because no web search provider is configured. Try your documents instead."
  }
  if (code === 'web_search_failed') {
    return 'The web search provider could not answer that question. Try again.'
  }
  return 'The run could not finish. Try again.'
}

function errorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'data' in error) {
    const data = (error as { data?: unknown }).data
    if (typeof data === 'object' && data !== null && 'message' in data) {
      const message = (data as { message?: unknown }).message
      if (typeof message === 'string') return message
    }
  }
  if (error instanceof Error) return error.message
  return 'The question could not be started. Try again.'
}

export function ChatView({ chatId }: { chatId: string }) {
  const chat = useChat(chatId)
  const messages = useMessages(chatId)
  const patchChat = usePatchChat()
  const createRun = useCreateRun(chatId)
  const cancelRun = useCancelRun()
  const quota = useQuota()
  const collections = useCollections()

  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [traceRunId, setTraceRunId] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [collectionSelection, setCollectionSelection] = useState<{
    chatId: string
    ids: string[]
  } | null>(null)
  const pendingCollectionChange = useRef<{
    chatId: string
    ids: string[]
    promise: Promise<unknown>
  } | null>(null)
  const collectionPatchQueue = useRef<Promise<unknown>>(Promise.resolve())
  useEffect(() => {
    setActiveRunId(chat.data?.active_run_id ?? null)
    if (chat.data?.active_run_id) setTraceRunId(chat.data.active_run_id)
  }, [chat.data?.active_run_id])

  const collectionIds =
    collectionSelection?.chatId === chatId
      ? collectionSelection.ids
      : (chat.data?.collection_ids ?? [])

  const { resume } = useRunStream(activeRunId, chatId)
  const live = useChatRunStore((s) => (activeRunId ? s.runs[activeRunId] : undefined))
  const trace = useTrace(traceRunId)
  const streaming =
    live !== undefined && (live.status === 'connecting' || live.status === 'streaming')

  const onSend = async (
    message: string,
    options: { mode: RunMode; source: RunSource },
  ) => {
    setSendError(null)
    try {
      const pending = pendingCollectionChange.current
      if (pending?.chatId === chatId) await pending.promise
      const run = await createRun.mutateAsync({
        message,
        modelId: chat.data?.model_id,
        mode: options.mode,
        source: options.source,
        collectionIds: pending?.chatId === chatId ? pending.ids : collectionIds,
      })
      if (pending?.chatId === chatId) pendingCollectionChange.current = null
      useChatRunStore.getState().begin(run!.run_id, run!.message_id)
      setActiveRunId(run!.run_id)
      void quota.refetch()
    } catch (error) {
      setSendError(errorMessage(error))
      void quota.refetch()
    }
  }

  const onCollectionChange = (nextCollectionIds: string[]) => {
    setCollectionSelection({ chatId, ids: nextCollectionIds })
    const promise = collectionPatchQueue.current
      .catch(() => undefined)
      .then(() =>
        patchChat.mutateAsync({
          chatId,
          patch: { collection_ids: nextCollectionIds },
        }),
      )
    collectionPatchQueue.current = promise.catch(() => undefined)
    pendingCollectionChange.current = { chatId, ids: nextCollectionIds, promise }
    void promise.catch(() => undefined)
  }

  const onAbstainAction = (action: 'web' | 'deep') => {
    const question = [...(messages.data ?? [])]
      .reverse()
      .find((message) => message.role === 'user')?.content
    if (!question) return
    void onSend(question, {
      mode: action === 'deep' ? 'deep' : 'auto',
      source: action === 'web' ? 'web' : 'auto',
    })
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
              <MessageList
                messages={messages.data ?? []}
                live={live}
                onSuggestion={(question) =>
                  void onSend(question, { mode: 'auto', source: 'auto' })
                }
                onAbstainAction={onAbstainAction}
              />
              {live?.status === 'failed' && live.error && (
                <p role="alert" className="mx-auto max-w-[72ch] px-4 pb-4 text-sm text-amber-verdict">
                  {runFailureMessage(live.error)}
                </p>
              )}
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
              quota={quota.data}
              collections={collections.data ?? []}
              collectionIds={collectionIds}
              error={sendError}
              onModelChange={(modelId) =>
                void patchChat.mutateAsync({ chatId, patch: { model_id: modelId } })
              }
              onCollectionChange={onCollectionChange}
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
          chunks={trace.chunks}
          metrics={trace.metrics}
          hold={trace.hold}
        />
      )}
    </div>
  )
}

import { useEffect, useRef, useState } from 'react'
import { ArrowDown, Check, MoreHorizontal, PanelRight, Pencil, Pin, Trash2 } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'

import { useChat, useMessages } from '../hooks/useChat'
import { useCancelRun, useCreateRun } from '../hooks/useRuns'
import { useRunStream } from '../hooks/useRunStream'
import { useQuota } from '../hooks/useQuota'
import { useCollections } from '../../sources/hooks/useCollections'
import { useDeleteChat, usePatchChat } from '../hooks/useChatList'
import { useChatRunStore } from '../store'
import { ChatComposer } from '../components/ChatComposer'
import { ChatSidebar } from '../components/ChatSidebar'
import { MessageList } from '../components/MessageList'
import type { RunMode } from '../components/ModePicker'
import type { RunSource } from '../components/SourcePicker'
import { TracePanel, type TraceTab } from '../../trace/components/TracePanel'
import { useTrace } from '../../trace/hooks/useTrace'
import { Menu, MenuContent, MenuItemWithIcon, MenuTrigger } from '../../../components/ui/primitives'

function runFailureMessage(code: string): string {
  if (code === 'web_search_unconfigured') return "Couldn't search the web because no web search provider is configured. Try your documents instead."
  if (code === 'web_search_failed') return 'The web search provider could not answer that question. Try again.'
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
  const navigate = useNavigate()
  const chat = useChat(chatId)
  const messages = useMessages(chatId)
  const patchChat = usePatchChat()
  const deleteChat = useDeleteChat()
  const createRun = useCreateRun(chatId)
  const cancelRun = useCancelRun()
  const quota = useQuota()
  const collections = useCollections()
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [traceRunId, setTraceRunId] = useState<string | null>(null)
  const [sendError, setSendError] = useState<string | null>(null)
  const [optimisticQuestion, setOptimisticQuestion] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [rightPanelOpen, setRightPanelOpen] = useState(() => window.innerWidth >= 1024)
  const [rightPanelExpanded, setRightPanelExpanded] = useState(false)
  const [traceTab, setTraceTab] = useState<TraceTab>('trace')
  const [focusSource, setFocusSource] = useState<number | null>(null)
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const [threadEditing, setThreadEditing] = useState(false)
  const [threadTitleDraft, setThreadTitleDraft] = useState('')
  const [showScrollButton, setShowScrollButton] = useState(false)
  const [collectionSelection, setCollectionSelection] = useState<{ chatId: string; ids: string[] } | null>(null)
  const pendingCollectionChange = useRef<{ chatId: string; ids: string[]; promise: Promise<unknown> } | null>(null)
  const collectionPatchQueue = useRef<Promise<unknown>>(Promise.resolve())
  const threadScrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setActiveRunId(chat.data?.active_run_id ?? null)
    if (chat.data?.active_run_id) setTraceRunId(chat.data.active_run_id)
  }, [chat.data?.active_run_id])

  useEffect(() => {
    const media = window.matchMedia('(min-width: 1024px)')
    const onChange = (event: MediaQueryListEvent) => setRightPanelOpen(event.matches)
    media.addEventListener('change', onChange)
    return () => media.removeEventListener('change', onChange)
  }, [])

  const collectionIds = collectionSelection?.chatId === chatId ? collectionSelection.ids : (chat.data?.collection_ids ?? [])
  const { resume } = useRunStream(activeRunId, chatId)
  const live = useChatRunStore((s) => (activeRunId ? s.runs[activeRunId] : undefined))

  useEffect(() => {
    if (live?.status === 'completed' || live?.status === 'failed' || live?.status === 'cancelled') setOptimisticQuestion(null)
  }, [live?.status])
  const trace = useTrace(traceRunId)
  const streaming = live !== undefined && (live.status === 'connecting' || live.status === 'streaming')
  const selectedMessage = selectedMessageId ? messages.data?.find((message) => message.id === selectedMessageId) : [...(messages.data ?? [])].reverse().find((message) => message.role === 'assistant')
  const lastQuestion = [...(messages.data ?? [])].reverse().find((message) => message.role === 'user')?.content ?? null

  const onSend = async (message: string, options: { mode: RunMode; source: RunSource }) => {
    setSendError(null)
    setOptimisticQuestion(message)
    try {
      const pending = pendingCollectionChange.current
      if (pending?.chatId === chatId) await pending.promise
      const run = await createRun.mutateAsync({ message, modelId: chat.data?.model_id, mode: options.mode, source: options.source, collectionIds: pending?.chatId === chatId ? pending.ids : collectionIds })
      if (pending?.chatId === chatId) pendingCollectionChange.current = null
      useChatRunStore.getState().begin(run!.run_id, run!.message_id)
      setActiveRunId(run!.run_id)
      void quota.refetch()
    } catch (error) {
      setOptimisticQuestion(null)
      setSendError(errorMessage(error))
      void quota.refetch()
    }
  }

  const onCollectionChange = (nextCollectionIds: string[]) => {
    setCollectionSelection({ chatId, ids: nextCollectionIds })
    const promise = collectionPatchQueue.current.catch(() => undefined).then(() => patchChat.mutateAsync({ chatId, patch: { collection_ids: nextCollectionIds } }))
    collectionPatchQueue.current = promise.catch(() => undefined)
    pendingCollectionChange.current = { chatId, ids: nextCollectionIds, promise }
    void promise.catch(() => undefined)
  }

  const onAbstainAction = (action: 'web' | 'deep') => {
    if (!lastQuestion) return
    void onSend(lastQuestion, { mode: action === 'deep' ? 'deep' : 'auto', source: action === 'web' ? 'web' : 'auto' })
  }

  const openSources = (sourceNumber?: number, messageId?: string) => {
    setRightPanelOpen(true)
    setTraceTab('sources')
    setFocusSource(sourceNumber ?? null)
    if (messageId) setSelectedMessageId(messageId)
  }

  const saveThreadRename = async () => {
    const title = threadTitleDraft.trim()
    if (!title) return
    await patchChat.mutateAsync({ chatId, patch: { title } })
    setThreadEditing(false)
  }

  const deleteCurrentChat = async () => {
    await deleteChat.mutateAsync(chatId)
    void navigate({ to: '/' })
  }

  const scrollToBottom = () => {
    threadScrollRef.current?.scrollTo({ top: threadScrollRef.current.scrollHeight, behavior: 'smooth' })
  }

  return (
    <div className="flex h-full min-h-0 bg-main text-fg">
      <ChatSidebar currentChatId={chatId} mobileOpen={sidebarOpen} onMobileClose={() => setSidebarOpen(false)} />
      <div className="flex min-w-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="relative z-10 flex h-14 shrink-0 items-center justify-between gap-3 border-b border-border bg-main px-3 sm:px-5">
            <div className="flex min-w-0 items-center gap-2">
              <button type="button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)} className="icon-button size-9 lg:hidden"><PanelRight size={17} strokeWidth={1.75} aria-hidden="true" /></button>
              {threadEditing ? (
                <div className="flex min-w-0 items-center gap-1">
                  <input aria-label="Rename thread" value={threadTitleDraft} onChange={(event) => setThreadTitleDraft(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === 'Enter') void saveThreadRename(); if (event.key === 'Escape') setThreadEditing(false) }} className="h-8 min-w-0 max-w-[16rem] rounded-lg border border-border bg-surface px-2 text-sm text-fg focus-visible:outline-2 focus-visible:outline-focus-ring" />
                  <button type="button" aria-label="Save thread rename" onClick={() => void saveThreadRename()} className="icon-button size-8 text-fg"><Check size={15} strokeWidth={1.75} aria-hidden="true" /></button>
                </div>
              ) : <h1 className="truncate text-sm font-medium text-fg-muted">{chat.data?.title ?? 'Conversation'}</h1>}
            </div>
            <div className="relative flex shrink-0 items-center gap-1">
              {!threadEditing && <Menu><MenuTrigger asChild><button type="button" aria-label="Thread actions" className="icon-button size-8"><MoreHorizontal size={17} strokeWidth={1.75} aria-hidden="true" /></button></MenuTrigger><MenuContent side="bottom" align="end" className="w-40"><MenuItemWithIcon onSelect={() => { setThreadTitleDraft(chat.data?.title ?? ''); setThreadEditing(true) }}><Pencil size={13} strokeWidth={1.75} aria-hidden="true" />Rename</MenuItemWithIcon><MenuItemWithIcon onSelect={() => void patchChat.mutateAsync({ chatId, patch: { pinned: !chat.data?.pinned } })}><Pin size={13} strokeWidth={1.75} aria-hidden="true" />{chat.data?.pinned ? 'Unpin' : 'Pin'}</MenuItemWithIcon><MenuItemWithIcon className="text-danger" onSelect={() => void deleteCurrentChat()}><Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />Delete</MenuItemWithIcon></MenuContent></Menu>}
              <button type="button" aria-label="Toggle workspace panel" aria-pressed={rightPanelOpen} onClick={() => setRightPanelOpen((value) => !value)} className="icon-button size-8"><PanelRight size={17} strokeWidth={1.75} aria-hidden="true" /></button>
            </div>
          </header>
          {chat.isError ? <p className="p-6 text-sm text-fg-muted">Chat not found.</p> : <>
            <div ref={threadScrollRef} onScroll={(event) => { const element = event.currentTarget; setShowScrollButton(element.scrollHeight - element.scrollTop - element.clientHeight > 160) }} className="min-h-0 flex-1 overflow-y-auto">
              <MessageList messages={messages.data ?? []} live={live} optimisticQuestion={optimisticQuestion} onSuggestion={(question) => void onSend(question, { mode: 'auto', source: 'auto' })} onAbstainAction={onAbstainAction} onOpenSources={openSources} onSelectMessage={setSelectedMessageId} onShowSteps={() => { setRightPanelOpen(true); setTraceTab('trace') }} />
              {live?.status === 'failed' && live.error && <p role="alert" className="mx-auto max-w-[720px] px-4 pb-4 text-sm text-warning">{runFailureMessage(live.error)}</p>}
              {live?.status === 'connection_lost' && <div className="mx-auto max-w-[720px] px-4 pb-4"><button type="button" onClick={resume} className="pressable rounded-lg border border-border/40 px-3 py-1.5 text-sm text-danger hover:bg-raised focus-visible:outline-2 focus-visible:outline-danger">Connection lost — resume</button></div>}
            </div>
            {showScrollButton && <button type="button" aria-label="Scroll to bottom" onClick={scrollToBottom} className="icon-button absolute bottom-[9.5rem] left-1/2 z-20 size-9 -translate-x-1/2 rounded-full border border-border bg-raised"><ArrowDown size={16} strokeWidth={1.75} aria-hidden="true" /></button>}
            <ChatComposer streaming={streaming} modelId={chat.data?.model_id ?? null} quota={quota.data} collections={collections.data ?? []} collectionIds={collectionIds} error={sendError} emptyThread={(messages.data ?? []).length === 0} onModelChange={(modelId) => void patchChat.mutateAsync({ chatId, patch: { model_id: modelId } })} onCollectionChange={onCollectionChange} onSend={(message, options) => void onSend(message, options)} onStop={() => activeRunId && cancelRun.mutate(activeRunId)} />
          </>}
        </main>
        <TracePanel steps={trace?.steps ?? []} decisions={trace?.decisions ?? []} thinking={trace?.thinking ?? ''} streaming={trace?.streaming ?? false} chunks={trace?.chunks ?? []} metrics={trace?.metrics ?? null} hold={trace?.hold ?? false} query={lastQuestion} open={rightPanelOpen} expanded={rightPanelExpanded} activeTab={traceTab} focusSource={focusSource} selectedMessage={selectedMessage} onOpenChange={setRightPanelOpen} onExpandedChange={setRightPanelExpanded} onTabChange={setTraceTab} onOpenDocument={() => void navigate({ to: '/sources' })} />
      </div>
    </div>
  )
}

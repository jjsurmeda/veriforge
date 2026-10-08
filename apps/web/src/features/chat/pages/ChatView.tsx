import { useEffect, useRef, useState } from 'react'
import { ArrowDown, Check, MoreHorizontal, PanelRight, Pencil, Pin, Trash2 } from 'lucide-react'
import { useNavigate } from '@tanstack/react-router'

import type { MessageOut } from '../../../generated/types.gen'
import { useChat, useMessages } from '../hooks/useChat'
import { useCancelRun, useCreateRun } from '../hooks/useRuns'
import { useRunStream } from '../hooks/useRunStream'
import { useQuota } from '../hooks/useQuota'
import { useUploadChatDocument } from '../../library/hooks/useDocuments'
import { useDemoLimits } from '../../demo/hooks/useDemoLimits'
import { useDeleteChat, usePatchChat } from '../hooks/useChatList'
import { useChatRunStore } from '../store'
import { ChatComposer, runOptions, type RunMode, type RunSource } from '../components/ChatComposer'
import { ChatSidebar } from '../components/ChatSidebar'
import { MessageList } from '../components/MessageList'
import { TracePanel, type TraceTab } from '../../trace/components/TracePanel'
import { useTrace } from '../../trace/hooks/useTrace'
import { Menu, MenuContent, MenuItemWithIcon, MenuTrigger } from '../../../components/ui/primitives'
import { PanelError } from '../../../components/ui/PanelError'
import { PanelNote } from '../../../components/ui/PanelNote'

export function runFailureMessage(code: string, quotaResetAt?: string): string {
  if (code === 'web_search_unconfigured') return "Couldn't search the web because no web search provider is configured. Try your documents instead."
  if (code === 'web_search_failed') return 'The web search provider could not answer that question. Try again.'
  // KI-23: a quota or provider-key failure cannot be retried away, so it
  // must not send the user back in a loop that spends nothing and succeeds
  // never. These three codes are published by the API on run.failed.
  if (code === 'quota_exceeded') {
    return quotaResetAt
      ? `You've reached your limit for this window; resets at ${quotaResetAt}.`
      : "You've reached your limit for this window. It resets on a timer — your chats and documents are untouched."
  }
  if (code === 'provider_key_invalid') {
    return 'The model provider rejected our API key, so nothing will run until it is replaced. This is on us, not on you.'
  }
  if (code === 'provider_unavailable') {
    return 'The model provider is unavailable right now. Nothing will run until it recovers; your chats and documents are fine.'
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

/** The API answers a chat that is gone (or was never yours) with a 404
 *  `chat_not_found`; offline, a 500, a session that failed to refresh — none
 *  of those prove the chat is absent, so they must not borrow that copy. */
function isChatMissing(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  const body = error as { error_code?: unknown; data?: { error_code?: unknown } }
  return body.error_code === 'chat_not_found' || body.data?.error_code === 'chat_not_found'
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
  const upload = useUploadChatDocument(chatId)
  const demoLimits = useDemoLimits()
  const [viewerDocumentId, setViewerDocumentId] = useState<string | null>(null)
  const [activeRunId, setActiveRunId] = useState<string | null>(null)
  const [traceRunId, setTraceRunId] = useState<string | null>(null)
  const [traceScrollSignal, setTraceScrollSignal] = useState(0)
  const [sendError, setSendError] = useState<string | null>(null)
  const [optimisticQuestion, setOptimisticQuestion] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [rightPanelOpen, setRightPanelOpen] = useState(() => window.innerWidth >= 1024)
  const [rightPanelExpanded, setRightPanelExpanded] = useState(false)
  const [traceTab, setTraceTab] = useState<TraceTab>('trace')
  const [focusSource, setFocusSource] = useState<number | null>(null)
  const [selectedMessageId, setSelectedMessageId] = useState<string | null>(null)
  const [deep, setDeep] = useState(false)
  const [web, setWeb] = useState(false)
  const [threadEditing, setThreadEditing] = useState(false)
  const [threadTitleDraft, setThreadTitleDraft] = useState('')
  const [showScrollButton, setShowScrollButton] = useState(false)
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

  const { resume } = useRunStream(activeRunId, chatId)
  // A finished run has no store entry, so the stream is what replays its
  // persisted run_events; invalidate: false keeps a replay from refetching.
  useRunStream(traceRunId !== activeRunId ? traceRunId : null, chatId, { invalidate: false })
  const live = useChatRunStore((s) => (activeRunId ? s.runs[activeRunId] : undefined))

  useEffect(() => {
    if (live?.status === 'completed' || live?.status === 'failed' || live?.status === 'cancelled') setOptimisticQuestion(null)
  }, [live?.status])
  const trace = useTrace(traceRunId)
  const streaming = live !== undefined && (live.status === 'connecting' || live.status === 'streaming')
  const selectedMessage = selectedMessageId ? messages.data?.find((message) => message.id === selectedMessageId) : [...(messages.data ?? [])].reverse().find((message) => message.role === 'assistant')
  const lastQuestion = [...(messages.data ?? [])].reverse().find((message) => message.role === 'user')?.content ?? null
  const replayedTrace = traceRunId
    ? { runId: traceRunId, decisions: trace?.decisions ?? [], chunks: trace?.chunks ?? [] }
    : null

  const onSend = async (message: string, options: { mode: RunMode; source: RunSource }) => {
    setSendError(null)
    setOptimisticQuestion(message)
    try {
      const run = await createRun.mutateAsync({ message, modelId: chat.data?.model_id, mode: options.mode, source: options.source })
      useChatRunStore.getState().begin(run!.run_id, run!.message_id)
      setActiveRunId(run!.run_id)
      void quota.refetch()
    } catch (error) {
      setOptimisticQuestion(null)
      setSendError(errorMessage(error))
      void quota.refetch()
    }
  }

  const onFiles = async (files: File[]) => {
    setSendError(null)
    setRightPanelOpen(true)
    setTraceTab('sources')
    setViewerDocumentId(null)
    try {
      for (const file of files) await upload.mutateAsync(file)
    } catch (error) {
      setSendError(errorMessage(error))
    }
  }

  // Item 4: a demo account is offered neither path, so the decline does not
    // show buttons whose only outcome is a refusal. The abstain template still
    // mentions them (it is server-written text); hiding the controls is what
    // stops the promise.
  const demoMayDeep = demoLimits.data?.allow_deep ?? true
  const demoMayWeb = demoLimits.data?.allow_web ?? true

  const onAbstainAction = (action: 'web' | 'deep') => {
    if (!lastQuestion) return
    if (action === 'deep' && !demoMayDeep) return
    if (action === 'web' && !demoMayWeb) return
    if (action === 'deep') setDeep(true)
    else setWeb(true)
    void onSend(lastQuestion, runOptions(action === 'deep' || deep, action === 'web' || web))
  }

  const showSteps = (message: MessageOut) => {
    if (!message.run_id) return
    setRightPanelOpen(true)
    setTraceTab('trace')
    setTraceRunId(message.run_id)
    setSelectedMessageId(message.id)
    setFocusSource(null)
    setTraceScrollSignal((n) => n + 1)
  }

  const openCitations = (sourceNumber?: number, messageId?: string) => {
    setRightPanelOpen(true)
    setTraceTab('citations')
    setFocusSource(sourceNumber ?? null)
    if (messageId) setSelectedMessageId(messageId)
  }

  const viewDocument = (documentId: string) => {
    setRightPanelOpen(true)
    setTraceTab('sources')
    setViewerDocumentId(documentId)
  }

  // Item 2: the decline message's link opens the Trace on the gate that
  // blocked. Scrolling the card into view matters as much as switching tabs —
  // at 1280px+ the panel is beside the thread and the card sits above the
  // fold of a long decision timeline, so without it the click looks like it
  // did nothing.
  const showGates = () => {
    setRightPanelOpen(true)
    setTraceTab('trace')
    setTraceScrollSignal((n) => n + 1)
    requestAnimationFrame(() => {
      document.getElementById('evidence-gates')?.scrollIntoView({ block: 'start' })
    })
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
          {chat.isPending ? (
            <div className="p-4"><PanelNote>Reading this conversation…</PanelNote></div>
          ) : chat.isError ? (
            isChatMissing(chat.error) ? (
              <p className="p-6 text-sm text-fg-muted">Chat not found.</p>
            ) : (
              <div className="p-6">
                <PanelError
                  title="This conversation could not be loaded."
                  hint="Nothing was changed. Try again in a moment."
                  action={
                    <button
                      type="button"
                      onClick={() => void chat.refetch()}
                      className="pressable min-h-9 w-full rounded-lg border border-border bg-surface px-3 text-xs text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring"
                    >
                      Try again
                    </button>
                  }
                />
              </div>
            )
          ) : <>
            <div ref={threadScrollRef} onScroll={(event) => { const element = event.currentTarget; setShowScrollButton(element.scrollHeight - element.scrollTop - element.clientHeight > 160) }} className="min-h-0 flex-1 overflow-y-auto">
              {messages.isPending && <div className="px-4 pt-4"><PanelNote>Reading this conversation…</PanelNote></div>}
              {/* Item 6: a failed history read used to render as a brand-new
                  empty thread, which reads as "your conversation is gone"
                  when nothing has been deleted at all. */}
              {messages.isError && (
                <p role="alert" className="mx-auto max-w-[720px] px-4 py-4 text-center text-sm text-danger">
                  This conversation’s messages could not be read.{' '}
                  <button type="button" onClick={() => void messages.refetch()} className="pressable rounded-lg border border-border/40 px-2 py-1 text-xs text-danger hover:bg-raised focus-visible:outline-2 focus-visible:outline-danger">Try again</button>
                </p>
              )}
              <MessageList messages={messages.data ?? []} live={live} optimisticQuestion={optimisticQuestion} replay={replayedTrace} mayUse={{ web: demoMayWeb, deep: demoMayDeep }} onSuggestion={(question) => void onSend(question, runOptions(deep, web))} onAbstainAction={onAbstainAction} onOpenSources={openCitations} onSelectMessage={setSelectedMessageId} onShowSteps={showSteps} onShowGates={showGates} />
              {live?.status === 'failed' && live.error && <p role="alert" className="mx-auto max-w-[720px] px-4 pb-4 text-sm text-warning">{runFailureMessage(live.error, quota.data?.reset_at_5h)}</p>}
              {live?.status === 'connection_lost' && <div className="mx-auto max-w-[720px] px-4 pb-4"><button type="button" onClick={resume} className="pressable rounded-lg border border-border/40 px-3 py-1.5 text-sm text-danger hover:bg-raised focus-visible:outline-2 focus-visible:outline-danger">Connection lost — resume</button></div>}
            </div>
            {showScrollButton && <button type="button" aria-label="Scroll to bottom" onClick={scrollToBottom} className="icon-button absolute bottom-[9.5rem] left-1/2 z-20 size-9 -translate-x-1/2 rounded-full border border-border bg-raised"><ArrowDown size={16} strokeWidth={1.75} aria-hidden="true" /></button>}
            <ChatComposer streaming={streaming} modelId={chat.data?.model_id ?? null} quota={quota.data} error={sendError} emptyThread={!messages.isPending && !messages.isError && (messages.data ?? []).length === 0} deep={deep} web={web} onFiles={(files) => void onFiles(files)} onModelChange={(modelId) => void patchChat.mutateAsync({ chatId, patch: { model_id: modelId } })} allowDeep={demoLimits.data?.allow_deep ?? true} allowWeb={demoLimits.data?.allow_web ?? true} onToggleDeep={setDeep} onToggleWeb={setWeb} onSend={(message, options) => void onSend(message, options)} onStop={() => activeRunId && cancelRun.mutate(activeRunId)} />
          </>}
        </main>
        <TracePanel steps={trace?.steps ?? []} decisions={trace?.decisions ?? []} thinking={trace?.thinking ?? ''} streaming={trace?.streaming ?? false} chunks={trace?.chunks ?? []} metrics={trace?.metrics ?? null} hold={trace?.hold ?? false} query={lastQuestion} chatId={chatId} viewerDocumentId={viewerDocumentId} open={rightPanelOpen} expanded={rightPanelExpanded} activeTab={traceTab} focusSource={focusSource} selectedMessage={selectedMessage} onOpenChange={setRightPanelOpen} onExpandedChange={setRightPanelExpanded} onTabChange={setTraceTab} onViewDocument={viewDocument} onCloseViewer={() => setViewerDocumentId(null)} scrollToTopSignal={traceScrollSignal} traceStatus={trace?.status ?? null} onRetryTrace={traceRunId !== activeRunId ? undefined : resume} />
      </div>
    </div>
  )
}

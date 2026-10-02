import { useNavigate } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'
import { Menu } from 'lucide-react'

import { createRunChatsChatIdRunsPost, uploadChatDocumentChatsChatIdDocumentsPost } from '../../../generated/sdk.gen'
import { useChatList, useCreateChat } from '../hooks/useChatList'
import { useQuota } from '../hooks/useQuota'
import { ChatComposer, runOptions, type RunMode, type RunSource } from '../components/ChatComposer'
import { ChatSidebar } from '../components/ChatSidebar'
import { useLibrary } from '../../library/hooks/useDocuments'
import { StarterQuestions } from '../../library/components/StarterQuestions'

export function ChatIndexPage() {
  const navigate = useNavigate()
  const { data: chats, isPending } = useChatList()
  const createChat = useCreateChat()
  const library = useLibrary()
  const quota = useQuota()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [deep, setDeep] = useState(false)
  const [web, setWeb] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pendingFiles = useRef<File[]>([])

  useEffect(() => {
    if (!isPending && chats && chats.length > 0) {
      void navigate({ to: '/chat/$chatId', params: { chatId: chats[0].id }, replace: true })
    }
  }, [chats, isPending, navigate])

  // A file leaves the queue only once its upload succeeded, so a failed
  // upload is retried with the next question instead of being lost (P1).
  const uploadPendingInto = async (chatId: string) => {
    for (const file of [...pendingFiles.current]) {
      const { error: uploadError } = await uploadChatDocumentChatsChatIdDocumentsPost({
        path: { chat_id: chatId },
        body: { file },
      })
      if (uploadError) throw uploadError
      pendingFiles.current = pendingFiles.current.filter((queued) => queued !== file)
    }
  }

  const startRun = async (message: string, options: { mode: RunMode; source: RunSource }) => {
    setError(null)
    try {
      const chat = await createChat.mutateAsync()
      const chatId = chat!.id
      await uploadPendingInto(chatId)
      const { error: runError } = await createRunChatsChatIdRunsPost({
        path: { chat_id: chatId },
        body: { message, mode: options.mode, source: options.source },
      })
      if (runError) throw runError
      void navigate({ to: '/chat/$chatId', params: { chatId } })
    } catch (cause) {
      setError('That did not go through. Your files are still queued — try again.')
    }
  }

  const onFiles = async (files: File[]) => {
    if (files.length === 0) return
    setError(null)
    pendingFiles.current = [...pendingFiles.current, ...files]
    try {
      const chat = await createChat.mutateAsync()
      const chatId = chat!.id
      await uploadPendingInto(chatId)
      void navigate({ to: '/chat/$chatId', params: { chatId } })
    } catch {
      setError('That upload did not finish. Your files are still queued — try again.')
    }
  }
  return (
    <div className="flex h-full min-h-0 bg-main text-fg">
      <ChatSidebar currentChatId={null} mobileOpen={sidebarOpen} onMobileClose={() => setSidebarOpen(false)} />
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3 lg:hidden">
          <button type="button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)} className="icon-button size-9"><Menu size={17} strokeWidth={1.75} aria-hidden="true" /></button>
          <span className="text-sm font-semibold text-fg">Veriforge</span>
          <span className="size-9" aria-hidden="true" />
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-4 py-10 sm:px-8">
          <section className="w-full max-w-[720px]">
            <div className="mb-8 text-center">
              <h1 className="text-xs font-medium uppercase tracking-[0.12em] text-fg-subtle">No chat selected</h1>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-fg sm:text-4xl">What do you want to know?</h1>
              <p className="mx-auto mt-3 max-w-[42ch] text-sm leading-6 text-fg-muted">Drop files to start, or just ask. Follow the evidence while the answer forms.</p>
            </div>
            <ChatComposer streaming={false} modelId={null} quota={quota.data} emptyThread error={error} deep={deep} web={web} onFiles={(files) => void onFiles(files)} onModelChange={() => undefined} onToggleDeep={setDeep} onToggleWeb={setWeb} onSend={(message, options) => void startRun(message, options)} onStop={() => undefined} />
            <div className="mx-auto mt-6 max-w-[720px]">
              <StarterQuestions questions={library.data?.starter_questions ?? []} onSelect={(question) => void startRun(question, runOptions(deep, web))} />
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

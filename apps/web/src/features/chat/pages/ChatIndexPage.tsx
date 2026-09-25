import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Menu } from 'lucide-react'

import { createRunChatsChatIdRunsPost } from '../../../generated/sdk.gen'
import { useChatList, useCreateChat } from '../hooks/useChatList'
import { useQuota } from '../hooks/useQuota'
import { ChatComposer } from '../components/ChatComposer'
import type { RunMode } from '../components/ModePicker'
import type { RunSource } from '../components/SourcePicker'
import { ChatSidebar } from '../components/ChatSidebar'
import { useCollections } from '../../sources/hooks/useCollections'
import { StarterQuestions } from '../../sources/components/StarterQuestions'

export function ChatIndexPage() {
  const navigate = useNavigate()
  const { data: chats, isPending } = useChatList()
  const createChat = useCreateChat()
  const collections = useCollections()
  const quota = useQuota()
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [collectionIds, setCollectionIds] = useState<string[]>([])

  useEffect(() => {
    if (!isPending && chats && chats.length > 0) {
      void navigate({ to: '/chat/$chatId', params: { chatId: chats[0].id }, replace: true })
    }
  }, [chats, isPending, navigate])

  const starters: Array<{ question: string; collectionId: string }> = []
  for (const collection of collections.data ?? []) {
    for (const question of collection.starter_questions ?? []) {
      if (!starters.some((starter) => starter.question === question)) starters.push({ question, collectionId: collection.id })
    }
  }

  const startRun = async (message: string, options: { mode: RunMode; source: RunSource }, selectedCollectionIds = collectionIds) => {
    const chat = await createChat.mutateAsync({ collectionIds: selectedCollectionIds })
    const chatId = chat!.id
    await createRunChatsChatIdRunsPost({ path: { chat_id: chatId }, body: { message, mode: options.mode, source: options.source } })
    void navigate({ to: '/chat/$chatId', params: { chatId } })
  }

  return (
    <div className="flex h-full min-h-0 bg-background text-foreground">
      <ChatSidebar currentChatId={null} mobileOpen={sidebarOpen} onMobileClose={() => setSidebarOpen(false)} />
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3 lg:hidden">
          <button type="button" aria-label="Open navigation" onClick={() => setSidebarOpen(true)} className="icon-button size-9"><Menu size={17} strokeWidth={1.75} aria-hidden="true" /></button>
          <span className="text-sm font-semibold text-foreground">Veriforge</span>
          <span className="size-9" aria-hidden="true" />
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-y-auto px-4 py-10 sm:px-8">
          <section className="w-full max-w-[720px]">
            <div className="mb-8 text-center">
              <h1 className="text-xs font-medium uppercase tracking-[0.12em] text-subtle-foreground">No chat selected</h1>
              <h1 className="mt-3 text-3xl font-semibold tracking-tight text-foreground sm:text-4xl">What do you want to know?</h1>
              <p className="mx-auto mt-3 max-w-[42ch] text-sm leading-6 text-muted-foreground">Ask a question and follow the evidence while the answer forms.</p>
            </div>
            <ChatComposer streaming={false} modelId={null} quota={quota.data} collections={collections.data ?? []} collectionIds={collectionIds} emptyThread onModelChange={() => undefined} onCollectionChange={setCollectionIds} onSend={(message, options) => void startRun(message, options)} onStop={() => undefined} />
            <div className="mx-auto mt-6 max-w-[720px]">
              <StarterQuestions questions={starters.map((starter) => starter.question)} onSelect={(question) => { const starter = starters.find((entry) => entry.question === question); if (starter) void startRun(question, { mode: 'auto', source: 'auto' }, [starter.collectionId]) }} />
            </div>
          </section>
        </div>
      </main>
    </div>
  )
}

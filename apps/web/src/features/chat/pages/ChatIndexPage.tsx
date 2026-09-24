import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { Menu, Plus, Sparkles } from 'lucide-react'

import { createRunChatsChatIdRunsPost } from '../../../generated/sdk.gen'
import { useChatList, useCreateChat } from '../hooks/useChatList'
import { ChatSidebar } from '../components/ChatSidebar'
import { useCollections } from '../../sources/hooks/useCollections'

export function ChatIndexPage() {
  const navigate = useNavigate()
  const { data: chats, isPending } = useChatList()
  const createChat = useCreateChat()
  const collections = useCollections()
  const [sidebarOpen, setSidebarOpen] = useState(false)

  useEffect(() => {
    if (!isPending && chats && chats.length > 0) {
      void navigate({ to: '/chat/$chatId', params: { chatId: chats[0].id }, replace: true })
    }
  }, [chats, isPending, navigate])

  const onNew = async () => {
    const chat = await createChat.mutateAsync({})
    void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
  }

  const starters: Array<{ question: string; collectionId: string }> = []
  for (const collection of collections.data ?? []) {
    for (const question of collection.starter_questions ?? []) {
      if (!starters.some((starter) => starter.question === question)) {
        starters.push({ question, collectionId: collection.id })
      }
    }
  }

  const onStart = async (question: string, collectionId: string) => {
    const chat = await createChat.mutateAsync({ collectionIds: [collectionId] })
    const chatId = chat!.id
    await createRunChatsChatIdRunsPost({
      path: { chat_id: chatId },
      body: { message: question, mode: 'auto', source: 'auto' },
    })
    void navigate({ to: '/chat/$chatId', params: { chatId } })
  }

  return (
    <div className="theme-transition flex h-screen bg-background text-foreground">
      <ChatSidebar
        currentChatId={null}
        mobileOpen={sidebarOpen}
        onMobileClose={() => setSidebarOpen(false)}
      />
      <main className="flex flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-2 lg:hidden">
          <button
            type="button"
            aria-label="Open navigation"
            onClick={() => setSidebarOpen(true)}
            className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface-muted text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-primary-soft hover:text-primary active:translate-y-px focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            <Menu size={17} aria-hidden="true" />
          </button>
          <span className="text-sm font-semibold text-foreground">Veriforge</span>
          <span className="size-9" aria-hidden="true" />
        </div>
        <div className="flex flex-1 items-center justify-center overflow-y-auto p-6 sm:p-10">
        <section className="w-full max-w-[56ch] rounded-xl border border-border bg-surface p-6 shadow-md sm:p-8">
          <div className="mb-5 flex items-center gap-2 text-primary">
            <Sparkles size={18} aria-hidden="true" />
            <span className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.14em]">New inquiry</span>
          </div>
          <h1 className="font-display text-2xl font-semibold tracking-tight text-foreground">No chat selected</h1>
          <p className="mt-2 max-w-[52ch] text-sm leading-6 text-muted-foreground">
            Start a chat to ask a question — answers stream with citations, and
            the Reviewer verifies every claim against its sources.
          </p>
          {starters.length > 0 && (
            <div className="mt-6 max-w-[52ch]">
              <h2 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Starter questions
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {starters.slice(0, 6).map(({ question, collectionId }) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => void onStart(question, collectionId)}
                    className="min-h-9 rounded-lg border border-border bg-surface-muted px-3 py-1.5 text-left text-xs text-foreground transition-[background-color,border-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary-soft hover:shadow-sm active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transform-none motion-reduce:transition-none"
                  >
                    {question}
                  </button>
                ))}
              </div>
            </div>
          )}
          <button
              type="button"
              onClick={() => void onNew()}
              className="mt-6 inline-flex min-h-10 items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transform-none motion-reduce:transition-none"
            >
              <Plus size={16} aria-hidden="true" />
              New chat
            </button>
         </section>
        </div>
      </main>

    </div>
  )
}

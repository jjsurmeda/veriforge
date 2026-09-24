import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { createRunChatsChatIdRunsPost } from '../../../generated/sdk.gen'
import { useChatList, useCreateChat } from '../hooks/useChatList'
import { ChatSidebar } from '../components/ChatSidebar'
import { useCollections } from '../../sources/hooks/useCollections'

export function ChatIndexPage() {
  const navigate = useNavigate()
  const { data: chats, isPending } = useChatList()
  const createChat = useCreateChat()
  const collections = useCollections()

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
    <div className="flex h-screen bg-ink text-paper">
      <ChatSidebar currentChatId={null} />
      <main className="flex flex-1 items-start p-10">
        <div>
          <h1 className="font-display text-2xl text-paper">No chat selected</h1>
          <p className="mt-2 max-w-[52ch] text-sm text-paper/60">
            Start a chat to ask a question — answers stream with citations, and
            the Reviewer verifies every claim against its sources.
          </p>
          {starters.length > 0 && (
            <div className="mt-6 max-w-[52ch]">
              <h2 className="text-xs font-medium uppercase tracking-wide text-paper/50">
                Starter questions
              </h2>
              <div className="mt-2 flex flex-wrap gap-2">
                {starters.slice(0, 6).map(({ question, collectionId }) => (
                  <button
                    key={question}
                    type="button"
                    onClick={() => void onStart(question, collectionId)}
                    className="rounded border border-mist bg-graphite px-2.5 py-1.5 text-left text-xs text-paper/80 hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
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
            className="mt-6 rounded border border-mist px-4 py-2 text-sm text-paper hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
          >
            New chat
          </button>
        </div>
      </main>
    </div>
  )
}

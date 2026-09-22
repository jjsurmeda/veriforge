import { useNavigate } from '@tanstack/react-router'
import { useEffect } from 'react'

import { useChatList, useCreateChat } from '../hooks/useChatList'
import { ChatSidebar } from '../components/ChatSidebar'

export function ChatIndexPage() {
  const navigate = useNavigate()
  const { data: chats, isPending } = useChatList()
  const createChat = useCreateChat()

  useEffect(() => {
    if (!isPending && chats && chats.length > 0) {
      void navigate({ to: '/chat/$chatId', params: { chatId: chats[0].id }, replace: true })
    }
  }, [chats, isPending, navigate])

  const onNew = async () => {
    const chat = await createChat.mutateAsync(undefined)
    void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
  }

  return (
    <div className="flex h-screen bg-ink text-paper">
      <ChatSidebar currentChatId={null} />
      <main className="flex flex-1 items-start p-10">
        <div>
          <h1 className="font-display text-2xl text-paper">No chat selected</h1>
          <p className="mt-2 max-w-[52ch] text-sm text-paper/60">
            Start a chat to ask a question. Retrieval, citations and verification land in later
            slices — right now you get plain model streaming.
          </p>
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

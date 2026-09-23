import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { logout } from '../../../lib/auth'
import { queryClient } from '../../../lib/queryClient'
import { useChatList, useCreateChat, useDeleteChat } from '../hooks/useChatList'

export function ChatSidebar({ currentChatId }: { currentChatId: string | null }) {
  const navigate = useNavigate()
  const { data: chats } = useChatList()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const [creating, setCreating] = useState(false)

  const onNewChat = async () => {
    setCreating(true)
    try {
      const chat = await createChat.mutateAsync(undefined)
      void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
    } finally {
      setCreating(false)
    }
  }

  const onLogout = async () => {
    await logout()
    queryClient.clear()
    void navigate({ to: '/login' })
  }

  return (
    <aside className="flex h-full w-64 flex-col border-r border-mist bg-graphite">
      <div className="flex items-center justify-between border-b border-mist px-4 py-3">
        <span className="font-display text-lg tracking-tight text-paper">Veriforge</span>
        <button
          type="button"
          onClick={() => void onNewChat()}
          disabled={creating}
          className="rounded border border-mist px-2.5 py-1 text-xs text-paper hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember"
        >
          New chat
        </button>
      </div>
      <nav className="flex-1 overflow-y-auto py-1">
        {(chats ?? []).map((chat) => (
          <div
            key={chat.id}
            className={`group flex items-center gap-2 px-4 py-2 text-sm ${
              chat.id === currentChatId ? 'bg-mist/60 text-paper' : 'text-paper/70 hover:bg-mist/30'
            }`}
          >
            <button
              type="button"
              className="min-w-0 flex-1 truncate text-left focus-visible:outline-2 focus-visible:outline-ember"
              onClick={() => void navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
            >
              {chat.pinned ? '★ ' : ''}
              {chat.title}
            </button>
            <button
              type="button"
              aria-label={`Delete ${chat.title}`}
              onClick={() => void deleteChat.mutateAsync(chat.id)}
              className="invisible text-paper/40 group-hover:visible hover:text-rust focus-visible:visible focus-visible:outline-2 focus-visible:outline-ember"
            >
              ×
            </button>
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-mist px-4 py-3">
        <button
          type="button"
          onClick={() => void navigate({ to: '/sources' })}
          className="text-xs text-paper/50 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
        >
          Sources
        </button>
        <button
          type="button"
          onClick={() => void onLogout()}
          className="text-xs text-paper/50 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
        >
          Sign out
        </button>
      </div>
    </aside>
  )
}

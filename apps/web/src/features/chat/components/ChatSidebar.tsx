import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { useMe } from '../../auth/hooks/useMe'
import { useCollections } from '../../sources/hooks/useCollections'
import { logout } from '../../../lib/auth'
import { queryClient } from '../../../lib/queryClient'
import { CollectionPicker } from './CollectionPicker'
import { useChatList, useCreateChat, useDeleteChat, usePatchChat } from '../hooks/useChatList'

export function ChatSidebar({ currentChatId }: { currentChatId: string | null }) {
  const navigate = useNavigate()
  const { data: chats } = useChatList()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const patchChat = usePatchChat()
  const collections = useCollections()
  const me = useMe()
  const [creating, setCreating] = useState(false)
  const [newChatCollectionIds, setNewChatCollectionIds] = useState<string[]>([])
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')

  const beginRename = (chatId: string, title: string) => {
    setEditingChatId(chatId)
    setTitleDraft(title)
  }

  const saveRename = async () => {
    if (!editingChatId) return
    const title = titleDraft.trim()
    if (!title) return
    await patchChat.mutateAsync({ chatId: editingChatId, patch: { title } })
    setEditingChatId(null)
  }

  const onNewChat = async () => {
    setCreating(true)
    try {
      const chat = await createChat.mutateAsync({ collectionIds: newChatCollectionIds })
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
      {currentChatId === null && (
        <div className="border-b border-mist px-4 py-3">
          <CollectionPicker
            collections={collections.data ?? []}
            value={newChatCollectionIds}
            onChange={setNewChatCollectionIds}
            disabled={creating}
          />
        </div>
      )}
      <nav className="flex-1 overflow-y-auto py-1">
        {(chats ?? []).map((chat) => (
          <div
            key={chat.id}
            className={`group flex items-center gap-2 px-4 py-2 text-sm ${
              chat.id === currentChatId ? 'bg-mist/60 text-paper' : 'text-paper/70 hover:bg-mist/30'
            }`}
          >
            {editingChatId === chat.id ? (
              <div className="flex min-w-0 flex-1 items-center gap-1">
                <input
                  aria-label={`Rename ${chat.title}`}
                  value={titleDraft}
                  onChange={(event) => setTitleDraft(event.currentTarget.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') void saveRename()
                    if (event.key === 'Escape') setEditingChatId(null)
                  }}
                  className="min-w-0 flex-1 rounded border border-mist bg-ink px-2 py-1 text-xs text-paper focus-visible:outline-2 focus-visible:outline-ember"
                />
                <button
                  type="button"
                  aria-label="Save rename"
                  onClick={() => void saveRename()}
                  className="text-[0.65rem] text-paper/60 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
                >
                  Save
                </button>
              </div>
            ) : (
              <>
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
                  aria-label={`Rename ${chat.title}`}
                  onClick={() => beginRename(chat.id, chat.title)}
                  className="text-[0.65rem] text-paper/40 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
                >
                  Rename
                </button>
                <button
                  type="button"
                  aria-label={`${chat.pinned ? 'Unpin' : 'Pin'} ${chat.title}`}
                  aria-pressed={chat.pinned}
                  onClick={() =>
                    void patchChat.mutateAsync({
                      chatId: chat.id,
                      patch: { pinned: !chat.pinned },
                    })
                  }
                  className="text-[0.65rem] text-paper/40 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
                >
                  {chat.pinned ? 'Unpin' : 'Pin'}
                </button>
              </>
            )}
            <button
              type="button"
              aria-label={`Delete ${chat.title}`}
              onClick={() => void deleteChat.mutateAsync(chat.id)}
              className="text-paper/40 hover:text-rust focus-visible:outline-2 focus-visible:outline-ember"
            >
              ×
            </button>
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between border-t border-mist px-4 py-3">
        <div className="flex items-center gap-3">
          {me.data?.role === 'admin' && (
            <button
              type="button"
              onClick={() => void navigate({ to: '/admin' })}
              className="text-xs text-ember hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
            >
              Admin
            </button>
          )}
          <button
            type="button"
            onClick={() => void navigate({ to: '/sources' })}
            className="text-xs text-paper/50 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
          >
            Sources
          </button>
        </div>
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

import { useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import {
  Check,
  Library,
  MessageSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  Plus,
  Trash2,
  X,
} from 'lucide-react'

import { useCollections } from '../../sources/hooks/useCollections'
import { CollectionPicker } from './CollectionPicker'
import { useChatList, useCreateChat, useDeleteChat, usePatchChat } from '../hooks/useChatList'

const SIDEBAR_STORAGE_KEY = 'veriforge-chat-sidebar-collapsed'

export function ChatSidebar({
  currentChatId,
  mobileOpen = false,
  onMobileClose,
}: {
  currentChatId: string | null
  mobileOpen?: boolean
  onMobileClose?: () => void
}) {
  const navigate = useNavigate()
  const { data: chats } = useChatList()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const patchChat = usePatchChat()
  const collections = useCollections()
  const [collapsed, setCollapsed] = useState(
    () => window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === 'true',
  )
  const [creating, setCreating] = useState(false)
  const [newChatCollectionIds, setNewChatCollectionIds] = useState<string[]>([])
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const rail = collapsed && !mobileOpen

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(collapsed))
  }, [collapsed])

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
      onMobileClose?.()
      void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onMobileClose}
           className="fixed bottom-0 left-0 right-0 top-14 z-40 bg-background/70 backdrop-blur-sm lg:hidden"
        />
      )}
      <aside
        className={`${
          mobileOpen
            ? 'fixed bottom-0 left-0 top-14 z-50 flex w-[min(20rem,85vw)]'
            : 'hidden lg:flex'
        } ${collapsed ? 'lg:w-16' : 'lg:w-72'} h-full shrink-0 flex-col border-r border-border bg-surface/80 shadow-lg backdrop-blur-md lg:shadow-sm`}
      >
        <div className={`flex items-center border-b border-border ${rail ? 'justify-center px-2 py-3' : 'justify-between gap-3 px-4 py-4'}`}>
          <div className={`flex min-w-0 items-center ${rail ? 'justify-center' : 'gap-2.5'}`}>
            <span className={`flex size-9 shrink-0 items-center justify-center rounded-xl ${rail ? 'bg-surface-muted text-muted-foreground' : 'bg-primary-soft text-primary shadow-sm'}`}>
              <MessageSquare size={18} aria-hidden="true" />
            </span>
            <div className={`${rail ? 'hidden' : 'min-w-0'}`}>
              <span className="block truncate font-display text-base font-semibold tracking-tight text-foreground">Chats</span>
            </div>
          </div>
          <div className={`${rail ? 'hidden' : 'flex items-center gap-1'}`}>
            <button
              type="button"
              aria-label="New chat"
              onClick={() => void onNewChat()}
              disabled={creating}
              className="inline-flex min-h-9 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-on-primary shadow-sm transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-md active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transform-none motion-reduce:transition-none"
            >
              <Plus size={15} aria-hidden="true" />
              <span className="hidden sm:inline">New chat</span>
            </button>
            <button
              type="button"
              aria-label="Close navigation panel"
              onClick={onMobileClose}
              className="rounded-lg p-2 text-muted-foreground transition-colors duration-180 hover:bg-surface-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary lg:hidden"
            >
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <button
            type="button"
            aria-label={collapsed ? 'Expand chat sidebar' : 'Collapse chat sidebar'}
            aria-pressed={collapsed}
            title={collapsed ? 'Expand chat sidebar' : 'Collapse chat sidebar'}
            onClick={() => setCollapsed((value) => !value)}
            className="hidden size-8 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-surface-muted hover:text-foreground active:translate-y-px focus-visible:outline-2 focus-visible:outline-primary lg:inline-flex motion-reduce:transition-none"
          >
            {collapsed ? <PanelLeftOpen size={16} aria-hidden="true" /> : <PanelLeftClose size={16} aria-hidden="true" />}
          </button>
        </div>

        {currentChatId === null && !rail && (
          <div className="border-b border-border bg-surface-muted/40 px-4 py-3">
            <CollectionPicker
              collections={collections.data ?? []}
              value={newChatCollectionIds}
              onChange={setNewChatCollectionIds}
              disabled={creating}
            />
          </div>
        )}
        <nav className={`flex-1 overflow-y-auto ${rail ? 'px-1.5 py-2' : 'px-2 py-2'}`} aria-label="Chats">
        {(chats ?? []).map((chat) => (
          <div
            key={chat.id}
            className={`group flex min-h-11 items-center rounded-r-lg border-l-2 py-1.5 text-sm transition-[background-color,border-color,transform,box-shadow] duration-180 motion-reduce:transition-none ${
              rail ? 'justify-center px-1' : 'gap-1 px-2'
            } ${
              chat.id === currentChatId
                ? 'border-primary bg-primary-soft text-foreground shadow-sm'
                : 'border-transparent text-muted-foreground hover:-translate-y-px hover:bg-surface-muted hover:text-foreground hover:shadow-sm'
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
                  className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                />
                <button
                  type="button"
                  aria-label="Save rename"
                  onClick={() => void saveRename()}
                  className="rounded-md p-1.5 text-primary transition-colors duration-180 hover:bg-primary-soft focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary motion-reduce:transition-none"
                >
                  <Check size={14} aria-hidden="true" />
                </button>
              </div>
            ) : (
              <>
                <button
                  type="button"
                  aria-label={rail ? chat.title : undefined}
                  title={rail ? chat.title : undefined}
                  className={`flex min-w-0 items-center rounded-md text-left focus-visible:outline-2 focus-visible:outline-primary ${rail ? 'justify-center p-2' : 'flex-1 gap-2 truncate px-1 py-1'}`}
                  onClick={() => void navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
                >
                  {chat.pinned ? (
                    <Pin size={14} className="shrink-0 text-accent" fill="currentColor" aria-hidden="true" />
                  ) : (
                    <MessageSquare size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className={rail ? 'sr-only' : 'truncate'}>{chat.title}</span>
                </button>
                {!rail && (
                  <>
                    <button
                      type="button"
                      aria-label={`Rename ${chat.title}`}
                      onClick={() => beginRename(chat.id, chat.title)}
                      className="rounded-md p-1.5 text-muted-foreground opacity-0 transition-[color,background-color,opacity] duration-180 hover:bg-surface-muted hover:text-foreground group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
                    >
                      <Pencil size={13} aria-hidden="true" />
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
                      className="rounded-md p-1.5 text-muted-foreground transition-[color,background-color] duration-180 hover:bg-accent-soft hover:text-accent focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
                    >
                      <Pin size={13} fill={chat.pinned ? 'currentColor' : 'none'} aria-hidden="true" />
                    </button>
                  </>
                )}
              </>
            )}
            {!rail && (
              <button
                type="button"
                aria-label={`Delete ${chat.title}`}
                onClick={() => void deleteChat.mutateAsync(chat.id)}
                className="rounded-md p-1.5 text-muted-foreground transition-[color,background-color] duration-180 hover:bg-danger-soft hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger motion-reduce:transition-none"
              >
                <Trash2 size={13} aria-hidden="true" />
              </button>
            )}
          </div>
        ))}
      </nav>
      <div className={`flex border-t border-border px-3 py-3 ${rail ? 'justify-center' : 'items-center justify-between gap-2'}`}>
        <button
          type="button"
          aria-label="Sources"
          title="Sources"
          onClick={() => void navigate({ to: '/sources' })}
          className={`inline-flex items-center justify-center rounded-lg text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-secondary-soft hover:text-secondary active:translate-y-px focus-visible:outline-2 focus-visible:outline-secondary motion-reduce:transition-none ${rail ? 'size-9' : 'gap-1.5 px-2 py-1.5 text-xs'}`}
        >
          <Library size={15} aria-hidden="true" />
          {!rail && <span>Sources</span>}
        </button>
      </div>
        </aside>
      </>
    )
  }

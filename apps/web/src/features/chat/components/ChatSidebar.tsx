import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { Check, Library, LogOut, MessageSquare, Pencil, Pin, Plus, ShieldCheck, Trash2, X } from 'lucide-react'

import { ThemeToggle } from '../../../components/ThemeToggle'

import { useMe } from '../../auth/hooks/useMe'
import { useCollections } from '../../sources/hooks/useCollections'
import { useQuota } from '../hooks/useQuota'
import { logout } from '../../../lib/auth'
import { queryClient } from '../../../lib/queryClient'
import type { QuotaOut } from '../../../generated/types.gen'
import { CollectionPicker } from './CollectionPicker'
import { useChatList, useCreateChat, useDeleteChat, usePatchChat } from '../hooks/useChatList'

const quotaNumber = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 })

function quotaPercent(remaining: number, limit: number): number {
  if (limit <= 0) return 0
  return Math.min(100, Math.max(0, (remaining / limit) * 100))
}

function resetLabel(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric' }).format(new Date(value))
}

function QuotaSummary({ quota }: { quota: QuotaOut }) {
  const windows = [
    { label: '5h', remaining: quota.remaining_5h, limit: quota.limit_5h, reset: quota.reset_at_5h },
    {
      label: 'month',
      remaining: quota.remaining_month,
      limit: quota.limit_month,
      reset: quota.reset_at_month,
    },
  ]
  return (
    <div className="border-b border-border bg-surface-muted/60 px-4 py-3" aria-label="Credit quota" aria-live="polite">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-mono text-[0.65rem] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
          Credit quota
        </span>
        <span className="font-mono text-[0.65rem] text-muted-foreground">live</span>
      </div>
      <div className="space-y-2">
        {windows.map((window) => {
          const percent = quotaPercent(window.remaining, window.limit)
          return (
            <div key={window.label} role="group" aria-label={`${window.label} quota`}>
              <div className="mb-1 flex items-baseline justify-between gap-2 text-[0.65rem]">
                <span className="font-medium text-foreground">{window.label}</span>
                <span className="font-mono text-muted-foreground">
                  {quotaNumber.format(window.remaining)} / {quotaNumber.format(window.limit)} · resets {resetLabel(window.reset)}
                </span>
              </div>
              <div className="h-1 overflow-hidden rounded-full bg-border">
                <div
                  className="h-full rounded-full bg-primary transition-[width] duration-300 motion-reduce:transition-none"
                  style={{ width: `${percent}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

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
  const quota = useQuota()
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
      onMobileClose?.()
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
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onMobileClose}
          className="fixed inset-0 z-40 bg-background/70 backdrop-blur-sm lg:hidden"
        />
      )}
      <aside
        className={`${
          mobileOpen
            ? 'fixed inset-y-0 left-0 z-50 flex w-[min(20rem,85vw)]'
            : 'hidden lg:flex lg:w-72'
        } h-full shrink-0 flex-col border-r border-border bg-surface shadow-lg lg:shadow-sm`}
      >
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-4">
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-xl bg-primary-soft text-primary shadow-sm">
            <MessageSquare size={18} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <span className="block truncate font-display text-base font-semibold tracking-tight text-foreground">Veriforge</span>
            <span className="block truncate text-[0.65rem] text-muted-foreground">Evidence workbench</span>
          </div>
        </div>
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

      {quota.data && <QuotaSummary quota={quota.data} />}
      {currentChatId === null && (
        <div className="border-b border-border bg-surface-muted/40 px-4 py-3">
          <CollectionPicker
            collections={collections.data ?? []}
            value={newChatCollectionIds}
            onChange={setNewChatCollectionIds}
            disabled={creating}
          />
        </div>
      )}
      <nav className="flex-1 overflow-y-auto px-2 py-2" aria-label="Chats">
        {(chats ?? []).map((chat) => (
          <div
            key={chat.id}
            className={`group flex min-h-11 items-center gap-1 rounded-r-lg border-l-2 px-2 py-1.5 text-sm transition-[background-color,border-color,transform,box-shadow] duration-180 motion-reduce:transition-none ${
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
                  className="flex min-w-0 flex-1 items-center gap-2 truncate rounded-md px-1 py-1 text-left focus-visible:outline-2 focus-visible:outline-primary"
                  onClick={() => void navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
                >
                  {chat.pinned ? (
                    <Pin size={14} className="shrink-0 text-accent" fill="currentColor" aria-hidden="true" />
                  ) : (
                    <MessageSquare size={14} className="shrink-0 text-muted-foreground" aria-hidden="true" />
                  )}
                  <span className="truncate">{chat.title}</span>
                </button>
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
            <button
              type="button"
              aria-label={`Delete ${chat.title}`}
              onClick={() => void deleteChat.mutateAsync(chat.id)}
              className="rounded-md p-1.5 text-muted-foreground transition-[color,background-color] duration-180 hover:bg-danger-soft hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-danger motion-reduce:transition-none"
            >
              <Trash2 size={13} aria-hidden="true" />
            </button>
          </div>
        ))}
      </nav>
      <div className="flex items-center justify-between gap-2 border-t border-border px-3 py-3">
        <div className="flex items-center gap-1">
          {me.data?.role === 'admin' && (
            <button
              type="button"
              onClick={() => void navigate({ to: '/admin' })}
              className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-primary-soft hover:text-primary active:translate-y-px focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
            >
              <ShieldCheck size={14} aria-hidden="true" />
              Admin
            </button>
          )}
          <button
            type="button"
            onClick={() => void navigate({ to: '/sources' })}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-secondary-soft hover:text-secondary active:translate-y-px focus-visible:outline-2 focus-visible:outline-secondary motion-reduce:transition-none"
          >
            <Library size={14} aria-hidden="true" />
            Sources
          </button>
        </div>
        <div className="flex items-center gap-1">
          <ThemeToggle />
          <button
            type="button"
            aria-label="Sign out"
            onClick={() => void onLogout()}
            className="rounded-lg p-2 text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-danger-soft hover:text-danger active:translate-y-px focus-visible:outline-2 focus-visible:outline-danger motion-reduce:transition-none"
          >
            <LogOut size={14} aria-hidden="true" />
           </button>
         </div>
       </div>
        </aside>
      </>
    )
  }

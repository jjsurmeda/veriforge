import { useNavigate } from '@tanstack/react-router'
import { Fragment, useEffect, useMemo, useState, type ReactElement } from 'react'
import {
  Check,
  MessageSquare,
  MoreHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Pencil,
  Pin,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react'

import { useMe } from '../../auth/hooks/useMe'
import { IconButton } from '../../../components/ui/IconButton'
import { PanelError } from '../../../components/ui/PanelError'
import { PanelNote } from '../../../components/ui/PanelNote'
import {
  Menu,
  MenuContent,
  MenuItemWithIcon,
  MenuTrigger,
  TooltipContent,
  TooltipRoot,
  TooltipTrigger,
} from '../../../components/ui/primitives'
import { ProfileMenu } from '../../../components/ProfileMenu'
import { ThemeToggle } from '../../../components/ThemeToggle'
import { useChatList, useCreateChat, useDeleteChat, usePatchChat } from '../hooks/useChatList'

const SIDEBAR_STORAGE_KEY = 'veriforge-chat-sidebar-collapsed'

function readStorage(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback
  } catch {
    return fallback
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value)
  } catch {
    return
  }
}

function Tooltip({ label, children }: { label: string; children: ReactElement }) {
  return (
    <TooltipRoot>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </TooltipRoot>
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
  const { data: chats, isPending, isError, refetch } = useChatList()
  const { data: me } = useMe()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const patchChat = usePatchChat()
  const [collapsed, setCollapsed] = useState(() => readStorage(SIDEBAR_STORAGE_KEY, 'false') === 'true')
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const rail = collapsed && !mobileOpen

  useEffect(() => writeStorage(SIDEBAR_STORAGE_KEY, String(collapsed)), [collapsed])

  const filteredChats = useMemo(() => {
    const query = searchQuery.trim().toLowerCase()
    if (!query) return chats ?? []
    return (chats ?? []).filter((chat) => chat.title.toLowerCase().includes(query))
  }, [chats, searchQuery])
  const pinnedChats = filteredChats.filter((chat) => chat.pinned)
  const otherChats = filteredChats.filter((chat) => !chat.pinned)

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
      const chat = await createChat.mutateAsync()
      onMobileClose?.()
      void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
    } finally {
      setCreating(false)
    }
  }

  const toggleCollapsed = () => setCollapsed((value) => !value)

  const renderChatRow = (chat: NonNullable<typeof chats>[number]) => {
    const active = chat.id === currentChatId
    return (
      <Fragment key={chat.id}>
      <div
        className={`group relative flex min-h-10 items-center rounded-lg transition-[background-color,color] duration-150 ease-out ${
          rail ? 'justify-center px-1' : 'gap-0.5 px-1'
        } ${active ? 'bg-raised text-fg' : 'text-fg-muted hover:bg-raised-hover hover:text-fg'}`}
      >
        {editingChatId === chat.id ? (
          <div className="flex min-w-0 flex-1 items-center gap-1 px-1">
            <input
              aria-label={`Rename ${chat.title}`}
              value={titleDraft}
              onChange={(event) => setTitleDraft(event.currentTarget.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') void saveRename()
                if (event.key === 'Escape') setEditingChatId(null)
              }}
              className="min-w-0 flex-1 rounded-md border border-border bg-surface px-2 py-1.5 text-xs text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            />
            <button
              type="button"
              aria-label="Save rename"
              onClick={() => void saveRename()}
              className="icon-button size-7 text-fg"
            >
              <Check size={14} strokeWidth={1.75} aria-hidden="true" />
            </button>
          </div>
        ) : (
          <>
            <button
              type="button"
              aria-label={rail ? chat.title : undefined}
              title={rail ? chat.title : undefined}
              className={`flex min-w-0 items-center rounded-md text-left focus-visible:outline-2 focus-visible:outline-focus-ring ${rail ? 'justify-center p-2' : 'flex-1 gap-2 truncate px-2 py-1.5'}`}
              onClick={() => void navigate({ to: '/chat/$chatId', params: { chatId: chat.id } })}
            >
              {chat.pinned ? (
                <Pin size={14} strokeWidth={1.75} className="shrink-0 text-fg" fill="currentColor" aria-hidden="true" />
              ) : (
                <MessageSquare size={14} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />
              )}
              <span className={rail ? 'sr-only' : 'truncate'}>{chat.title}</span>
            </button>
            {!rail && (
              <>
                <button
                  type="button"
                  aria-label={`Rename ${chat.title}`}
                  onClick={() => beginRename(chat.id, chat.title)}
                  className="icon-button size-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                >
                  <Pencil size={13} strokeWidth={1.75} aria-hidden="true" />
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
                  className="icon-button size-7"
                >
                  <Pin size={13} strokeWidth={1.75} fill={chat.pinned ? 'currentColor' : 'none'} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${chat.title}`}
                  onClick={() => void deleteChat.mutateAsync(chat.id)}
                  className="icon-button size-7 hover:bg-raised hover:text-danger"
                >
                  <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
                </button>
                <Menu>
                  <MenuTrigger asChild><IconButton size={28} aria-label={`More actions for ${chat.title}`} className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"><MoreHorizontal size={14} strokeWidth={1.75} aria-hidden="true" /></IconButton></MenuTrigger>
                  <MenuContent side="right" align="start" className="w-40">
                    <MenuItemWithIcon onSelect={() => beginRename(chat.id, chat.title)}><Pencil size={13} strokeWidth={1.75} aria-hidden="true" />Rename</MenuItemWithIcon>
                    <MenuItemWithIcon onSelect={() => void patchChat.mutateAsync({ chatId: chat.id, patch: { pinned: !chat.pinned } })}><Pin size={13} strokeWidth={1.75} aria-hidden="true" />{chat.pinned ? 'Unpin' : 'Pin'}</MenuItemWithIcon>
                    <MenuItemWithIcon className="text-danger" onSelect={() => void deleteChat.mutateAsync(chat.id)}><Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />Delete</MenuItemWithIcon>
                  </MenuContent>
                </Menu>
              </>
            )}
          </>
        )}
        </div>
      </Fragment>
    )
  }

  return (
    <>
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close navigation"
          onClick={onMobileClose}
          className="fixed inset-0 z-40 bg-main/75 lg:hidden"
        />
      )}
      <aside
        aria-label="Chat navigation"
        className={`${mobileOpen ? 'fixed inset-y-0 left-0 z-50 flex w-[min(20rem,88vw)]' : 'hidden lg:flex'} ${collapsed ? 'lg:w-16' : 'lg:w-[280px]'} h-full shrink-0 flex-col border-r border-border bg-sidebar text-fg`}
      >
        <div className={`flex h-14 shrink-0 items-center border-b border-border ${rail ? 'justify-center px-2' : 'justify-between gap-2 px-4'}`}>
          <div className={`flex min-w-0 items-center ${rail ? 'justify-center' : 'gap-2.5'}`}>
            <span className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-border bg-surface text-fg">
              <MessageSquare size={17} strokeWidth={1.75} aria-hidden="true" />
            </span>
            {!rail && (
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold tracking-tight text-fg">Veriforge</p>
                <p className="truncate text-[0.62rem] text-fg-muted">Evidence workbench</p>
              </div>
            )}
          </div>
          {!rail && (
            <button type="button" aria-label="Close navigation panel" onClick={onMobileClose} className="icon-button size-8 lg:hidden">
              <X size={16} strokeWidth={1.75} aria-hidden="true" />
            </button>
          )}
          <button
            type="button"
            aria-label={collapsed ? 'Expand chat sidebar' : 'Collapse chat sidebar'}
            aria-pressed={collapsed}
            title={collapsed ? 'Expand chat sidebar' : 'Collapse chat sidebar'}
            onClick={toggleCollapsed}
            className="icon-button hidden size-8 lg:inline-flex"
          >
            {collapsed ? <PanelLeftOpen size={16} strokeWidth={1.75} aria-hidden="true" /> : <PanelLeftClose size={16} strokeWidth={1.75} aria-hidden="true" />}
          </button>
        </div>

        {rail ? (
          me?.role === 'admin' ? (
            <div className="flex flex-col items-center gap-2 border-b border-border px-1.5 py-2">
              <Tooltip label="Admin">
                <IconButton aria-label="Admin" onClick={() => void navigate({ to: '/admin' })}>
                  <ShieldCheck size={18} strokeWidth={1.75} aria-hidden="true" />
                </IconButton>
              </Tooltip>
            </div>
          ) : null
        ) : (
          <nav className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 py-2" aria-label="Sidebar">
            {searchOpen ? (
              <div className="mb-1">
                <label className="relative block">
                  <Search size={14} strokeWidth={1.75} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
                  <input
                    autoFocus
                    aria-label="Search chats"
                    value={searchQuery}
                    onChange={(event) => setSearchQuery(event.currentTarget.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        setSearchQuery('')
                        setSearchOpen(false)
                      }
                    }}
                    placeholder="Filter chats"
                    className="h-9 w-full rounded-lg border border-border bg-surface pl-8 pr-2 text-xs text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
                  />
                </label>
              </div>
            ) : (
              <div className="mb-1 flex items-center gap-1">
                <p className="min-w-0 flex-1 truncate px-2 text-[0.68rem] font-medium uppercase tracking-[0.12em] text-fg-subtle">
                  Chats
                </p>
                <Tooltip label="Search chats">
                  <IconButton aria-label="Search chats" onClick={() => setSearchOpen(true)}>
                    <Search size={15} strokeWidth={1.75} aria-hidden="true" />
                  </IconButton>
                </Tooltip>
                <Tooltip label="New chat">
                  <IconButton aria-label="New chat" disabled={creating} onClick={() => void onNewChat()}>
                    <Plus size={16} strokeWidth={1.75} aria-hidden="true" />
                  </IconButton>
                </Tooltip>
              </div>
            )}

            {pinnedChats.length > 0 && (
              <div className="mb-2">
                <p className="px-2 pb-1 text-[0.62rem] text-fg-subtle">Pinned</p>
                {pinnedChats.map(renderChatRow)}
              </div>
            )}
            {otherChats.map(renderChatRow)}
            {/* Item 6: "No chats yet." on a failed read is a claim about the
                account, not about the request. Same for the first paint. */}
            {isPending ? (
              <div className="px-1">
                <PanelNote>Reading your chats…</PanelNote>
              </div>
            ) : isError ? (
              <div className="px-1">
                <PanelError
                  compact
                  title="Your chats could not be read."
                  hint="Nothing was changed. Try again in a moment."
                  action={
                    <button
                      type="button"
                      onClick={() => void refetch()}
                      className="pressable min-h-8 rounded-lg border border-border bg-surface px-2.5 text-2xs text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring"
                    >
                      Try again
                    </button>
                  }
                />
              </div>
            ) : filteredChats.length === 0 ? (
              <p className="px-2 py-3 text-xs text-fg-muted">{searchQuery ? 'No chats match.' : 'No chats yet.'}</p>
            ) : null}

            {me?.role === 'admin' ? (
              <button
                type="button"
                onClick={() => void navigate({ to: '/admin' })}
                className="mt-2 flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-xs text-fg-muted transition-colors duration-150 hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
              >
                <ShieldCheck size={15} strokeWidth={1.75} aria-hidden="true" />
                Admin
              </button>
            ) : (
              // The demo role gets the decision layer, not Admin: the page is
              // read-only and the API refuses it every write (item 3), so
              // calling it "Admin" would promise a control room it cannot enter.
              <button
                type="button"
                onClick={() => void navigate({ to: '/decision-layer' })}
                className="mt-2 flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-xs text-fg-muted transition-colors duration-150 hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
              >
                <ShieldCheck size={15} strokeWidth={1.75} aria-hidden="true" />
                Decision layer
              </button>
            )}
          </nav>
        )}

        <div className={`flex items-center gap-1 border-t border-border p-2 ${rail ? 'flex-col' : 'justify-between'}`}>
          <ProfileMenu side={rail ? 'right' : 'top'} align="start" collapsed={rail} />
          {!rail && <ThemeToggle />}
        </div>
      </aside>
    </>
  )
}

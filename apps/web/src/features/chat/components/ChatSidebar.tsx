import { useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  ChevronDown,
  Library,
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
import { useCollections } from '../../sources/hooks/useCollections'
import { IconButton } from '../../../components/ui/IconButton'
import { Menu, MenuContent, MenuItemWithIcon, MenuTrigger } from '../../../components/ui/primitives'
import { ProfileMenu, QuotaBadge } from '../../../components/ProfileMenu'
import { CollectionPicker } from './CollectionPicker'
import { useChatList, useCreateChat, useDeleteChat, usePatchChat } from '../hooks/useChatList'

const SIDEBAR_STORAGE_KEY = 'veriforge-chat-sidebar-collapsed'
const SOURCES_SECTION_STORAGE_KEY = 'veriforge-chat-sources-collapsed'
const CHATS_SECTION_STORAGE_KEY = 'veriforge-chat-chats-collapsed'

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
  const { data: me } = useMe()
  const createChat = useCreateChat()
  const deleteChat = useDeleteChat()
  const patchChat = usePatchChat()
  const collections = useCollections()
  const [collapsed, setCollapsed] = useState(() => readStorage(SIDEBAR_STORAGE_KEY, 'false') === 'true')
  const [sourcesCollapsed, setSourcesCollapsed] = useState(
    () => readStorage(SOURCES_SECTION_STORAGE_KEY, 'false') === 'true',
  )
  const [chatsCollapsed, setChatsCollapsed] = useState(
    () => readStorage(CHATS_SECTION_STORAGE_KEY, 'false') === 'true',
  )
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  const [creating, setCreating] = useState(false)
  const [newChatCollectionIds, setNewChatCollectionIds] = useState<string[]>([])
  const [editingChatId, setEditingChatId] = useState<string | null>(null)
  const [titleDraft, setTitleDraft] = useState('')
  const rail = collapsed && !mobileOpen

  useEffect(() => writeStorage(SIDEBAR_STORAGE_KEY, String(collapsed)), [collapsed])
  useEffect(() => writeStorage(SOURCES_SECTION_STORAGE_KEY, String(sourcesCollapsed)), [sourcesCollapsed])
  useEffect(() => writeStorage(CHATS_SECTION_STORAGE_KEY, String(chatsCollapsed)), [chatsCollapsed])

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
      const chat = await createChat.mutateAsync({ collectionIds: newChatCollectionIds })
      onMobileClose?.()
      void navigate({ to: '/chat/$chatId', params: { chatId: chat!.id } })
    } finally {
      setCreating(false)
    }
  }

  const navigateToSources = () => {
    onMobileClose?.()
    void navigate({ to: '/sources' })
  }

  const toggleCollapsed = () => setCollapsed((value) => !value)

  const renderChatRow = (chat: NonNullable<typeof chats>[number]) => {
    const active = chat.id === currentChatId
    return (
      <div
        key={chat.id}
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
            <div className="flex items-center gap-0.5">
              <button type="button" aria-label="Search chats" title="Search chats" onClick={() => setSearchOpen((value) => !value)} className="icon-button size-8">
                <Search size={16} strokeWidth={1.75} aria-hidden="true" />
              </button>
              <button type="button" aria-label="Close navigation panel" onClick={onMobileClose} className="icon-button size-8 lg:hidden">
                <X size={16} strokeWidth={1.75} aria-hidden="true" />
              </button>
            </div>
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

        <div className={`border-b border-border px-2 py-2 ${rail ? 'flex justify-center' : ''}`}>
          <button type="button" aria-label="New chat" onClick={() => void onNewChat()} disabled={creating} className={`pressable flex min-h-10 w-full items-center rounded-lg text-sm font-medium ${rail ? 'justify-center px-2' : 'gap-2.5 px-2.5'} ${rail ? 'text-fg-muted hover:bg-raised-hover hover:text-fg' : 'text-fg hover:bg-raised-hover'} disabled:cursor-not-allowed disabled:opacity-50`}>
            <span className={`flex size-6 shrink-0 items-center justify-center rounded-full border border-border ${rail ? 'bg-surface' : 'bg-raised text-fg'}`}>
              <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
            </span>
            {!rail && <span>New chat</span>}
          </button>
          <button type="button" aria-label="Sources" title="Sources" onClick={navigateToSources} className={`pressable mt-1 flex min-h-10 w-full items-center rounded-lg text-sm ${rail ? 'justify-center px-2' : 'gap-2.5 px-2.5'} text-fg-muted hover:bg-raised-hover hover:text-fg`}>
            <Library size={18} strokeWidth={1.75} aria-hidden="true" />
            {!rail && <span>Sources</span>}
          </button>
          {me?.role === 'admin' && (
            <button type="button" aria-label="Admin" title="Admin" onClick={() => void navigate({ to: '/admin' })} className={`pressable mt-1 flex min-h-10 w-full items-center rounded-lg text-sm ${rail ? 'justify-center px-2' : 'gap-2.5 px-2.5'} text-fg-muted hover:bg-raised-hover hover:text-fg`}>
              <ShieldCheck size={18} strokeWidth={1.75} aria-hidden="true" />
              {!rail && <span>Admin</span>}
            </button>
          )}
        </div>

        {!rail && searchOpen && (
          <div className="border-b border-border px-3 py-2">
            <label className="relative block">
              <Search size={14} strokeWidth={1.75} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-muted" aria-hidden="true" />
              <input aria-label="Search chats" value={searchQuery} onChange={(event) => setSearchQuery(event.currentTarget.value)} placeholder="Filter chats" className="h-9 w-full rounded-lg border border-border bg-surface pl-8 pr-2 text-xs text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring" />
            </label>
          </div>
        )}

        {!rail && (
          <section className="border-b border-border px-3 py-3" aria-labelledby="sidebar-sources-heading">
            <button type="button" aria-expanded={!sourcesCollapsed} onClick={() => setSourcesCollapsed((value) => !value)} className="flex min-h-8 w-full items-center justify-between text-left text-[0.68rem] font-medium uppercase tracking-[0.12em] text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">
              <span id="sidebar-sources-heading">Sources</span>
              <ChevronDown size={14} strokeWidth={1.75} className={`transition-transform duration-150 ${sourcesCollapsed ? '-rotate-90' : ''}`} aria-hidden="true" />
            </button>
            {!sourcesCollapsed && (
              <div className="mt-1 space-y-0.5">
                {(collections.data ?? []).map((collection) => (
                  <button key={collection.id} type="button" onClick={navigateToSources} className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-sm text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">
                    <Library size={14} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
                    <span className="min-w-0 flex-1 truncate">{collection.name}</span>
                    <span className="font-mono text-[0.65rem] tabular-nums text-fg-muted">{collection.document_count}</span>
                  </button>
                ))}
                {(collections.data ?? []).length === 0 && (
                  <>
                    <p className="px-2 py-2 text-xs text-fg-muted">No sources yet</p>
                    <button type="button" onClick={navigateToSources} className="flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-xs text-fg hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring">
                      <Plus size={14} strokeWidth={1.75} aria-hidden="true" /> Add source
                    </button>
                  </>
                )}
              </div>
            )}
          </section>
        )}

        {currentChatId === null && !rail && (
          <div className="border-b border-border px-3 py-3">
            <CollectionPicker collections={collections.data ?? []} value={newChatCollectionIds} onChange={setNewChatCollectionIds} disabled={creating} />
          </div>
        )}

        <nav className={`min-h-0 flex-1 overflow-y-auto ${rail ? 'px-1.5 py-2' : 'px-2 py-2'}`} aria-label="Chats">
          {!rail && (
            <button type="button" aria-expanded={!chatsCollapsed} onClick={() => setChatsCollapsed((value) => !value)} className="mb-1 flex min-h-8 w-full items-center justify-between px-2 text-left text-[0.68rem] font-medium uppercase tracking-[0.12em] text-fg-subtle hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring">
              <span>Chats</span>
              <ChevronDown size={14} strokeWidth={1.75} className={`transition-transform duration-150 ${chatsCollapsed ? '-rotate-90' : ''}`} aria-hidden="true" />
            </button>
          )}
          {!chatsCollapsed && pinnedChats.length > 0 && (
            <div className="mb-2">
              {!rail && <p className="px-2 pb-1 text-[0.62rem] text-fg-subtle">Pinned</p>}
              {pinnedChats.map(renderChatRow)}
            </div>
          )}
          {!chatsCollapsed && otherChats.map(renderChatRow)}
          {!chatsCollapsed && filteredChats.length === 0 && (
            <p className="px-2 py-3 text-xs text-fg-muted">{searchQuery ? 'No chats match.' : 'No chats yet.'}</p>
          )}
        </nav>

        <div className={`border-t border-border p-2 ${rail ? 'flex flex-col items-center gap-2' : 'space-y-2'}`}>
          <QuotaBadge side={rail ? 'right' : 'top'} align={rail ? 'start' : 'start'} className={rail ? 'mx-auto' : 'mx-auto w-fit'} />
          <ProfileMenu side={rail ? 'right' : 'top'} align="start" collapsed={rail} />
        </div>
      </aside>
    </>
  )
}

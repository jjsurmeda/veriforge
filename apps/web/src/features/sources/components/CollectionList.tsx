import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, FolderOpen, Plus, X } from 'lucide-react'

import type { CollectionOut } from '../../../generated/types.gen'

export function CollectionList({ collections, selectedId, onSelect, onCreate, creating, mobileOpen = false, onMobileClose }: { collections: CollectionOut[]; selectedId: string | null; onSelect: (collectionId: string) => void; onCreate: (name: string) => Promise<unknown>; creating: boolean; mobileOpen?: boolean; onMobileClose?: () => void }) {
  const [name, setName] = useState('')
  const navigate = useNavigate()
  const submit = async () => {
    const trimmed = name.trim()
    if (!trimmed) return
    await onCreate(trimmed)
    setName('')
  }
  return (
    <>
      {mobileOpen && <button type="button" aria-label="Close source navigation" onClick={onMobileClose} className="fixed inset-0 z-40 bg-main/75 lg:hidden" />}
      <aside className={`${mobileOpen ? 'fixed inset-y-0 left-0 z-50 flex w-[min(20rem,88vw)]' : 'hidden lg:flex lg:w-[280px]'} h-full shrink-0 flex-col border-r border-border bg-sidebar text-fg`}>
        <div className="flex h-14 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-2.5"><span className="flex size-8 items-center justify-center rounded-lg border border-border bg-surface text-fg"><FolderOpen size={17} strokeWidth={1.75} aria-hidden="true" /></span><div><p className="text-sm font-semibold tracking-tight text-fg">Sources</p><p className="text-[0.62rem] text-fg-muted">Evidence library</p></div></div>
          <button type="button" aria-label="Close source navigation panel" onClick={onMobileClose} className="icon-button size-8 lg:hidden"><X size={16} strokeWidth={1.75} aria-hidden="true" /></button>
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Collections">
          {collections.map((collection) => <button key={collection.id} type="button" onClick={() => { onSelect(collection.id); onMobileClose?.() }} className={`group flex min-h-10 w-full items-center justify-between gap-2 rounded-lg px-2.5 text-left text-sm transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring ${collection.id === selectedId ? 'bg-raised text-fg' : 'text-fg-muted hover:bg-raised-hover hover:text-fg'}`}><span className="min-w-0 flex-1 truncate">{collection.name}{collection.visibility === 'shared' && <span className="ml-1 text-xs text-fg-muted">(shared)</span>}</span><span className="shrink-0 rounded-full bg-surface px-1.5 py-0.5 font-mono text-[0.62rem] tabular-nums text-fg-muted">{collection.document_count}</span></button>)}
          {collections.length === 0 && <p className="px-2 py-3 text-xs text-fg-muted">No collections yet.</p>}
        </nav>
        <div className="border-t border-border p-3">
          <button type="button" onClick={() => void navigate({ to: '/' })} className="mb-2 flex min-h-9 w-full items-center gap-2 rounded-lg px-2 text-left text-xs text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"><ArrowLeft size={14} strokeWidth={1.75} aria-hidden="true" />Chats</button>
          <div className="flex gap-2"><input value={name} onChange={(event) => setName(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === 'Enter') void submit() }} placeholder="New collection" aria-label="New collection name" className="h-10 min-w-0 flex-1 rounded-lg border border-border bg-surface px-2.5 text-sm text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-focus-ring" /><button type="button" disabled={creating || !name.trim()} onClick={() => void submit()} className="pressable inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-fg-strong px-3 text-xs font-semibold text-on-strong disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-focus-ring"><Plus size={14} strokeWidth={1.75} aria-hidden="true" />Create</button></div>
        </div>
      </aside>
    </>
  )
}

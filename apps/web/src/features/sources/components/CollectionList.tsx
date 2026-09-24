import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { ArrowLeft, FolderOpen, Plus, X } from 'lucide-react'

import type { CollectionOut } from '../../../generated/types.gen'

export function CollectionList({
  collections,
  selectedId,
  onSelect,
  onCreate,
  creating,
  mobileOpen = false,
  onMobileClose,
}: {
  collections: CollectionOut[]
  selectedId: string | null
  onSelect: (collectionId: string) => void
  onCreate: (name: string) => Promise<unknown>
  creating: boolean
  mobileOpen?: boolean
  onMobileClose?: () => void
}) {
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
      {mobileOpen && (
        <button
          type="button"
          aria-label="Close source navigation"
          onClick={onMobileClose}
           className="fixed bottom-0 left-0 right-0 top-14 z-40 bg-background/70 backdrop-blur-sm lg:hidden"
        />
      )}
      <aside
        className={`${
           mobileOpen
             ? 'fixed bottom-0 left-0 top-14 z-50 flex w-[min(20rem,85vw)]'
             : 'hidden lg:flex lg:w-72'
        } h-full shrink-0 flex-col border-r border-border bg-surface shadow-lg lg:shadow-sm`}
      >
      <div className="flex items-center justify-between border-b border-border px-4 py-4">
        <div className="flex items-center gap-2.5">
          <span className="flex size-9 items-center justify-center rounded-xl bg-secondary-soft text-secondary shadow-sm">
            <FolderOpen size={18} aria-hidden="true" />
          </span>
          <div>
            <span className="block font-display text-base font-semibold tracking-tight text-foreground">Sources</span>
            <span className="block text-[0.65rem] text-muted-foreground">Evidence library</span>
          </div>
        </div>
         <div className="flex items-center gap-1">
           <button
            type="button"
            aria-label="Close source navigation panel"
            onClick={onMobileClose}
            className="rounded-lg p-2 text-muted-foreground transition-colors duration-180 hover:bg-surface-muted hover:text-foreground focus-visible:outline-2 focus-visible:outline-primary lg:hidden"
          >
            <X size={16} aria-hidden="true" />
          </button>
        </div>
      </div>
      <nav className="flex-1 overflow-y-auto py-1" aria-label="Collections">
        {collections.map((collection) => (
          <button
            key={collection.id}
            type="button"
            onClick={() => {
              onSelect(collection.id)
              onMobileClose?.()
            }}
            className={`group flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-left text-sm transition-[background-color,color,transform,box-shadow] duration-180 focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none ${
              collection.id === selectedId
                ? 'bg-primary-soft text-foreground shadow-sm'
                : 'text-muted-foreground hover:-translate-y-px hover:bg-surface-muted hover:text-foreground hover:shadow-sm'
            }`}
          >
            <span className="min-w-0 flex-1 truncate">
              {collection.name}
              {collection.visibility === 'shared' && (
                <span className="ml-1 text-xs text-muted-foreground">(shared)</span>
              )}
            </span>
            <span className="shrink-0 rounded-full bg-surface-muted px-1.5 py-0.5 font-mono text-[0.65rem] text-muted-foreground">{collection.document_count}</span>
          </button>
        ))}
        {collections.length === 0 && (
          <p className="px-4 py-3 text-xs text-muted-foreground">No collections yet.</p>
        )}
      </nav>
      <div className="border-t border-border bg-surface-muted/50 p-3">
        <div className="mb-2">
          <button
            type="button"
            onClick={() => void navigate({ to: '/' })}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-primary-soft hover:text-primary active:translate-y-px focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            <ArrowLeft size={14} aria-hidden="true" />
            Chats
          </button>
        </div>
        <div className="flex gap-2">
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') void submit()
            }}
            placeholder="New collection"
            aria-label="New collection name"
            className="min-w-0 flex-1 rounded-lg border border-border bg-background px-2.5 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus-visible:outline-2 focus-visible:outline-primary"
          />
          <button
            type="button"
            disabled={creating || !name.trim()}
            onClick={() => void submit()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-on-primary transition-[background-color,transform,box-shadow] duration-180 hover:-translate-y-0.5 hover:bg-primary-strong hover:shadow-sm active:translate-y-0 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transform-none motion-reduce:transition-none"
          >
            <Plus size={14} aria-hidden="true" />
            Create
          </button>
        </div>
      </div>
        </aside>
      </>
    )
  }

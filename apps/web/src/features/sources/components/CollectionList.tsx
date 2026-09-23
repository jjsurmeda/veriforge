import { useState } from 'react'
import { useNavigate } from '@tanstack/react-router'

import type { CollectionOut } from '../../../generated/types.gen'

export function CollectionList({
  collections,
  selectedId,
  onSelect,
  onCreate,
  creating,
}: {
  collections: CollectionOut[]
  selectedId: string | null
  onSelect: (collectionId: string) => void
  onCreate: (name: string) => Promise<unknown>
  creating: boolean
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
    <aside className="flex h-full w-64 shrink-0 flex-col border-r border-mist bg-graphite">
      <div className="border-b border-mist px-4 py-3">
        <span className="font-display text-lg tracking-tight text-paper">Sources</span>
      </div>
      <nav className="flex-1 overflow-y-auto py-1" aria-label="Collections">
        {collections.map((collection) => (
          <button
            key={collection.id}
            type="button"
            onClick={() => onSelect(collection.id)}
            className={`flex w-full items-center justify-between gap-2 px-4 py-2 text-left text-sm focus-visible:outline-2 focus-visible:outline-ember ${
              collection.id === selectedId
                ? 'bg-mist/60 text-paper'
                : 'text-paper/70 hover:bg-mist/30'
            }`}
          >
            <span className="min-w-0 flex-1 truncate">
              {collection.name}
              {collection.visibility === 'shared' && (
                <span className="ml-1 text-xs text-paper/40">(shared)</span>
              )}
            </span>
            <span className="shrink-0 text-xs text-paper/40">{collection.document_count}</span>
          </button>
        ))}
        {collections.length === 0 && (
          <p className="px-4 py-2 text-xs text-paper/40">No collections yet.</p>
        )}
      </nav>
      <div className="border-t border-mist p-3">
        <div className="mb-2">
          <button
            type="button"
            onClick={() => void navigate({ to: '/' })}
            className="text-xs text-paper/50 hover:text-paper focus-visible:outline-2 focus-visible:outline-ember"
          >
            ← Chats
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
            className="min-w-0 flex-1 rounded border border-mist bg-ink px-2 py-1 text-sm text-paper placeholder:text-paper/30 focus-visible:outline-2 focus-visible:outline-ember"
          />
          <button
            type="button"
            disabled={creating || !name.trim()}
            onClick={() => void submit()}
            className="shrink-0 rounded border border-mist px-2.5 py-1 text-xs text-paper hover:border-paper/50 focus-visible:outline-2 focus-visible:outline-ember disabled:opacity-50"
          >
            Create
          </button>
        </div>
      </div>
    </aside>
  )
}

import { FolderOpen } from 'lucide-react'

import type { CollectionOut } from '../../../generated/types.gen'

interface Props {
  collections: CollectionOut[]
  value: string[]
  onChange: (collectionIds: string[]) => void
  disabled?: boolean
}

export function CollectionPicker({ collections, value, onChange, disabled = false }: Props) {
  const selectedNames = collections
    .filter((collection) => value.includes(collection.id))
    .map((collection) => collection.name)

  const toggle = (collectionId: string, checked: boolean) => {
    if (checked) {
      onChange([...value, collectionId])
      return
    }
    onChange(value.filter((id) => id !== collectionId))
  }

  return (
    <fieldset className="min-w-0 rounded-xl border border-border bg-surface p-2.5" disabled={disabled}>
      <legend className="flex items-center gap-1.5 px-1 text-[0.65rem] font-medium uppercase tracking-[0.1em] text-fg-muted">
        <FolderOpen size={13} strokeWidth={1.75} aria-hidden="true" />
        Documents
      </legend>
      <div className="mt-1 space-y-0.5">
        {collections.map((collection) => (
          <label
            key={collection.id}
            className="flex min-h-9 min-w-0 cursor-pointer items-center gap-2 rounded-lg px-1.5 py-1.5 text-xs text-fg transition-colors duration-150 ease-out hover:bg-raised-hover focus-within:bg-raised-hover"
          >
            <input
              type="checkbox"
              checked={value.includes(collection.id)}
              onChange={(event) => toggle(collection.id, event.currentTarget.checked)}
              className="size-3.5 shrink-0 cursor-pointer appearance-none rounded border border-border-strong bg-surface checked:border-fg-strong checked:bg-fg-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
            />
            <span className="min-w-0 flex-1 truncate">
              {collection.name}
              {collection.visibility === 'shared' && <span className="ml-1 text-fg-muted">(shared)</span>}
            </span>
            <span className="font-mono text-[0.65rem] tabular-nums text-fg-muted">{collection.document_count}</span>
          </label>
        ))}
        {collections.length === 0 && (
          <p className="rounded-lg border border-dashed border-border-strong px-2 py-2 text-xs text-fg-muted">No documents yet.</p>
        )}
      </div>
      {selectedNames.length > 0 && (
        <p className="mt-2 truncate border-t border-border pt-2 text-[0.65rem] text-fg-muted">{selectedNames.join(', ')}</p>
      )}
    </fieldset>
  )
}

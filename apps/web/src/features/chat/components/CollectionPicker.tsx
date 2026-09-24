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
    <fieldset className="min-w-0 rounded-lg border border-border bg-surface-muted p-3" disabled={disabled}>
      <legend className="flex items-center gap-1.5 px-1 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-muted-foreground">
        <FolderOpen size={13} aria-hidden="true" />
        Documents
      </legend>
      <div className="mt-1 space-y-1">
        {collections.map((collection) => (
          <label
            key={collection.id}
            className="flex min-w-0 cursor-pointer items-center gap-2 rounded-md px-1.5 py-1.5 text-xs text-foreground transition-[background-color,color] duration-180 hover:bg-primary-soft focus-within:bg-primary-soft motion-reduce:transition-none"
          >
            <input
              type="checkbox"
              checked={value.includes(collection.id)}
              onChange={(event) => toggle(collection.id, event.currentTarget.checked)}
              className="size-3.5 shrink-0 cursor-pointer accent-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            />
            <span className="min-w-0 flex-1 truncate">
              {collection.name}
              {collection.visibility === 'shared' && (
                <span className="ml-1 text-muted-foreground">(shared)</span>
              )}
            </span>
            <span className="font-mono text-[0.65rem] text-muted-foreground">
              {collection.document_count}
            </span>
          </label>
        ))}
        {collections.length === 0 && (
          <p className="rounded-md border border-dashed border-border-strong px-2 py-2 text-xs text-muted-foreground">
            No documents yet.
          </p>
        )}
      </div>
      {selectedNames.length > 0 && (
        <p className="mt-2 truncate border-t border-border/70 pt-2 text-[0.65rem] text-muted-foreground">
          {selectedNames.join(', ')}
        </p>
      )}
    </fieldset>
  )
}

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
    <fieldset className="min-w-0 rounded-sm border border-mist/60 bg-ink/20 p-2.5" disabled={disabled}>
      <legend className="px-1 font-mono text-[0.65rem] uppercase tracking-[0.12em] text-paper/50">
        Documents
      </legend>
      <div className="mt-1 space-y-0.5">
        {collections.map((collection) => (
          <label
            key={collection.id}
            className="flex min-w-0 cursor-pointer items-center gap-2 rounded-sm px-1 py-1 text-xs text-paper/70 transition-colors duration-150 hover:bg-mist/30 focus-within:bg-mist/30 motion-reduce:transition-none"
          >
            <input
              type="checkbox"
              checked={value.includes(collection.id)}
              onChange={(event) => toggle(collection.id, event.currentTarget.checked)}
              className="h-3.5 w-3.5 shrink-0 cursor-pointer accent-ember focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-2 focus-visible:ring-offset-ink"
            />
            <span className="min-w-0 flex-1 truncate">
              {collection.name}
              {collection.visibility === 'shared' && (
                <span className="ml-1 text-paper/40">(shared)</span>
              )}
            </span>
            <span className="font-mono text-[0.65rem] text-paper/40">
              {collection.document_count}
            </span>
          </label>
        ))}
        {collections.length === 0 && (
          <p className="rounded-sm border border-dashed border-mist/60 px-2 py-2 text-xs text-paper/50">
            No documents yet.
          </p>
        )}
      </div>
      {selectedNames.length > 0 && (
        <p className="mt-2 truncate border-t border-mist/40 pt-2 text-[0.65rem] text-paper/50">
          {selectedNames.join(', ')}
        </p>
      )}
    </fieldset>
  )
}

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
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-paper/50">
        Documents
      </legend>
      <div className="mt-1 space-y-1">
        {collections.map((collection) => (
          <label
            key={collection.id}
            className="flex min-w-0 items-center gap-2 text-xs text-paper/70"
          >
            <input
              type="checkbox"
              checked={value.includes(collection.id)}
              onChange={(event) => toggle(collection.id, event.currentTarget.checked)}
              className="accent-ember"
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
        {collections.length === 0 && <p className="text-xs text-paper/40">No documents yet.</p>}
      </div>
      {selectedNames.length > 0 && (
        <p className="mt-2 truncate text-[0.65rem] text-paper/40">{selectedNames.join(', ')}</p>
      )}
    </fieldset>
  )
}

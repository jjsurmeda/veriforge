export type RunSource = 'auto' | 'upload' | 'web' | 'both'

interface Props {
  value: RunSource
  disabled?: boolean
  onChange: (source: RunSource) => void
}

const SOURCES: { value: RunSource; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'upload', label: 'Upload' },
  { value: 'web', label: 'Web' },
  { value: 'both', label: 'Both' },
]

export function SourcePicker({ value, disabled, onChange }: Props) {
  return (
    <label className="flex items-center gap-2 text-xs text-paper/60">
      <span>Source</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value as RunSource)}
        className="rounded border border-mist bg-ink px-2 py-1 text-xs text-paper focus-visible:outline-2 focus-visible:outline-ember disabled:opacity-50"
      >
        {SOURCES.map((source) => (
          <option key={source.value} value={source.value}>
            {source.label}
          </option>
        ))}
      </select>
    </label>
  )
}

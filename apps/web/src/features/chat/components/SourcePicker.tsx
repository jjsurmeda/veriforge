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
    <label className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-paper/50">
      <span>Source</span>
      <span className="relative">
        <select
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as RunSource)}
          className="h-8 min-w-[5.25rem] cursor-pointer appearance-none rounded-sm border border-mist bg-graphite py-1 pl-2.5 pr-7 font-mono text-xs normal-case tracking-normal text-paper transition-colors duration-150 hover:border-paper/50 focus-visible:border-ember focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
        >
          {SOURCES.map((source) => (
            <option key={source.value} value={source.value}>
              {source.label}
            </option>
          ))}
        </select>
        <span
          aria-hidden="true"
          className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-[0.65rem] text-paper/45"
        >
          ⌄
        </span>
      </span>
    </label>
  )
}

import { ChevronDown, Library } from 'lucide-react'

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
    <label className="relative flex min-w-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="sr-only">Source</span>
      <Library size={14} strokeWidth={1.75} className="shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="relative min-w-0 flex-1">
        <select
          aria-label="Run source"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as RunSource)}
          className="h-8 w-full min-w-0 cursor-pointer appearance-none rounded-lg border-0 bg-transparent px-1 pr-5 text-xs font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {SOURCES.map((source) => (
            <option key={source.value} value={source.value}>
              {source.label}
            </option>
          ))}
        </select>
        <ChevronDown size={13} strokeWidth={1.75} aria-hidden="true" className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-muted-foreground" />
      </span>
    </label>
  )
}

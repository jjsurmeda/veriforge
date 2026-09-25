import { ChevronDown, Zap } from 'lucide-react'

export type RunMode = 'auto' | 'fast' | 'deep'

interface Props {
  value: RunMode
  disabled?: boolean
  onChange: (mode: RunMode) => void
}

const MODES: { value: RunMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'fast', label: 'Fast' },
  { value: 'deep', label: 'Deep' },
]

export function ModePicker({ value, disabled, onChange }: Props) {
  return (
    <label className="relative flex min-w-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="sr-only">Mode</span>
      <Zap size={14} strokeWidth={1.75} className="shrink-0 text-accent" aria-hidden="true" />
      <span className="relative min-w-0 flex-1">
        <select
          aria-label="Run mode"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as RunMode)}
          className="h-8 w-full min-w-0 cursor-pointer appearance-none rounded-lg border-0 bg-transparent px-1 pr-5 text-xs font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.label}
            </option>
          ))}
        </select>
        <ChevronDown size={13} strokeWidth={1.75} aria-hidden="true" className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-muted-foreground" />
      </span>
    </label>
  )
}

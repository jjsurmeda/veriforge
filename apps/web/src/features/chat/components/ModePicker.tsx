import { ChevronDown } from 'lucide-react'

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
    <label className="flex min-w-0 items-center gap-2 text-xs font-medium text-muted-foreground">
      <span className="shrink-0 font-mono text-[0.65rem] uppercase tracking-[0.1em]">Mode</span>
      <span className="relative min-w-0 flex-1">
        <select
          aria-label="Run mode"
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as RunMode)}
          className="h-9 w-full min-w-0 cursor-pointer appearance-none rounded-lg border border-border bg-surface px-3 pr-8 text-sm text-foreground transition-[border-color,box-shadow] duration-180 hover:border-primary/50 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
        >
          {MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.label}
            </option>
          ))}
        </select>
        <ChevronDown
          size={14}
          aria-hidden="true"
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
        />
      </span>
    </label>
  )
}

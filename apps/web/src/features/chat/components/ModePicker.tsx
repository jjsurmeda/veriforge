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
    <label className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-paper/50">
      <span>Mode</span>
      <span className="relative">
        <select
          value={value}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value as RunMode)}
          className="h-8 min-w-[5.25rem] cursor-pointer appearance-none rounded-sm border border-mist bg-graphite py-1 pl-2.5 pr-7 font-mono text-xs normal-case tracking-normal text-paper transition-colors duration-150 hover:border-paper/50 focus-visible:border-ember focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
        >
          {MODES.map((mode) => (
            <option key={mode.value} value={mode.value}>
              {mode.label}
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

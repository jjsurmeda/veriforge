export type RunMode = 'auto' | 'fast' | 'deep'

interface Props {
  value: RunMode
  disabled?: boolean
  onChange: (mode: RunMode) => void
  onDeepBlocked?: () => void
}

const MODES: { value: RunMode; label: string }[] = [
  { value: 'auto', label: 'Auto' },
  { value: 'fast', label: 'Fast' },
  { value: 'deep', label: 'Deep' },
]

export function ModePicker({ value, disabled, onChange, onDeepBlocked }: Props) {
  return (
    <label className="flex items-center gap-2 text-xs text-paper/60">
      <span>Mode</span>
      <select
        value={value}
        disabled={disabled}
        onChange={(event) => {
          const next = event.target.value as RunMode
          if (next === 'deep' && onDeepBlocked) onDeepBlocked()
          onChange(next)
        }}
        className="rounded border border-mist bg-ink px-2 py-1 text-xs text-paper focus-visible:outline-2 focus-visible:outline-ember disabled:opacity-50"
      >
        {MODES.map((mode) => (
          <option key={mode.value} value={mode.value}>
            {mode.label}
          </option>
        ))}
      </select>
    </label>
  )
}

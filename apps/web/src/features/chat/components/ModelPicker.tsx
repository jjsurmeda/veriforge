import { ChevronDown } from 'lucide-react'

import { useModels } from '../hooks/useModels'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  return (
    <label className="flex min-w-0 items-center gap-2 text-xs font-medium text-muted-foreground">
      <span className="shrink-0 font-mono text-[0.65rem] uppercase tracking-[0.1em]">Model</span>
      <span className="relative min-w-0 flex-1">
        <select
          aria-label="Model"
          value={value ?? ''}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="h-9 w-full min-w-0 cursor-pointer appearance-none rounded-lg border border-border bg-surface px-3 pr-8 text-sm text-foreground transition-[border-color,box-shadow] duration-180 hover:border-primary/50 focus-visible:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30 disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
        >
          {(models ?? []).map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.model_id}
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

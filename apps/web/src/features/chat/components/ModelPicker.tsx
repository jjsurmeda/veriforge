import { Bot, ChevronDown } from 'lucide-react'

import { useModels } from '../hooks/useModels'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  return (
    <label className="relative flex min-w-0 items-center gap-1.5 text-xs font-medium text-muted-foreground">
      <span className="sr-only">Model</span>
      <Bot size={14} strokeWidth={1.75} className="shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="relative min-w-0 flex-1">
        <select
          aria-label="Model"
          value={value ?? ''}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="h-8 w-full min-w-0 cursor-pointer appearance-none rounded-lg border-0 bg-transparent px-1 pr-5 text-xs font-medium text-foreground outline-none focus-visible:ring-2 focus-visible:ring-accent/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {(models ?? []).map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.model_id}
            </option>
          ))}
        </select>
        <ChevronDown size={13} strokeWidth={1.75} aria-hidden="true" className="pointer-events-none absolute right-0 top-1/2 -translate-y-1/2 text-muted-foreground" />
      </span>
    </label>
  )
}

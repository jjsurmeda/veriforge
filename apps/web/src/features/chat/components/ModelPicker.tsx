import { useModels } from '../hooks/useModels'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  return (
    <label className="flex items-center gap-2 font-mono text-[0.65rem] uppercase tracking-[0.08em] text-paper/50">
      <span>model</span>
      <span className="relative">
        <select
          value={value ?? ''}
          disabled={disabled}
          onChange={(event) => onChange(event.target.value)}
          className="h-8 max-w-[15rem] cursor-pointer appearance-none rounded-sm border border-mist bg-graphite py-1 pl-2.5 pr-7 font-mono text-xs normal-case tracking-normal text-paper transition-colors duration-150 hover:border-paper/50 focus-visible:border-ember focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember focus-visible:ring-offset-2 focus-visible:ring-offset-ink disabled:cursor-not-allowed disabled:opacity-50 motion-reduce:transition-none"
        >
          {(models ?? []).map((model) => (
            <option key={model.model_id} value={model.model_id}>
              {model.model_id}
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

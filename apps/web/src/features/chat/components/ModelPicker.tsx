import { useModels } from '../hooks/useModels'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  return (
    <label className="flex items-center gap-2 font-mono text-xs text-paper/50">
      model
      <select
        value={value ?? ''}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="rounded border border-mist bg-graphite px-2 py-1 font-mono text-xs text-paper focus-visible:outline-2 focus-visible:outline-ember"
      >
        {(models ?? []).map((model) => (
          <option key={model.model_id} value={model.model_id}>
            {model.model_id}
          </option>
        ))}
      </select>
    </label>
  )
}

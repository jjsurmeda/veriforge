import { Bot, ChevronDown } from 'lucide-react'

import { useModels } from '../hooks/useModels'
import {
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from '../../../components/ui/primitives'

interface Props {
  value: string | null
  disabled?: boolean
  onChange: (modelId: string) => void
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  const providers = [...new Set((models ?? []).map((model) => model.provider))]
  return (
    <SelectRoot value={value ?? undefined} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger aria-label="Model" className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-lg px-2.5 text-sm text-fg-muted outline-none transition-colors hover:bg-raised hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring data-[placeholder]:text-fg-muted">
        <Bot size={14} strokeWidth={1.75} aria-hidden="true" />
        <SelectValue placeholder="Model" />
        <ChevronDown size={12} strokeWidth={1.75} aria-hidden="true" />
      </SelectTrigger>
      <SelectContent>
        <SelectViewport>
          {providers.map((provider) => (
            <SelectGroup key={provider}>
              <SelectLabel className="px-2.5 py-1.5 text-[11px] text-fg-subtle">{provider}</SelectLabel>
              {(models ?? []).filter((model) => model.provider === provider).map((model) => (
                <SelectItem key={model.model_id} value={model.model_id}>
                  <span className="flex min-w-0 flex-col"><span>{model.model_id}</span><span className="text-xs text-fg-muted">{model.context_window ? `${Math.round(model.context_window / 1000)}k context` : ''}</span></span>
                </SelectItem>
              ))}
            </SelectGroup>
          ))}
        </SelectViewport>
      </SelectContent>
    </SelectRoot>
  )
}

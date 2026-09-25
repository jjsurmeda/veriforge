import { ChevronDown } from 'lucide-react'

import type { ModelOut } from '../../../generated/types.gen'
import { useModels } from '../hooks/useModels'
import {
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectItemText,
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

export function shortModelName(modelId: string): string {
  const withoutProvider = modelId.includes('/') ? modelId.slice(modelId.indexOf('/') + 1) : modelId
  return withoutProvider.replace(/:free$/, '')
}

export function isFree(model: ModelOut): boolean {
  return model.price_in === 0 && model.price_out === 0
}

function contextLabel(contextWindow: number | null): string {
  if (!contextWindow) return ''
  return contextWindow >= 1000 ? `${Math.round(contextWindow / 1000)}k` : String(contextWindow)
}

export function ModelPicker({ value, disabled, onChange }: Props) {
  const { data: models } = useModels()
  const all = models ?? []
  const selected = all.find((model) => model.model_id === value)
  const providers = [...new Set(all.map((model) => model.provider))]

  return (
    <SelectRoot value={value ?? undefined} disabled={disabled} onValueChange={onChange}>
      <SelectTrigger
        aria-label="Model"
        className="inline-flex h-8 min-w-0 max-w-[13rem] items-center gap-1.5 rounded-lg px-2.5 text-sm text-fg-muted outline-none transition-[background-color,color,transform] duration-150 ease-out hover:bg-raised hover:text-fg active:scale-[0.97] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring disabled:pointer-events-none disabled:opacity-40 data-[placeholder]:text-fg-muted motion-reduce:transform-none"
      >
        <SelectValue placeholder="Model">
          {selected ? shortModelName(selected.model_id) : 'Model'}
        </SelectValue>
        <ChevronDown size={13} strokeWidth={1.75} aria-hidden="true" />
      </SelectTrigger>
      <SelectContent className="min-w-[16rem]">
        <SelectViewport>
          {providers.map((provider) => (
            <SelectGroup key={provider}>
              <SelectLabel className="px-2.5 py-1.5 text-[0.65rem] uppercase tracking-[0.12em] text-fg-subtle">
                {provider}
              </SelectLabel>
              {all
                .filter((model) => model.provider === provider)
                .map((model) => (
                  <SelectItem key={model.model_id} value={model.model_id}>
                    <SelectItemText>{shortModelName(model.model_id)}</SelectItemText>
                    <span className="ml-auto flex shrink-0 items-center gap-1.5 pl-3">
                      {isFree(model) && (
                        <span className="rounded-full border border-border px-1.5 py-0.5 text-[0.6rem] text-fg-muted">
                          Free
                        </span>
                      )}
                      <span className="font-mono text-[0.65rem] tabular-nums text-fg-subtle">
                        {contextLabel(model.context_window)}
                      </span>
                    </span>
                  </SelectItem>
                ))}
            </SelectGroup>
          ))}
        </SelectViewport>
      </SelectContent>
    </SelectRoot>
  )
}

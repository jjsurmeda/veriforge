import { Zap } from 'lucide-react'

import {
  SelectContent,
  SelectItem,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from '../../../components/ui/primitives'

export type RunMode = 'auto' | 'fast' | 'deep'

interface Props {
  value: RunMode
  disabled?: boolean
  onChange: (mode: RunMode) => void
}

const MODES: Array<{ value: RunMode; label: string; description: string }> = [
  { value: 'auto', label: 'Auto', description: 'Fast, single-pass answer' },
  { value: 'fast', label: 'Fast', description: 'Fast, single-pass answer' },
  { value: 'deep', label: 'Deep', description: 'Plans, multi-hop, verifies' },
]

export function ModePicker({ value, disabled, onChange }: Props) {
  return (
    <SelectRoot value={value} disabled={disabled} onValueChange={(next) => onChange(next as RunMode)}>
      <SelectTrigger aria-label="Run mode" className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-lg px-2.5 text-sm text-fg-muted outline-none transition-colors hover:bg-raised hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
        <Zap size={14} strokeWidth={1.75} aria-hidden="true" />
        <SelectValue placeholder="Mode" />
      </SelectTrigger>
      <SelectContent>
        <SelectViewport>
          {MODES.map((mode) => <SelectItem key={mode.value} value={mode.value}><span className="flex flex-col"><span>{mode.label}</span><span className="text-xs text-fg-muted">{mode.description}</span></span></SelectItem>)}
        </SelectViewport>
      </SelectContent>
    </SelectRoot>
  )
}

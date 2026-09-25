import { Library } from 'lucide-react'

import {
  SelectContent,
  SelectItem,
  SelectRoot,
  SelectTrigger,
  SelectValue,
  SelectViewport,
} from '../../../components/ui/primitives'

export type RunSource = 'auto' | 'upload' | 'web' | 'both'

interface Props {
  value: RunSource
  disabled?: boolean
  onChange: (source: RunSource) => void
}

const SOURCES: Array<{ value: RunSource; label: string; description: string }> = [
  { value: 'auto', label: 'Auto', description: 'Choose the best source' },
  { value: 'upload', label: 'Upload', description: 'Your uploaded documents' },
  { value: 'web', label: 'Web', description: 'Search the web' },
  { value: 'both', label: 'Both', description: 'Documents and web' },
]

export function SourcePicker({ value, disabled, onChange }: Props) {
  return (
    <SelectRoot value={value} disabled={disabled} onValueChange={(next) => onChange(next as RunSource)}>
      <SelectTrigger aria-label="Run source" className="inline-flex h-8 min-w-0 items-center gap-1.5 rounded-lg px-2.5 text-sm text-fg-muted outline-none transition-colors hover:bg-raised hover:text-fg focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring">
        <Library size={14} strokeWidth={1.75} aria-hidden="true" />
        <SelectValue placeholder="Source" />
      </SelectTrigger>
      <SelectContent>
        <SelectViewport>
          {SOURCES.map((source) => <SelectItem key={source.value} value={source.value}><span className="flex flex-col"><span>{source.label}</span><span className="text-xs text-fg-muted">{source.description}</span></span></SelectItem>)}
        </SelectViewport>
      </SelectContent>
    </SelectRoot>
  )
}

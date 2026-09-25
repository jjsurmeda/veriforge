import { useRef, useState } from 'react'
import { Check, CircleX, CloudUpload, LoaderCircle } from 'lucide-react'

export interface UploadOutcome { file: File; state: 'uploading' | 'done' | 'error'; message?: string }

export function apiErrorMessage(error: unknown): string {
  if (typeof error === 'object' && error !== null && 'error_code' in error && 'message' in error) {
    const message = (error as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  return 'Upload failed'
}

export function UploadDropzone({ disabled, onUpload }: { disabled: boolean; onUpload: (file: File) => Promise<unknown> }) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [outcomes, setOutcomes] = useState<UploadOutcome[]>([])
  const setOutcome = (file: File, patch: Partial<UploadOutcome>) => setOutcomes((current) => current.map((entry) => (entry.file === file ? { ...entry, ...patch } : entry)))
  const send = async (files: File[]) => {
    const fresh = files.map<UploadOutcome>((file) => ({ file, state: 'uploading' }))
    setOutcomes((current) => [...current, ...fresh])
    for (const file of files) {
      try { await onUpload(file); setOutcome(file, { state: 'done' }) } catch (error) { setOutcome(file, { state: 'error', message: apiErrorMessage(error) }) }
    }
  }
  const onDrop = (event: React.DragEvent) => { event.preventDefault(); setDragOver(false); if (!disabled) void send(Array.from(event.dataTransfer.files)) }
  return <div>
    <button type="button" disabled={disabled} onClick={() => inputRef.current?.click()} onDragOver={(event) => { event.preventDefault(); setDragOver(true) }} onDragLeave={() => setDragOver(false)} onDrop={onDrop} className={`flex w-full flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-8 text-sm transition-[background-color,border-color,transform] duration-150 focus-visible:outline-2 focus-visible:outline-accent ${dragOver ? 'border-accent bg-accent-soft text-accent' : 'border-border-strong bg-surface text-foreground hover:border-accent hover:bg-surface-hover'} ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}>
      <span className="flex size-9 items-center justify-center rounded-lg border border-border bg-surface-raised text-accent"><CloudUpload size={18} strokeWidth={1.75} aria-hidden="true" /></span><span className="font-medium">Drop files here, or click to choose</span><span className="text-xs text-muted-foreground">PDF, Office, text — up to 20 MB each</span>
    </button>
    <input ref={inputRef} type="file" multiple className="hidden" onChange={(event) => { void send(Array.from(event.target.files ?? [])); event.target.value = '' }} />
    {outcomes.length > 0 && <ul className="mt-2 space-y-1 rounded-lg border border-border bg-surface p-2">{outcomes.map((outcome, index) => <li key={`${outcome.file.name}-${index}`} className="flex items-center justify-between gap-2 px-2 py-1.5 text-xs"><span className="truncate text-foreground">{outcome.file.name}</span>{outcome.state === 'uploading' && <span className="inline-flex shrink-0 items-center gap-1 text-info"><LoaderCircle size={12} strokeWidth={1.75} className="animate-spin" aria-hidden="true" />uploading…</span>}{outcome.state === 'done' && <span className="inline-flex shrink-0 items-center gap-1 text-success"><Check size={12} strokeWidth={1.75} aria-hidden="true" />queued</span>}{outcome.state === 'error' && <span className="inline-flex shrink-0 items-center gap-1 text-danger" role="alert"><CircleX size={12} strokeWidth={1.75} aria-hidden="true" />{outcome.message}</span>}</li>)}</ul>}
  </div>
}

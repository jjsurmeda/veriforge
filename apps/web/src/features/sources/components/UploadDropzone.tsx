import { useRef, useState } from 'react'

export interface UploadOutcome {
  file: File
  state: 'uploading' | 'done' | 'error'
  message?: string
}

export function apiErrorMessage(error: unknown): string {
  if (
    typeof error === 'object' &&
    error !== null &&
    'error_code' in error &&
    'message' in error
  ) {
    const message = (error as { message?: unknown }).message
    if (typeof message === 'string' && message) return message
  }
  return 'Upload failed'
}

export function UploadDropzone({
  disabled,
  onUpload,
}: {
  disabled: boolean
  onUpload: (file: File) => Promise<unknown>
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [outcomes, setOutcomes] = useState<UploadOutcome[]>([])

  const setOutcome = (file: File, patch: Partial<UploadOutcome>) => {
    setOutcomes((current) =>
      current.map((entry) => (entry.file === file ? { ...entry, ...patch } : entry)),
    )
  }

  const send = async (files: File[]) => {
    const fresh = files.map<UploadOutcome>((file) => ({ file, state: 'uploading' }))
    setOutcomes((current) => [...current, ...fresh])
    for (const file of files) {
      try {
        await onUpload(file)
        setOutcome(file, { state: 'done' })
      } catch (error) {
        setOutcome(file, { state: 'error', message: apiErrorMessage(error) })
      }
    }
  }

  const onDrop = (event: React.DragEvent) => {
    event.preventDefault()
    setDragOver(false)
    if (disabled) return
    void send(Array.from(event.dataTransfer.files))
  }

  return (
    <div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
        onDragOver={(event) => {
          event.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        className={`flex w-full flex-col items-center gap-1 rounded border border-dashed px-4 py-8 text-sm focus-visible:outline-2 focus-visible:outline-ember ${
          dragOver ? 'border-ember text-paper' : 'border-mist text-paper/60'
        } ${disabled ? 'cursor-not-allowed opacity-50' : 'hover:border-paper/50'}`}
      >
        <span>Drop files here, or click to choose</span>
        <span className="text-xs text-paper/40">PDF, Office, text — up to 20 MB each</span>
      </button>
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={(event) => {
          void send(Array.from(event.target.files ?? []))
          event.target.value = ''
        }}
      />
      {outcomes.length > 0 && (
        <ul className="mt-2 space-y-1">
          {outcomes.map((outcome, index) => (
            <li
              key={`${outcome.file.name}-${index}`}
              className="flex items-center justify-between gap-2 px-1 text-xs"
            >
              <span className="truncate text-paper/70">{outcome.file.name}</span>
              {outcome.state === 'uploading' && (
                <span className="shrink-0 text-ember">uploading…</span>
              )}
              {outcome.state === 'done' && <span className="shrink-0 text-patina">queued</span>}
              {outcome.state === 'error' && (
                <span className="shrink-0 text-rust" role="alert">
                  {outcome.message}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

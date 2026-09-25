import { useState } from 'react'
import { Eye, FileText } from 'lucide-react'

import { useMe } from '../../auth/hooks/useMe'
import { useLibrary, useUploadLibraryDocument } from '../hooks/useDocuments'
import { StatusChip } from './StatusChip'
import { UploadDropzone } from './UploadDropzone'

interface Props {
  onOpenDocument: (documentId: string) => void
}

export function LibrarySection({ onOpenDocument }: Props) {
  const [shared, setShared] = useState(false)
  const { data: me } = useMe()
  const library = useLibrary()
  const uploadMine = useUploadLibraryDocument(false)
  const uploadShared = useUploadLibraryDocument(true)
  const upload = shared ? uploadShared : uploadMine
  const isAdmin = me?.role === 'admin'

  const documents = library.data?.documents ?? []
  const mine = documents.filter((document) => !document.shared)
  const sharedDocuments = documents.filter((document) => document.shared)

  const row = (document: (typeof documents)[number], readOnly: boolean) => (
    <li key={document.id}>
      <button
        type="button"
        onClick={() => onOpenDocument(document.id)}
        className="flex min-h-8 w-full items-center gap-1.5 rounded-lg px-1.5 text-left text-xs text-fg-muted transition-colors duration-150 hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
      >
        <FileText size={13} strokeWidth={1.75} className="min-w-0 shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">{document.name}</span>
        {readOnly && (
          <span className="shrink-0 rounded-full border border-border px-1.5 py-0.5 text-[0.6rem] text-fg-subtle">
            Read-only
          </span>
        )}
        <StatusChip status={document.status} />
      </button>
    </li>
  )

  return (
    <div className="flex flex-col gap-2">
      <UploadDropzone
        compact
        disabled={upload.isPending}
        label="Drop files or browse"
        onUpload={async (file) => upload.mutateAsync(file)}
      />

      {isAdmin && (
        <div className="flex items-center gap-1" role="group" aria-label="Upload target">
          {(
            [
              { value: false, label: 'Mine' },
              { value: true, label: 'Shared' },
            ] as const
          ).map((option) => (
            <button
              key={option.label}
              type="button"
              aria-pressed={shared === option.value}
              onClick={() => setShared(option.value)}
              className={`min-h-7 rounded-lg border px-2 text-[0.68rem] focus-visible:outline-2 focus-visible:outline-focus-ring ${
                shared === option.value
                  ? 'border-border-strong bg-raised text-fg'
                  : 'border-border text-fg-muted hover:bg-raised-hover hover:text-fg'
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>
      )}

      <section aria-labelledby="library-mine-heading">
        <h3 id="library-mine-heading" className="px-1.5 pb-1 text-[0.62rem] uppercase tracking-[0.12em] text-fg-subtle">
          Mine
        </h3>
        {mine.length === 0 ? (
          <p className="px-1.5 py-1 text-xs text-fg-muted">No documents yet.</p>
        ) : (
          <ul className="space-y-0.5">{mine.map((document) => row(document, false))}</ul>
        )}
      </section>

      <section aria-labelledby="library-shared-heading">
        <h3 id="library-shared-heading" className="px-1.5 pb-1 text-[0.62rem] uppercase tracking-[0.12em] text-fg-subtle">
          Shared
        </h3>
        {sharedDocuments.length === 0 ? (
          <p className="px-1.5 py-1 text-xs text-fg-muted">No shared documents yet.</p>
        ) : (
          <ul className="space-y-0.5">{sharedDocuments.map((document) => row(document, true))}</ul>
        )}
      </section>

      <p className="flex items-center gap-1.5 px-1.5 pt-1 text-[0.62rem] text-fg-subtle">
        <Eye size={12} strokeWidth={1.75} aria-hidden="true" />
        Documents apply to every chat.
      </p>
    </div>
  )
}

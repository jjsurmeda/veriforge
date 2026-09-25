import { useState } from 'react'
import { FileText } from 'lucide-react'

import { useMe } from '../../auth/hooks/useMe'
import {
  useDeleteDocument,
  useLibrary,
  usePatchDocumentTags,
  useReindexDocument,
  useUploadLibraryDocument,
} from '../hooks/useDocuments'
import { useDocumentChunks } from '../hooks/useDocumentChunks'
import { DocumentList } from '../components/DocumentList'
import { DocumentViewer } from '../components/DocumentViewer'
import { StarterQuestions } from '../components/StarterQuestions'
import { UploadDropzone } from '../components/UploadDropzone'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function LibraryPage() {
  const [viewerId, setViewerId] = useState<string | null>(null)
  const [shared, setShared] = useState(false)
  const { data: me } = useMe()
  const library = useLibrary()
  const uploadMine = useUploadLibraryDocument(false)
  const uploadShared = useUploadLibraryDocument(true)
  const upload = shared ? uploadShared : uploadMine
  const patchTags = usePatchDocumentTags()
  const deleteDocument = useDeleteDocument()
  const reindexDocument = useReindexDocument()

  const documents = library.data?.documents ?? []
  const mine = documents.filter((document) => !document.shared)
  const sharedDocuments = documents.filter((document) => document.shared)
  const viewerDocument = documents.find((document) => document.id === viewerId)
  const chunks = useDocumentChunks(
    viewerId,
    viewerDocument !== undefined && LIVE_STATUSES.has(viewerDocument.status),
  )

  const onDelete = async (documentId: string) => {
    if (!window.confirm('Delete this document and its chunks?')) return
    if (viewerId === documentId) setViewerId(null)
    await deleteDocument.mutateAsync(documentId)
  }

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-main text-fg">
      <div className="mx-auto flex w-full max-w-[56rem] flex-col gap-6 p-4 sm:p-6 lg:p-8">
        <header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.12em] text-fg-subtle">
              Evidence library
            </p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight text-fg">Library</h1>
            <p className="mt-2 max-w-[52ch] text-sm leading-6 text-fg-muted">
              Your documents apply to every chat. Shared documents are published by admins and
              read-only.
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 font-mono text-xs tabular-nums text-fg-muted">
            <FileText size={13} strokeWidth={1.75} aria-hidden="true" />
            {documents.length} document{documents.length === 1 ? '' : 's'}
          </span>
        </header>

        <StarterQuestions questions={library.data?.starter_questions ?? []} />

        {me?.role === 'admin' && (
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Upload target"
          >
            {(
              [
                { value: false, label: 'My Library' },
                { value: true, label: 'Shared' },
              ] as const
            ).map((option) => (
              <button
                key={option.label}
                type="button"
                aria-pressed={shared === option.value}
                onClick={() => setShared(option.value)}
                className={`pressable min-h-9 rounded-lg border px-3 text-sm focus-visible:outline-2 focus-visible:outline-focus-ring ${
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

        <UploadDropzone
          disabled={upload.isPending}
          onUpload={async (file) => upload.mutateAsync(file)}
        />

        <section aria-labelledby="library-mine-heading" className="flex flex-col gap-3">
          <h2
            id="library-mine-heading"
            className="text-xs font-medium uppercase tracking-[0.12em] text-fg-subtle"
          >
            Mine
          </h2>
          <DocumentList
            documents={mine}
            onView={setViewerId}
            onReindex={(documentId) => void reindexDocument.mutateAsync(documentId)}
            onDelete={(documentId) => void onDelete(documentId)}
          />
        </section>

        <section aria-labelledby="library-shared-heading" className="flex flex-col gap-3">
          <h2
            id="library-shared-heading"
            className="text-xs font-medium uppercase tracking-[0.12em] text-fg-subtle"
          >
            Shared
          </h2>
          {sharedDocuments.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-strong bg-surface px-4 py-8 text-center text-sm text-fg-muted">
              No shared documents yet.
            </p>
          ) : (
            <DocumentList
              documents={sharedDocuments}
              readOnly
              onView={setViewerId}
              onReindex={(documentId) => void reindexDocument.mutateAsync(documentId)}
              onDelete={(documentId) => void onDelete(documentId)}
            />
          )}
        </section>
      </div>

      {viewerDocument && (
        <div className="w-full shrink-0 lg:w-[42rem]">
          <DocumentViewer
            document={viewerDocument}
            chunks={chunks.data ?? []}
            onClose={() => setViewerId(null)}
            onSaveTags={async (tags) => {
              await patchTags.mutateAsync({ documentId: viewerDocument.id, tags })
            }}
            onReindex={() => void reindexDocument.mutateAsync(viewerDocument.id)}
          />
        </div>
      )}
    </div>
  )
}
import { useState } from 'react'
import { FileText, FolderOpen, Menu } from 'lucide-react'

import { useCollections, useCreateCollection } from '../hooks/useCollections'
import {
  useDeleteDocument,
  useDocuments,
  usePatchDocumentTags,
  useReindexDocument,
  useUploadDocument,
} from '../hooks/useDocuments'
import { useDocumentChunks } from '../hooks/useDocumentChunks'
import { CollectionList } from '../components/CollectionList'
import { DocumentList } from '../components/DocumentList'
import { DocumentViewer } from '../components/DocumentViewer'
import { StarterQuestions } from '../components/StarterQuestions'
import { UploadDropzone } from '../components/UploadDropzone'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function SourcesPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [viewerId, setViewerId] = useState<string | null>(null)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  const collections = useCollections()
  const createCollection = useCreateCollection()
  const documents = useDocuments(selectedId)
  const upload = useUploadDocument(selectedId)
  const patchTags = usePatchDocumentTags(selectedId)
  const deleteDocument = useDeleteDocument(selectedId)
  const reindexDocument = useReindexDocument(selectedId)

  const selected = (collections.data ?? []).find((collection) => collection.id === selectedId)
  const viewerDocument = (documents.data ?? []).find((document) => document.id === viewerId)
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
    <div className="theme-transition flex h-screen bg-background text-foreground">
      <CollectionList
        collections={collections.data ?? []}
        selectedId={selectedId}
        onSelect={(collectionId) => {
          setSelectedId(collectionId)
          setViewerId(null)
        }}
        onCreate={async (name) => {
          const created = await createCollection.mutateAsync(name)
          if (created) setSelectedId(created.id)
        }}
        creating={createCollection.isPending}
        mobileOpen={sidebarOpen}
        onMobileClose={() => setSidebarOpen(false)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between border-b border-border bg-surface px-3 py-2 lg:hidden">
          <button
            type="button"
            aria-label="Open source navigation"
            onClick={() => setSidebarOpen(true)}
            className="inline-flex size-9 items-center justify-center rounded-lg border border-border bg-surface-muted text-muted-foreground transition-[color,background-color,transform] duration-180 hover:bg-primary-soft hover:text-primary active:translate-y-px focus-visible:outline-2 focus-visible:outline-primary motion-reduce:transition-none"
          >
            <Menu size={17} aria-hidden="true" />
          </button>
          <span className="text-sm font-semibold text-foreground">Sources</span>
          <span className="size-9" aria-hidden="true" />
        </div>
        <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8">
          {selected ? (
          <>
            <header className="flex flex-wrap items-end justify-between gap-3 rounded-xl border border-border bg-surface px-5 py-4 shadow-sm">
              <div className="flex items-center gap-3">
                <span className="flex size-10 items-center justify-center rounded-xl bg-secondary-soft text-secondary shadow-sm">
                  <FolderOpen size={19} aria-hidden="true" />
                </span>
                <div>
                  <h1 className="font-display text-xl font-semibold tracking-tight text-foreground">
                    {selected.name}
                  </h1>
                  {selected.visibility === 'shared' && (
                    <span className="mt-0.5 inline-flex rounded-full bg-accent-soft px-2 py-0.5 text-[0.65rem] font-medium text-accent">shared</span>
                  )}
                </div>
              </div>
              <span className="inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground">
                <FileText size={13} aria-hidden="true" />
                {selected.document_count} document{selected.document_count === 1 ? '' : 's'}
              </span>
            </header>
            <StarterQuestions questions={selected.starter_questions} />
            <UploadDropzone
              disabled={upload.isPending}
              onUpload={async (file) => upload.mutateAsync(file)}
            />
            <DocumentList
              documents={documents.data ?? []}
              onView={setViewerId}
              onReindex={(documentId) => void reindexDocument.mutateAsync(documentId)}
              onDelete={(documentId) => void onDelete(documentId)}
            />
          </>
        ) : (
          <div className="flex min-h-[50vh] items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface/60 p-8 text-center shadow-sm">
            <div>
              <FolderOpen size={28} className="mx-auto text-muted-foreground" aria-hidden="true" />
              <p className="mt-3 text-sm text-muted-foreground">Select a collection on the left, or create one to start adding sources.</p>
            </div>
           </div>
         )}
        </div>
      </main>

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

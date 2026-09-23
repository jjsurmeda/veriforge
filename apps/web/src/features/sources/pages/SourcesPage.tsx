import { useState } from 'react'

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
    <div className="flex h-screen bg-ink text-paper">
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
      />
      <main className="flex min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
        {selected ? (
          <>
            <header className="flex items-baseline justify-between gap-3">
              <h1 className="font-display text-xl tracking-tight text-paper">
                {selected.name}
                {selected.visibility === 'shared' && (
                  <span className="ml-2 text-sm text-paper/40">shared</span>
                )}
              </h1>
              <span className="text-xs text-paper/40">
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
          <p className="p-6 text-sm text-paper/60">
            Select a collection on the left, or create one to start adding sources.
          </p>
        )}
      </main>
      {viewerDocument && (
        <div className="w-[42rem] shrink-0">
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

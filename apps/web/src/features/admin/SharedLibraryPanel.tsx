import { useState } from 'react'
import { FileText, MoreHorizontal, RotateCcw, Trash2 } from 'lucide-react'

import type { LibraryDocumentOut } from '../../generated/types.gen'
import { DocumentViewer } from '../library/components/DocumentViewer'
import { StatusChip } from '../library/components/StatusChip'
import { UploadDropzone } from '../library/components/UploadDropzone'
import { useDocumentChunks } from '../library/hooks/useDocumentChunks'
import {
  useDeleteDocument,
  useLibrary,
  usePatchDocumentTags,
  useReindexDocument,
  useUploadLibraryDocument,
} from '../library/hooks/useDocuments'
import {
  Menu,
  MenuContent,
  MenuItemWithIcon,
  MenuTrigger,
} from '../../components/ui/primitives'
import { IconButton } from '../../components/ui/IconButton'

export function SharedLibraryPanel() {
  const library = useLibrary()
  const upload = useUploadLibraryDocument()
  const remove = useDeleteDocument()
  const reindex = useReindexDocument()
  const patchTags = usePatchDocumentTags()
  const [viewerId, setViewerId] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)

  const documents = library.data?.documents ?? []
  const viewer = documents.find((entry) => entry.id === viewerId)
  const viewerChunks = useDocumentChunks(
    viewerId,
    viewer !== undefined && ['queued', 'parsing', 'embedding'].includes(viewer.status),
  )

  if (viewer !== undefined) {
    return (
      <DocumentViewer
        document={viewer}
        chunks={viewerChunks.data ?? []}
        onClose={() => setViewerId(null)}
        onSaveTags={async (tags) => {
          await patchTags.mutateAsync({ documentId: viewer.id, tags })
        }}
        onReindex={() => void reindex.mutateAsync(viewer.id)}
      />
    )
  }

  return (
    <div className="space-y-4">
      <UploadDropzone
        disabled={upload.isPending}
        label="Drop files here, or click to publish to Shared"
        onUpload={async (file) => upload.mutateAsync(file)}
      />
      <p className="text-xs text-fg-muted">
        Every chat searches these. {documents.length}{' '}
        {documents.length === 1 ? 'document' : 'documents'} published.
      </p>
      <ul className="divide-y divide-border overflow-hidden rounded-xl border border-border bg-surface">
        {documents.length === 0 && (
          <li className="px-4 py-6 text-center text-sm text-fg-muted">
            Nothing published yet.
          </li>
        )}
        {documents.map((document: LibraryDocumentOut) => (
          <li key={document.id} className="px-3 py-2">
            <div className="flex min-h-9 items-center gap-2">
              <FileText size={14} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />
              <button
                type="button"
                onClick={() => setViewerId(document.id)}
                className="min-w-0 flex-1 truncate rounded-md text-left text-sm text-fg hover:underline focus-visible:outline-2 focus-visible:outline-focus-ring"
              >
                {document.name}
              </button>
              {document.tags.length > 0 && (
                <span className="hidden shrink-0 text-xs text-fg-muted sm:inline">
                  {document.tags.join(', ')}
                </span>
              )}
              <StatusChip status={document.status} />
              <Menu>
                <MenuTrigger asChild>
                  <IconButton
                    size={28}
                    aria-label={`Actions for ${document.name}`}
                    className="text-fg-muted"
                  >
                    <MoreHorizontal size={14} strokeWidth={1.75} aria-hidden="true" />
                  </IconButton>
                </MenuTrigger>
                <MenuContent side="bottom" align="end" className="w-40">
                  <MenuItemWithIcon onSelect={() => setViewerId(document.id)}>
                    <FileText size={13} strokeWidth={1.75} aria-hidden="true" />
                    View
                  </MenuItemWithIcon>
                  <MenuItemWithIcon onSelect={() => void reindex.mutateAsync(document.id)}>
                    <RotateCcw size={13} strokeWidth={1.75} aria-hidden="true" />
                    Re-index
                  </MenuItemWithIcon>
                  <MenuItemWithIcon
                    className="text-danger"
                    onSelect={() => setConfirming(document.id)}
                  >
                    <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
                    Delete
                  </MenuItemWithIcon>
                </MenuContent>
              </Menu>
            </div>
            {confirming === document.id && (
              <div className="mt-1.5 flex items-center gap-2 rounded-lg bg-raised px-2 py-1.5">
                <p className="min-w-0 flex-1 truncate text-xs text-fg-muted">
                  Remove {document.name} from the Shared library?
                </p>
                <button
                  type="button"
                  onClick={() => setConfirming(null)}
                  className="pressable min-h-7 rounded-lg px-2 text-xs text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setConfirming(null)
                    void remove.mutateAsync(document.id)
                  }}
                  className="pressable min-h-7 rounded-lg border border-border/40 px-2 text-xs font-medium text-danger hover:bg-raised focus-visible:outline-2 focus-visible:outline-danger"
                >
                  Delete
                </button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

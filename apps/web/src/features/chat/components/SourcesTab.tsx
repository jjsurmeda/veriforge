import { useRef, useState } from 'react'
import {
  AlertTriangle,
  ChevronRight,
  CloudUpload,
  FileText,
  Library,
  MoreHorizontal,
  Plus,
  RotateCcw,
  Trash2,
} from 'lucide-react'

import type { DocumentOut, LibraryDocumentOut } from '../../../generated/types.gen'
import { DocumentViewer } from '../../library/components/DocumentViewer'
import { StatusChip } from '../../library/components/StatusChip'
import { useDocumentChunks } from '../../library/hooks/useDocumentChunks'
import {
  useChatDocuments,
  useDeleteDocument,
  useLibrary,
  usePatchDocumentTags,
  useReindexDocument,
  useUploadChatDocument,
} from '../../library/hooks/useDocuments'
import { IconButton } from '../../../components/ui/IconButton'
import { PanelEmpty } from '../../../components/ui/PanelEmpty'
import {
  Menu,
  MenuContent,
  MenuItemWithIcon,
  MenuTrigger,
  TooltipContent,
  TooltipRoot,
  TooltipTrigger,
} from '../../../components/ui/primitives'

interface Props {
  chatId: string | null
  viewerDocumentId: string | null
  onViewDocument: (documentId: string) => void
  onCloseViewer: () => void
}

function DocumentRow({
  document,
  onView,
  onDelete,
  onReindex,
}: {
  document: DocumentOut
  onView: (documentId: string) => void
  onDelete: (documentId: string) => void
  onReindex: (documentId: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const flagged = (document.page_flags ?? []).length > 0

  return (
    <li className="px-1 py-1.5">
      <div className="flex min-h-9 items-center gap-1.5">
        <FileText size={14} strokeWidth={1.75} className="shrink-0 text-fg-muted" aria-hidden="true" />
        <button
          type="button"
          onClick={() => onView(document.id)}
          className="min-w-0 flex-1 truncate rounded-md text-left text-xs text-fg hover:underline focus-visible:outline-2 focus-visible:outline-focus-ring"
        >
          {document.name}
        </button>
        {flagged && (
          <span className="inline-flex shrink-0 items-center gap-1 text-2xs text-warning">
            <AlertTriangle size={11} strokeWidth={1.75} aria-hidden="true" />
            pages flagged
          </span>
        )}
        <StatusChip status={document.status} />
        <Menu>
          <MenuTrigger asChild>
            <IconButton size={28} aria-label={`Actions for ${document.name}`} className="text-fg-muted">
              <MoreHorizontal size={14} strokeWidth={1.75} aria-hidden="true" />
            </IconButton>
          </MenuTrigger>
          <MenuContent side="bottom" align="end" className="w-40">
            <MenuItemWithIcon onSelect={() => onView(document.id)}>
              <FileText size={13} strokeWidth={1.75} aria-hidden="true" />
              View
            </MenuItemWithIcon>
            <MenuItemWithIcon onSelect={() => onReindex(document.id)}>
              <RotateCcw size={13} strokeWidth={1.75} aria-hidden="true" />
              Re-index
            </MenuItemWithIcon>
            <MenuItemWithIcon className="text-danger" onSelect={() => setConfirming(true)}>
              <Trash2 size={13} strokeWidth={1.75} aria-hidden="true" />
              Delete
            </MenuItemWithIcon>
          </MenuContent>
        </Menu>
      </div>
      {confirming && (
        <div className="mt-1 flex items-center gap-2 rounded-lg bg-raised px-2 py-1.5">
          <p className="min-w-0 flex-1 truncate text-2xs text-fg-muted">Delete {document.name}?</p>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            className="pressable min-h-7 rounded-lg px-2 text-2xs text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => onDelete(document.id)}
            className="pressable min-h-7 rounded-lg border border-border/40 px-2 text-2xs font-medium text-danger hover:bg-raised focus-visible:outline-2 focus-visible:outline-danger"
          >
            Delete
          </button>
        </div>
      )}
    </li>
  )
}

function SharedRow({
  documents,
  onView,
}: {
  documents: LibraryDocumentOut[]
  onView: (documentId: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <li className="border-t border-border">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex min-h-10 w-full items-center gap-2 px-2 text-left text-xs text-fg-muted transition-colors duration-150 hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
      >
        <Library size={14} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
        <span className="min-w-0 flex-1 truncate">Shared library</span>
        <span className="shrink-0 font-mono text-2xs tabular-nums text-fg-subtle">
          {documents.length} documents · always searched
        </span>
        <ChevronRight
          size={14}
          strokeWidth={1.75}
          className={`shrink-0 transition-transform duration-150 ${open ? 'rotate-90' : ''}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <ul className="pb-1">
          {documents.length === 0 ? (
            <li className="py-1 pl-6 pr-2 text-2xs text-fg-muted">The Shared library is empty.</li>
          ) : (
            documents.map((document) => (
              <li key={document.id}>
                <button
                  type="button"
                  onClick={() => onView(document.id)}
                  className="flex min-h-8 w-full items-center gap-1.5 rounded-lg py-1 pl-6 pr-2 text-left text-xs text-fg-muted hover:bg-raised-hover hover:text-fg focus-visible:outline-2 focus-visible:outline-focus-ring"
                >
                  <FileText size={13} strokeWidth={1.75} className="shrink-0" aria-hidden="true" />
                  <span className="min-w-0 flex-1 truncate">{document.name}</span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </li>
  )
}

export function SourcesTab({ chatId, viewerDocumentId, onViewDocument, onCloseViewer }: Props) {
  const chat = useChatDocuments(chatId)
  const library = useLibrary()
  const upload = useUploadChatDocument(chatId)
  const remove = useDeleteDocument()
  const reindex = useReindexDocument()
  const patchTags = usePatchDocumentTags()
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)

  const documents = chat.data ?? []
  const shared = library.data?.documents ?? []
  const viewer =
    documents.find((entry) => entry.id === viewerDocumentId) ??
    shared.find((entry) => entry.id === viewerDocumentId)
  const viewerLive =
    viewer !== undefined && ['queued', 'parsing', 'embedding'].includes(viewer.status)
  const viewerChunks = useDocumentChunks(viewer?.id ?? null, viewerLive)

  const disabled = chatId === null || upload.isPending
  const pick = () => inputRef.current?.click()
  const addFiles = async (files: File[]) => {
    for (const file of files) await upload.mutateAsync(file)
  }
  const dropProps = {
    onDragOver: (event: React.DragEvent) => {
      event.preventDefault()
      setDragOver(true)
    },
    onDragLeave: () => setDragOver(false),
    onDrop: (event: React.DragEvent) => {
      event.preventDefault()
      setDragOver(false)
      if (!disabled && event.dataTransfer.files.length > 0) {
        void addFiles(Array.from(event.dataTransfer.files))
      }
    },
  }

  if (viewer !== undefined) {
    return (
      <DocumentViewer
        document={viewer}
        chunks={viewerChunks.data ?? []}
        backLabel="Sources"
        readOnly={shared.some((entry) => entry.id === viewer.id)}
        onClose={onCloseViewer}
        onSaveTags={async (tags) => {
          await patchTags.mutateAsync({ documentId: viewer.id, tags })
        }}
        onReindex={() => void reindex.mutateAsync(viewer.id)}
      />
    )
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <h2 className="text-xs font-medium text-fg">This chat</h2>
        <TooltipRoot>
          <TooltipTrigger asChild>
            <button
              type="button"
              aria-label="Add sources"
              disabled={disabled}
              onClick={pick}
              className="pressable inline-flex min-h-8 items-center gap-1 rounded-lg border border-border bg-surface px-2 text-xs text-fg-muted hover:bg-raised-hover hover:text-fg disabled:pointer-events-none disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-focus-ring"
            >
              <Plus size={14} strokeWidth={1.75} aria-hidden="true" />
              Add
            </button>
          </TooltipTrigger>
          <TooltipContent>Add sources</TooltipContent>
        </TooltipRoot>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {documents.length === 0 ? (
          <PanelEmpty
            title={chatId === null ? 'No chat to add sources to yet.' : 'Add sources to this chat.'}
            hint={
              chatId === null
                ? 'Start a chat from the composer and its sources will show up here.'
                : 'PDF, DOCX, MD, TXT, up to 20 MB.'
            }
            action={
              <button
                type="button"
                disabled={disabled}
                onClick={pick}
                {...dropProps}
                className={`flex min-h-28 w-full flex-col items-center justify-center gap-1.5 rounded-xl border border-dashed transition-[background-color,border-color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring ${
                  dragOver
                    ? 'border-fg-muted bg-raised text-fg'
                    : 'border-border-strong bg-surface text-fg-muted hover:border-fg-subtle hover:text-fg'
                } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
              >
                <CloudUpload size={18} strokeWidth={1.75} aria-hidden="true" />
                <span className="text-xs">Drop files here, or click to choose</span>
              </button>
            }
          />
        ) : (
          <>
            <ul className="divide-y divide-border">
              {documents.map((document) => (
                <DocumentRow
                  key={document.id}
                  document={document}
                  onView={onViewDocument}
                  onDelete={(documentId) => void remove.mutateAsync(documentId)}
                  onReindex={(documentId) => void reindex.mutateAsync(documentId)}
                />
              ))}
            </ul>
            <button
              type="button"
              disabled={disabled}
              onClick={pick}
              {...dropProps}
              className={`mt-2 flex min-h-11 w-full items-center justify-center gap-1.5 rounded-lg border border-dashed text-2xs transition-[background-color,border-color,color] duration-150 focus-visible:outline-2 focus-visible:outline-focus-ring ${
                dragOver
                  ? 'border-fg-muted bg-raised text-fg'
                  : 'border-border text-fg-subtle hover:border-border-strong hover:text-fg-muted'
              } ${disabled ? 'cursor-not-allowed opacity-50' : ''}`}
            >
              <Plus size={13} strokeWidth={1.75} aria-hidden="true" />
              Drop files here to add them
            </button>
          </>
        )}
      </div>

      <ul className="shrink-0">
        <SharedRow documents={shared} onView={onViewDocument} />
      </ul>

      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        aria-label="Add sources to this chat"
        onChange={(event) => {
          const files = Array.from(event.currentTarget.files ?? [])
          event.currentTarget.value = ''
          if (files.length > 0) void addFiles(files)
        }}
      />
    </div>
  )
}

import { useState } from 'react'
import { FileText, FolderOpen, Menu, Plus } from 'lucide-react'

import { useCollections, useCreateCollection } from '../hooks/useCollections'
import { useDeleteDocument, useDocuments, usePatchDocumentTags, useReindexDocument, useUploadDocument } from '../hooks/useDocuments'
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
  const [newSourceName, setNewSourceName] = useState('')
  const collections = useCollections()
  const createCollection = useCreateCollection()
  const documents = useDocuments(selectedId)
  const upload = useUploadDocument(selectedId)
  const patchTags = usePatchDocumentTags(selectedId)
  const deleteDocument = useDeleteDocument(selectedId)
  const reindexDocument = useReindexDocument(selectedId)
  const selected = (collections.data ?? []).find((collection) => collection.id === selectedId)
  const viewerDocument = (documents.data ?? []).find((document) => document.id === viewerId)
  const chunks = useDocumentChunks(viewerId, viewerDocument !== undefined && LIVE_STATUSES.has(viewerDocument.status))

  const onDelete = async (documentId: string) => {
    if (!window.confirm('Delete this document and its chunks?')) return
    if (viewerId === documentId) setViewerId(null)
    await deleteDocument.mutateAsync(documentId)
  }
  const createSource = async () => {
    const name = newSourceName.trim()
    if (!name) return
    const created = await createCollection.mutateAsync(name)
    if (created) setSelectedId(created.id)
    setNewSourceName('')
  }

  return <div className="flex h-full min-h-0 bg-main text-fg"><CollectionList collections={collections.data ?? []} selectedId={selectedId} onSelect={(collectionId) => { setSelectedId(collectionId); setViewerId(null) }} onCreate={async (name) => { const created = await createCollection.mutateAsync(name); if (created) setSelectedId(created.id) }} creating={createCollection.isPending} mobileOpen={sidebarOpen} onMobileClose={() => setSidebarOpen(false)} /><main className="flex min-w-0 flex-1 flex-col"><div className="flex h-14 shrink-0 items-center justify-between border-b border-border px-3 lg:hidden"><button type="button" aria-label="Open source navigation" onClick={() => setSidebarOpen(true)} className="icon-button size-9"><Menu size={17} strokeWidth={1.75} aria-hidden="true" /></button><span className="text-sm font-semibold text-fg">Sources</span><span className="size-9" aria-hidden="true" /></div><div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-4 sm:p-6 lg:p-8">{selected ? <><header className="flex flex-wrap items-end justify-between gap-3 border-b border-border pb-4"><div className="flex items-center gap-3"><span className="flex size-9 items-center justify-center rounded-lg border border-border bg-surface text-fg"><FolderOpen size={18} strokeWidth={1.75} aria-hidden="true" /></span><div><h1 className="text-xl font-semibold tracking-tight text-fg">{selected.name}</h1>{selected.visibility === 'shared' && <span className="mt-0.5 inline-flex rounded-full border border-border/30 bg-raised px-2 py-0.5 text-[0.62rem] font-medium text-fg">shared</span>}</div></div><span className="inline-flex items-center gap-1.5 font-mono text-xs tabular-nums text-fg-muted"><FileText size={13} strokeWidth={1.75} aria-hidden="true" />{selected.document_count} document{selected.document_count === 1 ? '' : 's'}</span></header><StarterQuestions questions={selected.starter_questions} /><UploadDropzone disabled={upload.isPending} onUpload={async (file) => upload.mutateAsync(file)} /><DocumentList documents={documents.data ?? []} onView={setViewerId} onReindex={(documentId) => void reindexDocument.mutateAsync(documentId)} onDelete={(documentId) => void onDelete(documentId)} /></> : <div className="flex flex-1 flex-col justify-center"><div className="mb-5"><p className="text-xs font-medium uppercase tracking-[0.12em] text-fg-subtle">Evidence library</p><h1 className="mt-2 text-2xl font-semibold tracking-tight text-fg">Choose a source collection</h1><p className="mt-2 max-w-[48ch] text-sm leading-6 text-fg-muted">Select a collection on the left, or create one to start adding sources.</p></div><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{(collections.data ?? []).map((collection) => <button key={collection.id} type="button" onClick={() => setSelectedId(collection.id)} className="rounded-xl border border-border bg-surface p-4 text-left transition-colors duration-150 hover:bg-raised-hover focus-visible:outline-2 focus-visible:outline-focus-ring"><div className="flex items-center gap-2"><FolderOpen size={16} strokeWidth={1.75} className="text-fg" aria-hidden="true" /><span className="truncate text-sm font-medium text-fg">{collection.name}</span></div><p className="mt-3 font-mono text-xs tabular-nums text-fg-muted">{collection.document_count} document{collection.document_count === 1 ? '' : 's'}</p></button>)}<div className="rounded-xl border border-dashed border-border-strong bg-surface p-4"><p className="text-sm font-medium text-fg">+ New source</p><div className="mt-3 flex gap-2"><input value={newSourceName} onChange={(event) => setNewSourceName(event.currentTarget.value)} onKeyDown={(event) => { if (event.key === 'Enter') void createSource() }} placeholder="Collection name" aria-label="New source name" className="h-9 min-w-0 flex-1 rounded-lg border border-border bg-sidebar px-2.5 text-xs text-fg placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-focus-ring" /><button type="button" onClick={() => void createSource()} disabled={!newSourceName.trim() || createCollection.isPending} className="pressable inline-flex size-9 items-center justify-center rounded-lg bg-fg-strong text-on-strong disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-focus-ring" aria-label="Add source"><Plus size={15} strokeWidth={1.75} /></button></div></div></div></div>}</div></main>{viewerDocument && <div className="w-full shrink-0 lg:w-[42rem]"><DocumentViewer document={viewerDocument} chunks={chunks.data ?? []} onClose={() => setViewerId(null)} onSaveTags={async (tags) => { await patchTags.mutateAsync({ documentId: viewerDocument.id, tags }) }} onReindex={() => void reindexDocument.mutateAsync(viewerDocument.id)} /></div>}</div>
}

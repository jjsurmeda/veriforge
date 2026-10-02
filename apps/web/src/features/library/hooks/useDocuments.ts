import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteDocumentDocumentsDocumentIdDelete,
  getLibraryLibraryGet,
  listChatDocumentsChatsChatIdDocumentsGet,
  patchDocumentDocumentsDocumentIdPatch,
  reindexDocumentDocumentsDocumentIdReindexPost,
  uploadChatDocumentChatsChatIdDocumentsPost,
  uploadLibraryDocumentLibraryDocumentsPost,
} from '../../../generated/sdk.gen'
import type { DocumentOut } from '../../../generated/types.gen'
import { unwrap } from '../../../lib/api'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function shouldPoll(documents: DocumentOut[] | undefined): boolean {
  return (documents ?? []).some((doc) => LIVE_STATUSES.has(doc.status))
}

// A failed read must reach React Query as an error, so the Library and the
// Sources panel can tell "no documents yet" from "the request failed"
// (review P2). Same unwrap the admin queries use (lib/api.ts).
export function useLibrary() {
  return useQuery({
    queryKey: ['library'],
    queryFn: async () => unwrap(await getLibraryLibraryGet()),
    refetchInterval: (query) => (shouldPoll(query.state.data?.documents) ? 2000 : false),
  })
}

export function useChatDocuments(chatId: string | null) {
  return useQuery({
    queryKey: ['chats', chatId, 'documents'],
    enabled: chatId !== null,
    queryFn: async () =>
      unwrap(await listChatDocumentsChatsChatIdDocumentsGet({ path: { chat_id: chatId! } })),
    refetchInterval: (query) => (shouldPoll(query.state.data) ? 2000 : false),
  })
}

function useDocumentMutation<TVariables>(mutationFn: (variables: TVariables) => Promise<unknown>) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['library'] })
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
    },
  })
}

export function useUploadChatDocument(chatId: string | null) {
  return useDocumentMutation(async (file: File) => {
    const { error } = await uploadChatDocumentChatsChatIdDocumentsPost({
      path: { chat_id: chatId! },
      body: { file },
    })
    if (error) throw error
  })
}

export function useUploadLibraryDocument() {
  return useDocumentMutation(async (file: File) => {
    const { error } = await uploadLibraryDocumentLibraryDocumentsPost({
      body: { file },
    })
    if (error) throw error
  })
}

export function usePatchDocumentTags() {
  return useDocumentMutation(async ({ documentId, tags }: { documentId: string; tags: string[] }) => {
    const { error } = await patchDocumentDocumentsDocumentIdPatch({
      path: { document_id: documentId },
      body: { tags },
    })
    if (error) throw error
  })
}

export function useDeleteDocument() {
  return useDocumentMutation(async (documentId: string) => {
    const { error } = await deleteDocumentDocumentsDocumentIdDelete({
      path: { document_id: documentId },
    })
    if (error) throw error
  })
}

export function useReindexDocument() {
  return useDocumentMutation(async (documentId: string) => {
    const { error } = await reindexDocumentDocumentsDocumentIdReindexPost({
      path: { document_id: documentId },
    })
    if (error) throw error
  })
}

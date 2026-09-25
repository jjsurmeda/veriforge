import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteDocumentDocumentsDocumentIdDelete,
  getLibraryLibraryGet,
  listChatDocumentsChatsChatIdDocumentsGet,
  patchDocumentDocumentsDocumentIdPatch,
  pinWebSourceWebSourcesWebPageIdPinPost,
  reindexDocumentDocumentsDocumentIdReindexPost,
  uploadChatDocumentChatsChatIdDocumentsPost,
  uploadLibraryDocumentLibraryDocumentsPost,
} from '../../../generated/sdk.gen'
import type { DocumentOut, LibraryOut } from '../../../generated/types.gen'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function shouldPoll(documents: DocumentOut[] | undefined): boolean {
  return (documents ?? []).some((doc) => LIVE_STATUSES.has(doc.status))
}

const EMPTY_LIBRARY: LibraryOut = { documents: [], starter_questions: [] }

export function useLibrary() {
  return useQuery({
    queryKey: ['library'],
    queryFn: async () => (await getLibraryLibraryGet()).data ?? EMPTY_LIBRARY,
    refetchInterval: (query) => (shouldPoll(query.state.data?.documents) ? 2000 : false),
  })
}

export function useChatDocuments(chatId: string | null) {
  return useQuery({
    queryKey: ['chats', chatId, 'documents'],
    enabled: chatId !== null,
    queryFn: async () =>
      (await listChatDocumentsChatsChatIdDocumentsGet({ path: { chat_id: chatId! } })).data ?? [],
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

export function useUploadLibraryDocument(shared: boolean) {
  return useDocumentMutation(async (file: File) => {
    const { error } = await uploadLibraryDocumentLibraryDocumentsPost({
      query: { shared },
      body: { file },
    })
    if (error) throw error
  })
}

export function usePinWebSource() {
  return useDocumentMutation(
    async ({ webPageId, target }: { webPageId: string; target: 'chat' | 'library' }) => {
      const { error } = await pinWebSourceWebSourcesWebPageIdPinPost({
        path: { web_page_id: webPageId },
        body: { target },
      })
      if (error) throw error
    },
  )
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

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteDocumentDocumentsDocumentIdDelete,
  getCollectionDocumentsCollectionsCollectionIdDocumentsGet,
  patchDocumentDocumentsDocumentIdPatch,
  reindexDocumentDocumentsDocumentIdReindexPost,
  uploadDocumentCollectionsCollectionIdDocumentsPost,
} from '../../../generated/sdk.gen'
import type { DocumentOut } from '../../../generated/types.gen'

const LIVE_STATUSES = new Set(['queued', 'parsing', 'embedding'])

export function shouldPoll(documents: DocumentOut[] | undefined): boolean {
  return (documents ?? []).some((doc) => LIVE_STATUSES.has(doc.status))
}

export function useDocuments(collectionId: string | null) {
  return useQuery({
    queryKey: ['collections', collectionId, 'documents'],
    enabled: collectionId !== null,
    queryFn: async () =>
      (
        await getCollectionDocumentsCollectionsCollectionIdDocumentsGet({
          path: { collection_id: collectionId! },
        })
      ).data ?? [],
    refetchInterval: (query) => (shouldPoll(query.state.data) ? 2000 : false),
  })
}

export function useUploadDocument(collectionId: string | null) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (file: File) => {
      const { data, error } = await uploadDocumentCollectionsCollectionIdDocumentsPost({
        path: { collection_id: collectionId! },
        body: { file },
      })
      if (error) throw error
      return data
    },
    onSuccess: () =>
      void queryClient.invalidateQueries({
        queryKey: ['collections', collectionId, 'documents'],
      }),
  })
}

function useDocumentMutation<TVariables>(
  collectionId: string | null,
  mutationFn: (variables: TVariables) => Promise<DocumentOut | undefined>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['collections', collectionId, 'documents'],
      })
      void queryClient.invalidateQueries({ queryKey: ['collections'] })
    },
  })
}

export function usePatchDocumentTags(collectionId: string | null) {
  return useDocumentMutation(
    collectionId,
    async ({ documentId, tags }: { documentId: string; tags: string[] }) => {
      const { data, error } = await patchDocumentDocumentsDocumentIdPatch({
        path: { document_id: documentId },
        body: { tags },
      })
      if (error) throw error
      return data
    },
  )
}

export function useDeleteDocument(collectionId: string | null) {
  return useDocumentMutation(collectionId, async (documentId: string) => {
    const { error } = await deleteDocumentDocumentsDocumentIdDelete({
      path: { document_id: documentId },
    })
    if (error) throw error
    return undefined
  })
}

export function useReindexDocument(collectionId: string | null) {
  return useDocumentMutation(collectionId, async (documentId: string) => {
    const { data, error } = await reindexDocumentDocumentsDocumentIdReindexPost({
      path: { document_id: documentId },
    })
    if (error) throw error
    return data
  })
}

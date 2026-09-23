import { useQuery } from '@tanstack/react-query'

import { getDocumentChunksDocumentsDocumentIdChunksGet } from '../../../generated/sdk.gen'

export function useDocumentChunks(documentId: string | null, live: boolean) {
  return useQuery({
    queryKey: ['documents', documentId, 'chunks'],
    enabled: documentId !== null,
    queryFn: async () =>
      (
        await getDocumentChunksDocumentsDocumentIdChunksGet({
          path: { document_id: documentId! },
        })
      ).data ?? [],
    refetchInterval: live ? 2000 : false,
  })
}

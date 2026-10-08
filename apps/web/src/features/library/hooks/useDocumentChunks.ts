import { useQuery } from '@tanstack/react-query'

import { getDocumentChunksDocumentsDocumentIdChunksGet } from '../../../generated/sdk.gen'
import { unwrap } from '../../../lib/api'

export function useDocumentChunks(documentId: string | null, live: boolean) {
  return useQuery({
    queryKey: ['documents', documentId, 'chunks'],
    enabled: documentId !== null,
    // As in `useChatList`: `?? []` made a failed read indistinguishable from a
    // document with no extractable text (item 6).
    queryFn: async () =>
      unwrap(
        await getDocumentChunksDocumentsDocumentIdChunksGet({
          path: { document_id: documentId! },
        }),
      ),
    refetchInterval: live ? 2000 : false,
  })
}

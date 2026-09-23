import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createCollectionCollectionsPost,
  deleteCollectionCollectionsCollectionIdDelete,
  listCollectionsCollectionsGet,
  patchCollectionCollectionsCollectionIdPatch,
} from '../../../generated/sdk.gen'

export function useCollections() {
  return useQuery({
    queryKey: ['collections'],
    queryFn: async () => (await listCollectionsCollectionsGet()).data ?? [],
  })
}

export function useCreateCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (name: string) => {
      const { data, error } = await createCollectionCollectionsPost({ body: { name } })
      if (error) throw error
      return data
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['collections'] }),
  })
}

export function usePatchCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      collectionId,
      patch,
    }: {
      collectionId: string
      patch: { name?: string | null; visibility?: string | null }
    }) => {
      const { data, error } = await patchCollectionCollectionsCollectionIdPatch({
        path: { collection_id: collectionId },
        body: patch,
      })
      if (error) throw error
      return data
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['collections'] }),
  })
}

export function useDeleteCollection() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (collectionId: string) => {
      const { error } = await deleteCollectionCollectionsCollectionIdDelete({
        path: { collection_id: collectionId },
      })
      if (error) throw error
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['collections'] }),
  })
}

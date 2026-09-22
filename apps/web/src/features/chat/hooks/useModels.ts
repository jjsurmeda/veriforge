import { useQuery } from '@tanstack/react-query'

import { listModelsModelsGet } from '../../../generated/sdk.gen'

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    queryFn: async () => (await listModelsModelsGet()).data ?? [],
    staleTime: 60_000,
  })
}

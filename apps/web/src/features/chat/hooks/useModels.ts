import { useQuery } from '@tanstack/react-query'

import { listModelsModelsGet } from '../../../generated/sdk.gen'
import { unwrap } from '../../../lib/api'

export function useModels() {
  return useQuery({
    queryKey: ['models'],
    // As in `useChatList`: a swallowed failure became an empty catalogue, and
    // the picker then reported "No models match" (item 6).
    queryFn: async () => unwrap(await listModelsModelsGet()),
    staleTime: 60_000,
  })
}

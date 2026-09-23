import { useQuery } from '@tanstack/react-query'

import { getQuotaMeQuotaGet } from '../../../generated/sdk.gen'

export function useQuota(mode: 'fast' | 'auto' | 'deep' = 'auto') {
  return useQuery({
    queryKey: ['quota', mode],
    queryFn: async () => {
      const { data, error } = await getQuotaMeQuotaGet({ query: { mode } })
      if (error) throw error
      return data
    },
    staleTime: 15_000,
  })
}

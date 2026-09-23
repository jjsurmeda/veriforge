import { useQuery } from '@tanstack/react-query'

import { meMeGet } from '../../../generated/sdk.gen'

export function useMe() {
  return useQuery({
    queryKey: ['me'],
    queryFn: async () => {
      const { data, error } = await meMeGet()
      if (error) throw error
      return data
    },
    staleTime: 60_000,
  })
}

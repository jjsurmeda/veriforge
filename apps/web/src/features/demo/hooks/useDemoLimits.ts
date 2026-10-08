import { useQuery } from '@tanstack/react-query'

import { demoLimitsAuthDemoLimitsGet } from '../../../generated/sdk.gen'

export interface DemoLimits {
  role: string
  is_demo: boolean
  allow_deep: boolean
  allow_web: boolean
  allow_upload: boolean
  plan: string
}

/** What this account may do, read from the server (item 4).
 *
 *  One source of truth, on purpose. The demo limits endpoint returns the same
 *  settings the run route enforces, so the composer cannot offer a Deep or Web
 *  toggle the server will refuse, and cannot hide one it will accept. The
 *  query is cheap and cached for the session; on a read failure the caller
 *  gets `null`, which the composer treats as "not a demo account" — the
 *  permissive default, so a network blip does not hide controls from a real
 *  user.
 */
export function useDemoLimits() {
  return useQuery<DemoLimits | null>({
    queryKey: ['demo-limits'],
    queryFn: async () => {
      const { data, error } = await demoLimitsAuthDemoLimitsGet()
      if (error || !data) return null
      // The endpoint's response model is an untyped dict (a read-only summary,
      // not a product model), so the shape is asserted here rather than
      // generated. Read defensively: a missing key means "not a demo account",
      // which is the permissive default and never hides a real user's control.
      const row = data as Record<string, unknown>
      return {
        role: String(row.role ?? 'user'),
        is_demo: row.is_demo === true,
        allow_deep: row.allow_deep !== false,
        allow_web: row.allow_web !== false,
        allow_upload: row.allow_upload !== false,
        plan: String(row.plan ?? 'free'),
      } satisfies DemoLimits
    },
    staleTime: 5 * 60 * 1000,
  })
}
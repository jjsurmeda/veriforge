import { useShallow } from 'zustand/react/shallow'

import { useChatRunStore } from '../../chat/store'

export function useTrace(runId: string | null) {
  return useChatRunStore(
    useShallow((s) => {
      if (!runId) return undefined
      const run = s.runs[runId]
      if (!run) return undefined
      return {
        steps: run.steps,
        plan: run.plan,
        decisions: run.decisions,
        thinking: run.thinking,
        abstain: run.abstain,
        conflict: run.conflict,
        chunks: run.chunks,
        metrics: run.metrics,
        claims: run.claims,
        hold: run.hold,
        revision: run.revision,
        suggestions: run.suggestions,
        streaming: run.status === 'streaming' || run.status === 'connecting',
      }
    }),
  )
}

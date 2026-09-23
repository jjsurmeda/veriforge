import { useChatRunStore } from '../../chat/store'

export function useTrace(runId: string | null) {
  return useChatRunStore((s) => {
    if (!runId) return undefined
    const run = s.runs[runId]
    if (!run) return undefined
    return {
      steps: run.steps,
      decisions: run.decisions,
      thinking: run.thinking,
      abstain: run.abstain,
      conflict: run.conflict,
      streaming: run.status === 'streaming' || run.status === 'connecting',
    }
  })
}

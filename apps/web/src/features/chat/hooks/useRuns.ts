import { useMutation } from '@tanstack/react-query'

import {
  cancelRunRunsRunIdCancelPost,
  createRunChatsChatIdRunsPost,
} from '../../../generated/sdk.gen'
import type { RunFilters } from '../../../generated/types.gen'
import type { RunMode, RunSource } from '../components/ChatComposer'

interface CreateRunOptions {
  message: string
  modelId?: string | null
  mode?: RunMode
  source?: RunSource
  filters?: RunFilters
}

export function useCreateRun(chatId: string) {
  return useMutation({
    mutationFn: async ({ message, modelId, mode, source, filters }: CreateRunOptions) => {
      const { data, error } = await createRunChatsChatIdRunsPost({
        path: { chat_id: chatId },
        body: {
          message,
          model_id: modelId ?? null,
          mode: mode ?? 'auto',
          source: source ?? 'upload',
          filters: filters ?? null,
        },
      })
      if (error) throw error
      return data
    },
  })
}

export function useCancelRun() {
  return useMutation({
    mutationFn: async (runId: string) => {
      const { error } = await cancelRunRunsRunIdCancelPost({ path: { run_id: runId } })
      if (error) throw error
    },
  })
}

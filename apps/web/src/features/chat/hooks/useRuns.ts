import { useMutation } from '@tanstack/react-query'

import {
  cancelRunRunsRunIdCancelPost,
  createRunChatsChatIdRunsPost,
} from '../../../generated/sdk.gen'

export function useCreateRun(chatId: string) {
  return useMutation({
    mutationFn: async ({ message, modelId }: { message: string; modelId?: string | null }) => {
      const { data, error } = await createRunChatsChatIdRunsPost({
        path: { chat_id: chatId },
        body: { message, model_id: modelId ?? null, mode: 'fast' },
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

import { useMutation } from '@tanstack/react-query'

import {
  cancelRunRunsRunIdCancelPost,
  createRunChatsChatIdRunsPost,
} from '../../../generated/sdk.gen'

interface CreateRunOptions {
  message: string
  modelId?: string | null
  mode?: 'fast' | 'auto' | 'deep'
  source?: 'auto' | 'upload' | 'web' | 'both'
  collectionIds?: string[]
}

export function useCreateRun(chatId: string) {
  return useMutation({
    mutationFn: async ({
      message,
      modelId,
      mode,
      source,
      collectionIds,
    }: CreateRunOptions) => {
      const { data, error } = await createRunChatsChatIdRunsPost({
        path: { chat_id: chatId },
        body: {
          message,
          model_id: modelId ?? null,
          mode: mode ?? 'auto',
          source: source ?? 'auto',
          collection_ids: collectionIds ?? null,
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

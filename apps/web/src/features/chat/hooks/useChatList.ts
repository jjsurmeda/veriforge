import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createChatChatsPost,
  deleteChatChatsChatIdDelete,
  listChatsChatsGet,
  patchChatChatsChatIdPatch,
} from '../../../generated/sdk.gen'
import { unwrap } from '../../../lib/api'

interface CreateChatOptions {
  title?: string | null
}

export function useChatList() {
  return useQuery({
    queryKey: ['chats'],
    // `?? []` turned every failed list into an empty one, so the sidebar read
    // "No chats yet." — a claim about the account — whenever the request
    // failed. `unwrap` lets the failure reach React Query (item 6).
    queryFn: async () => unwrap(await listChatsChatsGet()),
  })
}

export function useCreateChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (options?: CreateChatOptions) => {
      const { data, error } = await createChatChatsPost({
        body: { title: options?.title ?? null },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['chats'] }),
  })
}

export function useDeleteChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (chatId: string) => {
      const { error } = await deleteChatChatsChatIdDelete({ path: { chat_id: chatId } })
      if (error) throw error
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['chats'] }),
  })
}

export function usePatchChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({
      chatId,
      patch,
    }: {
      chatId: string
      patch: {
        title?: string | null
        pinned?: boolean | null
        model_id?: string | null
      }
    }) => {
      const { data, error } = await patchChatChatsChatIdPatch({
        path: { chat_id: chatId },
        body: patch,
      })
      if (error) throw error
      return data
    },
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['chats'] })
      void queryClient.invalidateQueries({ queryKey: ['chat', variables.chatId] })
    },
  })
}

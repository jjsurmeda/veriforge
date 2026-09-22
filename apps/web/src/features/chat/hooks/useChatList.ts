import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createChatChatsPost,
  deleteChatChatsChatIdDelete,
  listChatsChatsGet,
  patchChatChatsChatIdPatch,
} from '../../../generated/sdk.gen'

export function useChatList() {
  return useQuery({
    queryKey: ['chats'],
    queryFn: async () => (await listChatsChatsGet()).data ?? [],
  })
}

export function useCreateChat() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (title?: string) => {
      const { data, error } = await createChatChatsPost({ body: { title: title ?? null } })
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
      patch: { title?: string | null; pinned?: boolean | null; model_id?: string | null }
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

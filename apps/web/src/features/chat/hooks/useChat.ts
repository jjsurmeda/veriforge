import { useQuery } from '@tanstack/react-query'

import { getChatChatsChatIdGet, listMessagesChatsChatIdMessagesGet } from '../../../generated/sdk.gen'

export function useChat(chatId: string | null) {
  return useQuery({
    queryKey: ['chat', chatId],
    queryFn: async () => {
      const { data, error } = await getChatChatsChatIdGet({ path: { chat_id: chatId! } })
      if (error) throw error
      return data
    },
    enabled: chatId !== null,
  })
}

export function useMessages(chatId: string | null) {
  return useQuery({
    queryKey: ['messages', chatId],
    queryFn: async () => {
      const { data, error } = await listMessagesChatsChatIdMessagesGet({
        path: { chat_id: chatId! },
      })
      if (error) throw error
      return data
    },
    enabled: chatId !== null,
  })
}

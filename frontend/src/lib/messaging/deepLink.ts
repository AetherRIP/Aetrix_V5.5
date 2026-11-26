/** A notification or compatibility link opens the header messaging panel. */
export const OPEN_MESSAGES_EVENT = 'aetrix:open-messages'
export function requestOpenMessages() {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new Event(OPEN_MESSAGES_EVENT))
}

export const OPEN_CONVERSATION_KEY = 'aetrix:open-message-conversation'
export const OPEN_CONVERSATION_EVENT = 'aetrix:open-message-conversation'

export type OpenConversationDetail = { conversationId: string }

export function requestOpenConversation(conversationId: string) {
  if (typeof window === 'undefined') return
  window.sessionStorage.setItem(OPEN_CONVERSATION_KEY, conversationId)
  window.dispatchEvent(
    new CustomEvent<OpenConversationDetail>(OPEN_CONVERSATION_EVENT, {
      detail: { conversationId },
    }),
  )
}

/** Read a conversation request left before the messaging panel mounted. */
export function takeOpenConversationRequest(): string | null {
  if (typeof window === 'undefined') return null
  const conversationId = window.sessionStorage.getItem(OPEN_CONVERSATION_KEY)
  window.sessionStorage.removeItem(OPEN_CONVERSATION_KEY)
  return conversationId
}

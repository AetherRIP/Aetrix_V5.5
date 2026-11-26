import { env, isApiConfigured } from '../env'

/**
 * Server-sent event stream for messaging.
 *
 * The engine emits one event per persisted row change, woken by a PostgreSQL
 * notification inside the committing transaction. A browser `EventSource`
 * cannot attach the bearer token, so this reads the same endpoint with `fetch`
 * and parses the frames itself.
 *
 * Reconnection is owned here: a drop retries with capped backoff and the caller
 * is told to reconcile from stored history, which is what makes a missed event
 * recoverable rather than lost.
 */

export type MessagingStreamMessageEvent = {
  type: 'message'
  message_id: string
  conversation_id: string
  created_at: string
  sender_id: string
  sender_name: string
  body: string
  edited: boolean
  deleted: boolean
}

export type MessagingStreamNotificationEvent = {
  type: 'notification'
  notification_id: string
  conversation_id: string
  created_at: string
  kind: 'DIRECT' | 'MENTION' | 'REPLY' | 'ANNOUNCEMENT'
  message_id: string
  actor_name: string
  preview: string
}

export type MessagingStreamReconnectEvent = { type: 'reconnect' }

export type MessagingStreamEvent =
  | MessagingStreamMessageEvent
  | MessagingStreamNotificationEvent
  | MessagingStreamReconnectEvent

export type MessagingStreamHandlers = {
  onEvent: (event: MessagingStreamEvent) => void
  /** Called after a dropped stream is re-established, before new events. */
  onReconnect: () => void
}

const MAX_BACKOFF_MS = 5_000

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}

function parseFrame(frame: string): MessagingStreamEvent | null {
  let name = 'message'
  const data: string[] = []
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }
  if (name === 'reconnect') return { type: 'reconnect' }
  if (name !== 'message' && name !== 'notification') return null
  if (!data.length) return null
  try {
    const parsed = JSON.parse(data.join('\n')) as MessagingStreamEvent
    if (parsed?.type !== name) return null
    return parsed
  } catch {
    return null
  }
}

/**
 * Connect and keep reconnecting until `signal` is aborted. Returns immediately;
 * all work happens on the stream loop.
 */
export function openMessagingStream(
  token: string,
  handlers: MessagingStreamHandlers,
  signal: AbortSignal,
): void {
  if (!isApiConfigured) return

  void (async () => {
    let attempt = 0
    let dropped = false
    while (!signal.aborted) {
      let ok = false
      try {
        const response = await fetch(
          `${env.apiBaseUrl.replace(/\/$/, '')}/api/v1/messaging/stream`,
          {
            headers: { accept: 'text/event-stream', authorization: `Bearer ${token}` },
            cache: 'no-store',
            signal,
          },
        )
        if (response.ok && response.body) {
          if (dropped) handlers.onReconnect()
          dropped = false
          attempt = 0
          ok = true
          const reader = response.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''
          while (!signal.aborted) {
            const { done, value } = await reader.read()
            if (done) break
            buffer += decoder.decode(value, { stream: true })
            let split = buffer.indexOf('\n\n')
            while (split >= 0) {
              const frame = buffer.slice(0, split)
              buffer = buffer.slice(split + 2)
              if (frame.trim()) {
                const event = parseFrame(frame)
                if (event) handlers.onEvent(event)
              }
              split = buffer.indexOf('\n\n')
            }
          }
        }
      } catch {
        // Aborts and network failures both land here; the loop decides.
      }
      if (signal.aborted) return
      if (ok) dropped = true
      attempt += 1
      await wait(Math.min(1_000 * 2 ** (attempt - 1), MAX_BACKOFF_MS), signal)
    }
  })()
}

import { openMessagingStream, type MessagingStreamEvent } from './stream'

/**
 * One stream per signed-in session, shared by every component that needs it.
 *
 * The header panel and the notification bell both display delivered state; two
 * independent connections would double the server work and deliver each event
 * twice. This keeps a single connection alive while at least one subscriber
 * exists and closes it with the last one.
 */

type Listener = (event: MessagingStreamEvent) => void

const listeners = new Set<Listener>()
let controller: AbortController | null = null
let connectedToken: string | null = null

function broadcast(event: MessagingStreamEvent) {
  for (const listener of [...listeners]) listener(event)
}

export function subscribeMessagingStream(token: string, listener: Listener): () => void {
  listeners.add(listener)
  if (!controller || connectedToken !== token) {
    controller?.abort()
    connectedToken = token
    const local = new AbortController()
    controller = local
    openMessagingStream(
      token,
      {
        onEvent: (event) => broadcast(event),
        onReconnect: () => broadcast({ type: 'reconnect' }),
      },
      local.signal,
    )
  }
  return () => {
    listeners.delete(listener)
    if (listeners.size === 0) {
      controller?.abort()
      controller = null
      connectedToken = null
    }
  }
}

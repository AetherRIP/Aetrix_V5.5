import { createFileRoute } from '@tanstack/react-router'
import { requestOpenMessages } from '../lib/messaging/deepLink'

export const Route = createFileRoute('/_app/messages')({
  component: MessagesLanding,
})

/**
 * Kept so existing links to /messages still resolve. Messaging itself is a
 * global header utility; this route only points at it and never hosts a
 * second messaging workspace.
 */
function MessagesLanding() {
  return (
    <div className="app-stack">
      <section className="msgp-landing">
        <p className="mono msgp__eyebrow">Workspace messaging</p>
        <h1>Messages live in the header.</h1>
        <p>
          Open the messages icon beside notifications to read your direct conversations and
          workspace channels, or to start a new one, without leaving the page you are working on.
        </p>
        <button type="button" className="btn btn--primary" onClick={() => requestOpenMessages()}>
          Open messages
        </button>
      </section>
    </div>
  )
}

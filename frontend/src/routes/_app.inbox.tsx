import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/inbox')({
  component: Inbox,
})

function Inbox() {
  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Inbox filters">
        <div className="app-toolbar__tabs" role="group" aria-label="Filter">
          <button type="button" className="app-tab is-active" disabled>
            All
          </button>
          <button type="button" className="app-tab" disabled>
            Needs review
          </button>
          <button type="button" className="app-tab" disabled>
            Failed
          </button>
        </div>
        <p className="app-toolbar__note mono">Filters activate with the engine API</p>
      </div>

      <StatePanel
        tone="wip"
        title="Nothing can be delivered to the inbox yet"
        capability="GET /api/v1/workspaces/{id}/inbox"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          The inbox carries exactly two kinds of real event: a job that the pipeline
          parked for a person, and a job that failed. Both are produced by the
          correction pipeline, which is still unimplemented — so this list is
          genuinely empty, not hidden.
        </p>
      </StatePanel>
    </div>
  )
}

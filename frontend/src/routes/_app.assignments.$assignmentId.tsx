import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/assignments/$assignmentId')({
  component: AssignmentDetail,
})

function AssignmentDetail() {
  const { assignmentId } = Route.useParams()

  return (
    <div className="app-stack">
      <section className="record-head" aria-label="Assignment record">
        <div>
          <p className="record-head__kicker mono">Assignment</p>
          <p className="record-head__id mono">{assignmentId}</p>
        </div>
        <div className="record-head__meta">
          <span className="chip app-chip" data-tone="attention">
            Not loaded
          </span>
          <Link className="btn btn--small btn--outline" to="/assignments">
            Back to assignments
          </Link>
        </div>
      </section>

      <StatePanel
        tone="wip"
        title="This record has no content until the engine answers"
        capability="GET /api/v1/assignments/{id}"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          The route, layout and tab structure exist so the page survives a refresh and
          is ready for integration. Nothing about this assignment — its exam, state or
          submissions — is invented.
        </p>
      </StatePanel>

      <div className="app-tabs" role="tablist" aria-label="Assignment sections">
        <button type="button" role="tab" aria-selected="true" className="app-tab is-active" disabled>
          Overview
        </button>
        <button type="button" role="tab" aria-selected="false" className="app-tab" disabled>
          Submissions
        </button>
        <button type="button" role="tab" aria-selected="false" className="app-tab" disabled>
          Marking
        </button>
      </div>

      <div className="app-split">
        <section className="app-card" aria-labelledby="assignment-blueprint-title">
          <h2 className="app-card__title" id="assignment-blueprint-title">
            Blueprint
          </h2>
          <p className="app-card__body">
            Question-level structure comes from an approved blueprint version. Approval
            and immutable versioning already exist in the engine; the read endpoint is
            not hosted yet.
          </p>
        </section>

        <section className="app-card" aria-labelledby="assignment-scheme-title">
          <h2 className="app-card__title" id="assignment-scheme-title">
            Mark scheme
          </h2>
          <p className="app-card__body">
            The scheme is uploaded as a draft and approved explicitly. No scheme is
            attached to this record until the engine reports one.
          </p>
        </section>
      </div>
    </div>
  )
}

import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/submissions/$submissionId')({
  component: SubmissionReview,
})

function SubmissionReview() {
  const { submissionId } = Route.useParams()

  return (
    <div className="app-stack">
      <section className="record-head" aria-label="Submission record">
        <div>
          <p className="record-head__kicker mono">Submission</p>
          <p className="record-head__id mono">{submissionId}</p>
        </div>
        <div className="record-head__meta">
          <span className="chip app-chip" data-tone="attention">
            Not loaded
          </span>
          <Link className="btn btn--small btn--outline" to="/queue">
            Back to queue
          </Link>
        </div>
      </section>

      <StatePanel
        tone="wip"
        title="Correction review is blocked twice over"
        capability="correction pipeline + GET /api/v1/submissions/{id}"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          Even with the API hosted, this screen shows nothing until the correction
          pipeline exists: a submission has pages and a quality report, but the marks,
          evidence and review decisions are produced by marking. Aetrix does not render
          placeholder marks.
        </p>
      </StatePanel>

      <div className="app-split">
        <section className="app-card" aria-labelledby="submission-pages-title">
          <h2 className="app-card__title" id="submission-pages-title">
            Pages
          </h2>
          <div className="page-grid" aria-label="Page thumbnails, unavailable">
            {Array.from({ length: 6 }).map((_, index) => (
              <div className="page-grid__cell" key={index} aria-hidden="true">
                <span className="mono">{index + 1}</span>
              </div>
            ))}
          </div>
          <p className="app-card__body">
            Empty page frames, not fabricated scans: page images are served by the
            engine's storage adapter once a submission is ingested.
          </p>
        </section>

        <section className="app-card" aria-labelledby="submission-marks-title">
          <h2 className="app-card__title" id="submission-marks-title">
            Marking evidence
          </h2>
          <p className="app-card__body">
            Question-level marks, confidence and examiner evidence will appear here when
            the pipeline produces them. Nothing is estimated.
          </p>
        </section>
      </div>
    </div>
  )
}

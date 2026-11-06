import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/reports')({
  component: Reports,
})

function Reports() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="No reports can exist yet"
        capability="correction results + GET /api/v1/workspaces/{id}/reports"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          Reports summarise correction results. The engine has no result endpoint
          because it has no marking step, so there is nothing to summarise. Charts and
          cohort tables are deliberately absent rather than populated with sample data.
        </p>
      </StatePanel>

      <section className="app-card" aria-labelledby="reports-plan-title">
        <h2 className="app-card__title" id="reports-plan-title">
          What a report will contain
        </h2>
        <ul className="app-list">
          <li>Per-question facility and discrimination for a cohort</li>
          <li>Examiner-reviewed exceptions and their resolutions</li>
          <li>Confidence distribution and escalation history</li>
          <li>Exportable evidence trail for moderation</li>
        </ul>
        <p className="app-card__body">
          This is the intended contract, not a rendering of live data.
        </p>
      </section>
    </div>
  )
}

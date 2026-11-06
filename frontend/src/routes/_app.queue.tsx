import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/queue')({
  component: Queue,
})

const COLUMNS = ['Job', 'Submission', 'State', 'Attempts', 'Updated'] as const

function Queue() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="The marking queue has no jobs to lease"
        capability="GET /api/v1/workspaces/{id}/corrections"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          The engine already implements the job state machine and the leasing
          protocol, but its correction pipeline is deliberately unavailable: a claimed
          job is parked with <code>PIPELINE_UNAVAILABLE</code> instead of producing a
          mark. No queue rows are simulated here.
        </p>
      </StatePanel>

      <section className="app-card" aria-labelledby="queue-table-title">
        <h2 className="app-card__title" id="queue-table-title">
          Queue structure
        </h2>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">
              Marking queue, awaiting engine connection
            </caption>
            <thead>
              <tr>
                {COLUMNS.map((column) => (
                  <th key={column} scope="col">
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td colSpan={COLUMNS.length} className="data-table__empty">
                  No rows — the API is not deployed, so no job data exists to display.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}

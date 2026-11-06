import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/assignments')({
  component: Assignments,
})

const COLUMNS = ['Assignment', 'Exam', 'State', 'Submissions', 'Blueprint'] as const

function Assignments() {
  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Assignment actions">
        <p className="app-toolbar__note mono">
          Assignments bind an approved blueprint and a mark scheme to a cohort.
        </p>
        <button type="button" className="btn btn--small btn--primary" disabled>
          New assignment
        </button>
      </div>

      <StatePanel
        tone="wip"
        title="Assignments are stored by the engine"
        capability="GET /api/v1/workspaces/{id}/assignments"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          Creation is disabled rather than faked: an assignment needs an approved
          blueprint version and a mark scheme, both of which live behind the same
          undelivered API.
        </p>
      </StatePanel>

      <section className="app-card" aria-labelledby="assignments-table-title">
        <h2 className="app-card__title" id="assignments-table-title">
          Assignment list
        </h2>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">
              Assignments, awaiting engine connection
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
                  No rows — assignment records are served by the engine, which is not
                  deployed.
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <p className="app-hint">
        The detail view is routable now. Open an example record path to see the layout:{' '}
        <Link to="/assignments/$assignmentId" params={{ assignmentId: 'example' }}>
          /assignments/example
        </Link>
      </p>
    </div>
  )
}

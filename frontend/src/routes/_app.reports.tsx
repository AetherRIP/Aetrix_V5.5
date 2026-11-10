import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { ReportRow } from '../lib/api/types'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/reports')({
  component: Reports,
})

function percent(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(1)}%`
}

function Reports() {
  const session = useEngineSession()
  const [state, reload] = useResource<ReportRow[]>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => workspaceService.reports(session.tenantId!, { token: session.token, signal })
      : null,
  )

  const rows = state.state === 'ok' ? state.data : []
  const sufficient = rows.filter((row) => row.state === 'OK')

  return (
    <div className="app-stack">
      <DataState state={state} capability="GET /api/v1/workspaces/{id}/reports">
        <Panel title="Assignment reports" note={`${rows.length} assignment(s)`}>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">
                Per-assignment marking summary for this workspace
              </caption>
              <thead>
                <tr>
                  <th scope="col">Assignment</th>
                  <th scope="col">Submissions</th>
                  <th scope="col">Completed jobs</th>
                  <th scope="col">Awaiting review</th>
                  <th scope="col">Failed</th>
                  <th scope="col">Approved</th>
                  <th scope="col">Mean</th>
                  <th scope="col">Cohort</th>
                </tr>
              </thead>
              <tbody>
                {rows.length > 0 ? (
                  rows.map((row) => (
                    <tr key={row.assignment_id}>
                      <th scope="row">{row.name}</th>
                      <td className="mono">{row.submissions}</td>
                      <td className="mono">{row.jobs_completed}</td>
                      <td className="mono">{row.awaiting_review}</td>
                      <td className="mono">{row.failed}</td>
                      <td className="mono">{row.approved}</td>
                      <td className="mono">{percent(row.mean_percent)}</td>
                      <td>
                        <span
                          className="chip app-chip"
                          data-tone={row.state === 'OK' ? 'ok' : 'attention'}
                        >
                          {row.state === 'OK' ? 'Reportable' : 'Insufficient data'}
                        </span>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={8} className="data-table__empty">
                      No assignments yet, so there is nothing to report on.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          <div className="app-inline-actions">
            <button type="button" className="btn btn--small btn--outline" onClick={reload}>
              Refresh
            </button>
          </div>
          <p className="app-hint">
            Counts come from the engine's own tables. Mean percentages are computed from approved
            marks only; a dash means no approved marks exist, not a zero.
          </p>
        </Panel>
      </DataState>

      {state.state === 'ok' && rows.length > 0 && sufficient.length === 0 ? (
        <StatePanel tone="empty" title="No cohort is reportable yet">
          <p>
            Every assignment reports <code>INSUFFICIENT_DATA</code>. Cohort statistics need
            completed, approved results; per-question facility and discrimination stay absent until
            then rather than being estimated.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

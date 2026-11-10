import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { JobState, MarkingHistoryPage } from '../lib/api/types'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/history')({
  component: MarkingHistory,
})

const PAGE_SIZE = 20

const FILTERS: { id: string; label: string }[] = [
  { id: '', label: 'All' },
  { id: 'COMPLETED', label: 'Completed' },
  { id: 'REVIEW_REQUIRED', label: 'Needs review' },
  { id: 'FAILED', label: 'Failed' },
]

function tone(state: JobState): 'ok' | 'attention' | 'neutral' {
  if (state === 'COMPLETED') return 'ok'
  if (state === 'FAILED' || state === 'REVIEW_REQUIRED' || state === 'RETRY_SUSPENDED') {
    return 'attention'
  }
  return 'neutral'
}

function MarkingHistory() {
  const session = useEngineSession()
  const [state, setState] = useState('')
  const [offset, setOffset] = useState(0)
  const [page, reload] = useResource<MarkingHistoryPage>(
    `history:${session.tenantId ?? 'none'}:${state}:${offset}`,
    session.tenantId
      ? (signal) =>
          workspaceService.markingHistory(
            session.tenantId!,
            { limit: PAGE_SIZE, offset, state: state || undefined },
            { token: session.token, signal },
          )
      : null,
  )

  const rows = page.state === 'ok' ? page.data.items : []
  const total = page.state === 'ok' ? page.data.total : 0
  const from = rows.length > 0 ? offset + 1 : 0
  const to = offset + rows.length

  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Marking history filters">
        <div className="app-toolbar__tabs" role="group" aria-label="Filter by job state">
          {FILTERS.map((entry) => (
            <button
              key={entry.id || 'all'}
              type="button"
              className={entry.id === state ? 'app-tab is-active' : 'app-tab'}
              aria-pressed={entry.id === state}
              onClick={() => {
                setState(entry.id)
                setOffset(0)
              }}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <button type="button" className="btn btn--small btn--outline" onClick={reload}>
          Refresh
        </button>
      </div>

      <DataState state={page} capability="GET /api/v1/workspaces/{id}/marking-history">
        <Panel title="Marking history" note={`${from}–${to} of ${total}`}>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">
                Correction jobs, their marks and approval state
              </caption>
              <thead>
                <tr>
                  <th scope="col">Student</th>
                  <th scope="col">Assignment</th>
                  <th scope="col">State</th>
                  <th scope="col">Marks</th>
                  <th scope="col">Review</th>
                  <th scope="col">Approved</th>
                  <th scope="col">Updated</th>
                </tr>
              </thead>
              <tbody>
                {rows.length > 0 ? (
                  rows.map((row) => (
                    <tr key={row.job_id}>
                      <th scope="row">
                        <Link
                          to="/submissions/$submissionId"
                          params={{ submissionId: row.submission_id }}
                        >
                          {row.student_ref ?? row.submission_id.slice(0, 8)}
                        </Link>
                      </th>
                      <td>{row.assignment_name ?? '—'}</td>
                      <td>
                        <span className="chip app-chip" data-tone={tone(row.state)}>
                          {row.state}
                        </span>
                        {row.error_code ? (
                          <span className="mono app-hint"> {row.error_code}</span>
                        ) : null}
                      </td>
                      <td className="mono">
                        {row.total > 0 ? `${row.awarded}/${row.total}` : '—'}
                      </td>
                      <td className="mono">{row.review_required}</td>
                      <td>
                        {row.approved
                          ? row.approved_by_label ?? 'approved'
                          : 'not approved'}
                      </td>
                      <td className="mono">{new Date(row.updated_at).toLocaleString()}</td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={7} className="data-table__empty">
                      No correction jobs match this filter. A job appears once a submission is
                      queued; its marks appear when the engine stores results.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="app-inline-actions">
            <button
              type="button"
              className="btn btn--small btn--outline"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn btn--small btn--outline"
              disabled={offset + PAGE_SIZE >= total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Next
            </button>
          </div>
        </Panel>
      </DataState>

      {page.state === 'ok' && total === 0 ? (
        <StatePanel tone="empty" title="No marking history yet">
          <p>
            Nothing has been queued in this workspace. This list reads stored correction jobs,
            question results and approvals — it is never seeded with examples.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { InboxItem } from '../lib/api/types'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/inbox')({
  component: Inbox,
})

type Filter = 'all' | 'review' | 'failed'

function Inbox() {
  const session = useEngineSession()
  const [filter, setFilter] = useState<Filter>('all')
  const [state, reload] = useResource<InboxItem[]>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => workspaceService.inbox(session.tenantId!, { token: session.token, signal })
      : null,
  )

  const items = state.state === 'ok' ? state.data : []
  const shown = items.filter((item) =>
    filter === 'all'
      ? true
      : filter === 'review'
        ? item.kind === 'REVIEW_REQUIRED'
        : item.kind === 'JOB_FAILED',
  )

  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Inbox filters">
        <div className="app-toolbar__tabs" role="group" aria-label="Filter">
          {([
            ['all', 'All'],
            ['review', 'Needs review'],
            ['failed', 'Failed'],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={filter === id ? 'app-tab is-active' : 'app-tab'}
              aria-pressed={filter === id}
              onClick={() => setFilter(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="app-inline-actions">
          <Link className="btn btn--small btn--outline" to="/notifications">
            Notifications
          </Link>
          <button type="button" className="btn btn--small btn--outline" onClick={reload}>
            Refresh
          </button>
        </div>
      </div>

      <DataState state={state} capability="GET /api/v1/workspaces/{id}/inbox">
        <Panel title="Inbox" note={`${shown.length} item(s)`}>
          <ul className="app-list">
            {shown.length > 0 ? (
              shown.map((item) => (
                <li key={item.id}>
                  <span className="chip app-chip" data-tone={item.kind === 'JOB_FAILED' ? 'attention' : 'ok'}>
                    {item.kind === 'JOB_FAILED' ? 'Failed' : 'Review'}
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <span className="app-card__body">{item.detail}</span>
                    <span className="mono app-hint">
                      {' '}
                      {new Date(item.created_at).toLocaleString()} ·{' '}
                      {item.submission_id ? (
                        <Link
                          to="/submissions/$submissionId"
                          params={{ submissionId: item.submission_id }}
                        >
                          open submission
                        </Link>
                      ) : (
                        'no submission link'
                      )}
                    </span>
                  </span>
                </li>
              ))
            ) : (
              <li>
                No items match this filter. The inbox only carries two kinds of real event: a job
                the pipeline parked for a person, and a job that failed.
              </li>
            )}
          </ul>
          {items.length > 0 ? (
            <p className="app-hint">
              Read state is not tracked: the engine has no read-state table, so every item is
              reported with an unknown read flag rather than a fabricated one.
            </p>
          ) : null}
        </Panel>
      </DataState>

      {state.state === 'ok' && items.length === 0 ? (
        <StatePanel tone="empty" title="Nothing to deliver">
          <p>
            Review and failure events appear here as jobs are processed. An empty inbox means the
            engine reported no such events — not that this screen is switched off.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

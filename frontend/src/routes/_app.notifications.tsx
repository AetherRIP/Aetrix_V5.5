import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Notification } from '../lib/api/types'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/notifications')({
  component: Notifications,
})

type Filter = 'all' | 'work' | 'membership'

function tone(kind: Notification['kind']): 'ok' | 'attention' | 'neutral' {
  if (kind === 'JOB_FAILED') return 'attention'
  if (kind === 'REVIEW_REQUIRED') return 'attention'
  if (kind === 'RESULT_APPROVED') return 'ok'
  return 'neutral'
}

function Notifications() {
  const session = useEngineSession()
  const [filter, setFilter] = useState<Filter>('all')
  const [state, reload] = useResource<Notification[]>(
    `notifications:${session.tenantId ?? 'none'}`,
    session.tenantId
      ? (signal) =>
          workspaceService.notifications(session.tenantId!, {
            token: session.token,
            signal,
          })
      : null,
  )

  const items = state.state === 'ok' ? state.data : []
  const shown = items.filter((item) =>
    filter === 'all'
      ? true
      : filter === 'work'
        ? item.kind !== 'INVITATION_PENDING'
        : item.kind === 'INVITATION_PENDING',
  )

  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Notification filters">
        <div className="app-toolbar__tabs" role="group" aria-label="Filter notifications">
          {(
            [
              ['all', 'All'],
              ['work', 'Marking'],
              ['membership', 'Membership'],
            ] as const
          ).map(([id, label]) => (
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
        <button type="button" className="btn btn--small btn--outline" onClick={reload}>
          Refresh
        </button>
      </div>

      <DataState state={state} capability="GET /api/v1/workspaces/{id}/notifications">
        <Panel title="Notifications" note={`${shown.length} event(s)`}>
          {shown.length > 0 ? (
            <ul className="app-list">
              {shown.map((item) => (
                <li key={item.id}>
                  <span className="chip app-chip" data-tone={tone(item.kind)}>
                    {item.kind.replaceAll('_', ' ').toLowerCase()}
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <span className="app-card__body">{item.detail}</span>
                    <span className="mono app-hint">
                      {' '}
                      {new Date(item.created_at).toLocaleString()}
                      {item.submission_id ? (
                        <>
                          {' · '}
                          <Link
                            to="/submissions/$submissionId"
                            params={{ submissionId: item.submission_id }}
                          >
                            open submission
                          </Link>
                        </>
                      ) : null}
                      {item.invitation_id ? (
                        <>
                          {' · '}
                          <Link to="/assistants">manage invitations</Link>
                        </>
                      ) : null}
                    </span>
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="app-hint">
              No events match this filter. Notifications are derived from stored jobs, approvals
              and pending invitations — no sample rows are shown.
            </p>
          )}
          <p className="app-hint">
            Read state is not stored by the engine, so no item is marked read or unread.
          </p>
        </Panel>
      </DataState>

      {state.state === 'ok' && items.length === 0 ? (
        <StatePanel tone="empty" title="Nothing yet">
          <p>
            This workspace has no review, failure, approval or pending-invitation record. The
            screen will list one here as soon as the engine stores it.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

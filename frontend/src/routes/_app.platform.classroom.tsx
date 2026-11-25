import { useCallback, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useAuth } from '../lib/auth/AuthProvider'
import {
  adminCourses,
  adminSyncRuns,
  classroomConnection,
  disconnectClassroom,
  startClassroomOAuth,
  syncClassroom,
  type AdminCourse,
  type ClassroomConnection,
  type ClassroomSyncRun,
} from '../lib/api/classroom'
import { useResource } from '../lib/api/useResource'

export const Route = createFileRoute('/_app/platform/classroom')({
  component: PlatformClassroom,
})

type Notice = { tone: 'ok' | 'error'; message: string }

function formatMoment(value: string | null): string {
  if (!value) return 'never'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'unknown' : parsed.toLocaleString('en-GB')
}

function statusLabel(status: ClassroomConnection['status']): string {
  if (status === 'CONNECTED') return 'Connected'
  if (status === 'RECONNECT_REQUIRED') return 'Reconnect required'
  return 'Not connected'
}

function statusTone(status: string): 'ok' | 'attention' | 'neutral' {
  if (status === 'CONNECTED' || status === 'SUCCEEDED') return 'ok'
  if (status === 'RECONNECT_REQUIRED' || status === 'FAILED' || status === 'PARTIAL') {
    return 'attention'
  }
  return 'neutral'
}

/**
 * The platform's Google Classroom screen.
 *
 * One central Google account performs every Classroom operation, so this is the
 * only place a Classroom authorisation is started, refreshed, revoked or
 * reconnected.  The browser never receives a token: it receives the connection's
 * status, the scopes Google granted, the identity Google reported and what each
 * sync achieved.
 */
function PlatformClassroom() {
  const { session } = useAuth()
  const engine = useEngineSession()
  const token = session?.access_token ?? null
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [search, setSearch] = useState('')

  const [connection, reloadConnection] = useResource<ClassroomConnection>(
    `classroom-platform-connection:${token ?? 'anonymous'}`,
    token ? (signal) => classroomConnection({ token, signal }) : null,
  )
  const [courses, reloadCourses] = useResource<AdminCourse[]>(
    `classroom-platform-courses:${search}:${token ?? 'anonymous'}`,
    token ? (signal) => adminCourses(search, { token, signal }) : null,
  )
  const [runs, reloadRuns] = useResource<ClassroomSyncRun[]>(
    `classroom-platform-runs:${token ?? 'anonymous'}`,
    token ? (signal) => adminSyncRuns({ token, signal }) : null,
  )

  const refresh = useCallback(() => {
    reloadConnection()
    reloadCourses()
    reloadRuns()
  }, [reloadConnection, reloadCourses, reloadRuns])

  // Platform authority, not workspace seniority.  A platform administrator is
  // usually the OWNER of one workspace, so the workspace role cannot tell them
  // apart from a teacher-facing owner; the capability alone would miss an
  // administrator, who never carries it.  The engine refuses these routes
  // regardless, so this decides only what the screen offers.
  const platformAdmin =
    engine.me?.is_platform_admin === true || engine.capabilities.includes('platform_admin')

  if (engine.me?.role && !platformAdmin) {
    return (
      <StatePanel tone="error" title="Platform administration only">
        <p>
          The central Google Classroom connection is managed by platform owners and
          administrators. A workspace owner has no authority over it.
        </p>
      </StatePanel>
    )
  }

  const connect = async () => {
    if (!token) return
    setBusy('connect')
    setNotice(null)
    const result = await startClassroomOAuth({ token })
    if (result.status === 'ok') {
      window.location.assign(result.data.authorization_url)
      return
    }
    setBusy(null)
    setNotice({ tone: 'error', message: result.reason })
  }

  const runSync = async () => {
    if (!token) return
    setBusy('sync')
    setNotice(null)
    const result = await syncClassroom({ token })
    setBusy(null)
    if (result.status === 'ok') {
      setNotice({
        tone: 'ok',
        message:
          `Google listed ${result.data.counts.discovered} course(s): ` +
          `${result.data.counts.created} new, ${result.data.counts.updated} updated` +
          (result.data.truncated
            ? '. The configured ceiling stopped the read, so this list is partial.'
            : '.'),
      })
    } else {
      setNotice({ tone: 'error', message: result.reason })
    }
    refresh()
  }

  const disconnect = async () => {
    if (!token) return
    setBusy('disconnect')
    setNotice(null)
    const result = await disconnectClassroom({ token })
    setBusy(null)
    setConfirming(false)
    if (result.status === 'ok') {
      setNotice({
        tone: 'ok',
        message: result.data.revoked
          ? 'The central account was disconnected and Google confirmed the grant was revoked.'
          : 'The central account was disconnected here. Google did not confirm revocation; remove Aetrix from that Google account if the grant is still listed.',
      })
    } else {
      setNotice({ tone: 'error', message: result.reason })
    }
    refresh()
  }

  const connected = connection.state === 'ok' ? connection.data : null
  const locked = busy !== null

  return (
    <div className="app-stack">
      {notice ? (
        <div className="gem-notice" data-tone={notice.tone} role="status">
          {notice.message}
        </div>
      ) : null}

      <Panel title="Central Google account" note="One connection for the whole platform">
        {connection.state === 'loading' ? (
          <p className="panel-copy">Reading the central connection…</p>
        ) : connection.state === 'unavailable' || connection.state === 'error' ? (
          <p className="panel-copy">{connection.reason}</p>
        ) : connected ? (
          <>
            <div className="app-inline-actions">
              <StatusChip tone={statusTone(connected.status)}>
                {statusLabel(connected.status)}
              </StatusChip>
              <span className="gem-footnote">
                {connected.connected_account_email ?? 'Google did not report an address'}
              </span>
            </div>

            {!connected.configured ? (
              <p className="panel-copy">
                No Google OAuth client is configured on this deployment, so Classroom cannot be
                connected. The engine reports <code>CLASSROOM_NOT_CONFIGURED</code> instead of
                pretending an account exists.
              </p>
            ) : connected.status === 'RECONNECT_REQUIRED' ? (
              <p className="panel-copy">
                Google rejected the stored authorisation and its tokens were discarded.{' '}
                {connected.last_error_message ?? 'Connect the central account again.'}
              </p>
            ) : connected.status === 'NOT_CONNECTED' ? (
              <p className="panel-copy">
                No central Google account is connected. Connecting asks Google for course, roster,
                coursework, submission and Drive read access — the scopes the workflow below uses.
                Consenting grants Aetrix the ability to write coursework and grades to the classes
                that account teaches.
              </p>
            ) : (
              <p className="panel-copy">
                The authorisation is stored encrypted by the engine and refreshed before expiry.
                No token is ever sent to a browser.
              </p>
            )}

            <ul className="panel-copy">
              <li>
                Connected account:{' '}
                {connected.connected_account_name ?? connected.connected_account_email ?? 'unknown'}
              </li>
              <li>Authorised: {formatMoment(connected.connected_at)}</li>
              <li>Last token refresh: {formatMoment(connected.last_refresh_at)}</li>
              <li>Last course sync: {formatMoment(connected.last_synced_at)}</li>
              {connected.last_sync_status ? (
                <li>
                  Last sync outcome: {connected.last_sync_status}
                  {connected.last_sync_status === 'SUCCEEDED'
                    ? ` (${connected.last_sync_counts.discovered ?? 0} discovered)`
                    : ' — the connection was kept for another attempt'}
                </li>
              ) : null}
              {connected.last_error_code ? (
                <li>
                  Last error: {connected.last_error_code}
                  {connected.last_error_message ? ` — ${connected.last_error_message}` : ''}
                </li>
              ) : null}
            </ul>

            <details className="panel-copy">
              <summary>Google scopes</summary>
              <ul>
                {connected.required_scopes.map((scope) => (
                  <li key={scope} className="mono">
                    {scope}
                    {connected.granted_scopes.includes(scope) ? ' — granted' : ' — not granted'}
                  </li>
                ))}
              </ul>
              {connected.missing_scopes.length > 0 ? (
                <p>
                  Missing {connected.missing_scopes.length} scope(s). Authorise again and accept
                  every Classroom permission; an operation needing a missing scope is refused
                  rather than attempted.
                </p>
              ) : null}
            </details>

            <div className="app-inline-actions">
              {connected.configured &&
              (connected.status === 'NOT_CONNECTED' ||
                connected.status === 'RECONNECT_REQUIRED') ? (
                <button
                  type="button"
                  className="btn btn--small btn--primary"
                  onClick={() => void connect()}
                  disabled={locked}
                >
                  {busy === 'connect'
                    ? 'Opening Google…'
                    : connected.status === 'RECONNECT_REQUIRED'
                      ? 'Reconnect the central account'
                      : 'Connect the central account'}
                </button>
              ) : null}
              {connected.status === 'CONNECTED' ? (
                <button
                  type="button"
                  className="btn btn--small btn--primary"
                  onClick={() => void runSync()}
                  disabled={locked}
                >
                  {busy === 'sync' ? 'Reading courses…' : 'Synchronise courses'}
                </button>
              ) : null}
              {connected.status !== 'NOT_CONNECTED' ? (
                confirming ? (
                  <>
                    <button
                      type="button"
                      className="btn btn--small btn--danger"
                      onClick={() => void disconnect()}
                      disabled={locked}
                    >
                      {busy === 'disconnect' ? 'Disconnecting…' : 'Confirm disconnect'}
                    </button>
                    <button
                      type="button"
                      className="btn btn--small"
                      onClick={() => setConfirming(false)}
                      disabled={locked}
                    >
                      Cancel
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="btn btn--small"
                    onClick={() => setConfirming(true)}
                    disabled={locked}
                  >
                    Disconnect
                  </button>
                )
              ) : null}
            </div>
          </>
        ) : null}
      </Panel>

      <Panel
        title="Discovered courses"
        note={
          courses.state === 'ok'
            ? `${courses.data.length} shown · allocate on the Allocation screen`
            : 'Course discovery'
        }
      >
        <div className="app-inline-actions">
          <label className="app-form__label" htmlFor="classroom-search">
            Search courses
          </label>
          <input
            id="classroom-search"
            className="app-input"
            value={search}
            maxLength={200}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="name, section or course id"
          />
          <Link to="/platform/workspaces" className="btn btn--small">
            Open allocation
          </Link>
        </div>

        {courses.state === 'loading' ? (
          <p className="panel-copy">Reading discovered courses…</p>
        ) : courses.state === 'unavailable' || courses.state === 'error' ? (
          <p className="panel-copy">{courses.reason}</p>
        ) : courses.data.length === 0 ? (
          <p className="panel-copy">
            No course has been discovered yet. Connect the central account and synchronise: only
            courses Google actually lists are recorded, and they are marked VERIFIED.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Classroom courses known to the platform</caption>
              <thead>
                <tr>
                  <th scope="col">Course</th>
                  <th scope="col">Course ID</th>
                  <th scope="col">State</th>
                  <th scope="col">Teacher</th>
                  <th scope="col">Workspace</th>
                  <th scope="col">Last sync</th>
                </tr>
              </thead>
              <tbody>
                {courses.data.map((course) => (
                  <tr key={course.id}>
                    <td>
                      <span className="data-table__strong">{course.name}</span>
                      {course.section ? <span className="gem-footnote">{course.section}</span> : null}
                    </td>
                    <td className="mono">{course.course_id}</td>
                    <td>
                      <StatusChip tone={course.course_state === 'ACTIVE' ? 'ok' : 'attention'}>
                        {course.course_state}
                      </StatusChip>
                      <span className="gem-footnote">{course.verification}</span>
                    </td>
                    <td>{course.teacher_name ?? course.owner_email ?? '—'}</td>
                    <td>
                      {course.workspace_name ?? (
                        <span className="gem-footnote">not allocated</span>
                      )}
                    </td>
                    <td>{formatMoment(course.synced_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Synchronisation history" note="What each run actually achieved">
        {runs.state === 'loading' ? (
          <p className="panel-copy">Reading sync history…</p>
        ) : runs.state === 'unavailable' || runs.state === 'error' ? (
          <p className="panel-copy">{runs.reason}</p>
        ) : runs.data.length === 0 ? (
          <p className="panel-copy">No course discovery has run yet.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Course discovery runs</caption>
              <thead>
                <tr>
                  <th scope="col">Started</th>
                  <th scope="col">Status</th>
                  <th scope="col">Counts</th>
                  <th scope="col">Actor</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((run) => (
                  <tr key={run.id}>
                    <td>{formatMoment(run.started_at)}</td>
                    <td>
                      <StatusChip tone={statusTone(run.status)}>{run.status}</StatusChip>
                    </td>
                    <td>
                      {Object.entries(run.counts)
                        .map(([key, value]) => `${key}: ${value}`)
                        .join(', ') || '—'}
                    </td>
                    <td>{run.actor_subject ?? '—'}</td>
                    <td>{run.error_message ?? run.error_code ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <StatePanel tone="wip" title="What this connection can and cannot do" capability="classroom.courses · rosters · coursework · drive">
        <p>
          The central account reads courses, rosters, coursework and submissions, downloads Drive
          attachments into the existing ingestion pipeline, publishes coursework and writes
          approved grades. It does not create Google Forms, upload Drive files or send email, and
          those are not claimed. Publication is always an explicit, confirmed, audited action by a
          reviewer; nothing is published automatically.
        </p>
      </StatePanel>
    </div>
  )
}

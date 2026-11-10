import { useCallback, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { CapabilityList, Panel, StepList } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useAuth } from '../lib/auth/AuthProvider'
import {
  classroomConnection,
  disconnectClassroom,
  startClassroomOAuth,
  syncClassroom,
  type ClassroomConnection,
  type ClassroomSyncResult,
} from '../lib/api/classroom'
import { workspaceAllocations, type WorkspaceAllocation } from '../lib/api/allocations'
import { useResource } from '../lib/api/useResource'

export const Route = createFileRoute('/_app/classroom')({
  component: Classroom,
})

type Notice = { tone: 'ok' | 'error'; message: string }
type Busy = 'connect' | 'sync' | 'disconnect' | null

const MANAGER_ROLES = new Set(['OWNER', 'ADMIN', 'PLATFORM_OWNER'])

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

function statusTone(
  status: ClassroomConnection['status'],
): 'ok' | 'attention' | 'neutral' {
  if (status === 'CONNECTED') return 'ok'
  if (status === 'RECONNECT_REQUIRED') return 'attention'
  return 'neutral'
}

function Classroom() {
  const { session } = useAuth()
  const engine = useEngineSession()
  const token = session?.access_token ?? null
  const tenantId = engine.tenantId
  const canManage =
    MANAGER_ROLES.has(engine.me?.role ?? '') ||
    engine.capabilities.includes('workspace.classroom.connect')

  const [connection, reloadConnection] = useResource<ClassroomConnection>(
    `classroom-connection:${token ?? 'anonymous'}`,
    token ? (signal) => classroomConnection({ token, signal }) : null,
  )
  const [allocations, reloadAllocations] = useResource<WorkspaceAllocation[]>(
    `classroom-allocations:${tenantId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId ? (signal) => workspaceAllocations(tenantId, { token, signal }) : null,
  )
  const [syncResult, setSyncResult] = useState<ClassroomSyncResult | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState<Busy>(null)
  const [confirming, setConfirming] = useState(false)

  const refresh = useCallback(() => {
    reloadConnection()
    reloadAllocations()
  }, [reloadAllocations, reloadConnection])

  const connect = async () => {
    if (!token) return
    setBusy('connect')
    setNotice(null)
    const result = await startClassroomOAuth({ token })
    if (result.status === 'ok') {
      // Google must show its own consent screen; the engine never proxies it.
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
    if (result.status === 'ok') {
      setSyncResult(result.data)
      setNotice({
        tone: 'ok',
        message: `Google listed ${result.data.counts.discovered} active course${
          result.data.counts.discovered === 1 ? '' : 's'
        }: ${result.data.counts.created} new, ${result.data.counts.updated} updated.`,
      })
    } else {
      setNotice({ tone: 'error', message: result.reason })
    }
    setBusy(null)
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
      setSyncResult(null)
      setNotice({
        tone: 'ok',
        message: result.data.revoked
          ? 'Google Classroom was disconnected and Google confirmed the grant was revoked.'
          : 'Google Classroom was disconnected here. Google did not confirm revocation; remove Aetrix from your Google account if the grant is still listed.',
      })
    } else {
      setNotice({ tone: 'error', message: result.reason })
    }
    refresh()
  }

  const connected = connection.state === 'ok' ? connection.data : null
  const actionsLocked = busy !== null

  return (
    <div className="app-stack">
      {notice ? (
        <div className="gem-notice" data-tone={notice.tone} role="status">
          {notice.message}
        </div>
      ) : null}

      <Panel title="Connection" note="Optional · read-only course access">
        {connection.state === 'loading' ? (
          <p className="panel-copy">Reading the Classroom connection…</p>
        ) : connection.state === 'ok' ? (
          connected ? (
            <>
              <div className="app-inline-actions">
                <StatusChip tone={statusTone(connected.status)}>
                  {statusLabel(connected.status)}
                </StatusChip>
                <span className="gem-footnote">
                  {connected.configured
                    ? `Authorised ${formatMoment(connected.connected_at)}`
                    : 'OAuth client not configured on this deployment'}
                </span>
              </div>

              {!connected.configured ? (
                <p className="panel-copy">
                  This engine has no Google OAuth client, so Classroom cannot be connected.
                  Set <code>AETRIX_CLASSROOM__CLIENT_ID</code>,{' '}
                  <code>AETRIX_CLASSROOM__CLIENT_SECRET</code> and{' '}
                  <code>AETRIX_CLASSROOM__REDIRECT_URI</code>; until then the connection
                  routes report CLASSROOM_NOT_CONFIGURED rather than showing a fake account.
                </p>
              ) : connected.status === 'NOT_CONNECTED' ? (
                <p className="panel-copy">
                  No Google Classroom authorisation is stored for this workspace. Connecting
                  asks Google for read-only access to the teacher’s course list; it does not
                  read coursework, submissions, students or grades.
                </p>
              ) : connected.status === 'RECONNECT_REQUIRED' ? (
                <p className="panel-copy">
                  Google rejected the stored authorisation, so its tokens were deleted.{' '}
                  {connected.last_error_message ?? 'Connect Classroom again to read courses.'}
                </p>
              ) : (
                <p className="panel-copy">
                  The workspace authorisation is stored encrypted by the engine. Google does
                  not expose a token to the browser and no screen can read one back.
                </p>
              )}

              {connected.status !== 'NOT_CONNECTED' ? (
                <ul className="panel-copy">
                  <li>Connected by: {connected.connected_by_subject ?? 'unknown'}</li>
                  <li>Granted scopes: {connected.granted_scopes.join(', ') || 'none reported'}</li>
                  <li>Last course sync: {formatMoment(connected.last_synced_at)}</li>
                  {connected.last_sync_status ? (
                    <li>
                      Last sync outcome: {connected.last_sync_status}
                      {connected.last_sync_status === 'SUCCEEDED'
                        ? ` (${connected.last_sync_counts.discovered ?? 0} discovered, ${
                            connected.last_sync_counts.created ?? 0
                          } new, ${connected.last_sync_counts.updated ?? 0} updated)`
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
              ) : null}

              {canManage ? (
                <div className="app-inline-actions">
                  {connected.configured &&
                  (connected.status === 'NOT_CONNECTED' ||
                    connected.status === 'RECONNECT_REQUIRED') ? (
                    <button
                      type="button"
                      className="btn btn--small btn--primary"
                      onClick={() => void connect()}
                      disabled={actionsLocked}
                    >
                      {busy === 'connect'
                        ? 'Opening Google…'
                        : connected.status === 'RECONNECT_REQUIRED'
                          ? 'Reconnect Google Classroom'
                          : 'Connect Google Classroom'}
                    </button>
                  ) : null}
                  {connected.status === 'CONNECTED' ? (
                    <button
                      type="button"
                      className="btn btn--small btn--primary"
                      onClick={() => void runSync()}
                      disabled={actionsLocked}
                    >
                      {busy === 'sync' ? 'Reading courses…' : 'Sync courses'}
                    </button>
                  ) : null}
                  {connected.status !== 'NOT_CONNECTED' ? (
                    confirming ? (
                      <>
                        <button
                          type="button"
                          className="btn btn--small btn--danger"
                          onClick={() => void disconnect()}
                          disabled={actionsLocked}
                        >
                          {busy === 'disconnect' ? 'Disconnecting…' : 'Confirm disconnect'}
                        </button>
                        <button
                          type="button"
                          className="btn btn--small"
                          onClick={() => setConfirming(false)}
                          disabled={actionsLocked}
                        >
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => setConfirming(true)}
                        disabled={actionsLocked}
                      >
                        Disconnect
                      </button>
                    )
                  ) : null}
                </div>
              ) : (
                <p className="panel-copy">
                  Only a workspace owner or administrator can connect, sync or disconnect
                  Classroom. You can still read the connection status and the classes allocated
                  to this workspace.
                </p>
              )}
            </>
          ) : null
        ) : (
          <p className="panel-copy">
            {connection.state === 'unavailable' || connection.state === 'error'
              ? connection.reason
              : 'The connection status is unavailable.'}
          </p>
        )}
      </Panel>

      {syncResult ? (
        <Panel
          title="Courses found by the last sync"
          note={`${syncResult.counts.discovered} active · ${new Date(
            syncResult.synced_at,
          ).toLocaleString('en-GB')}`}
        >
          {syncResult.truncated ? (
            <p className="panel-copy">
              The configured course ceiling stopped this read before Google ran out. The list
              below is partial and the sync reports it as truncated rather than complete.
            </p>
          ) : null}
          {syncResult.courses.length === 0 ? (
            <p className="panel-copy">
              Google returned no ACTIVE courses for the connected teacher account.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Courses returned by Google Classroom
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Course ID</th>
                    <th scope="col">Section</th>
                    <th scope="col">Verification</th>
                  </tr>
                </thead>
                <tbody>
                  {syncResult.courses.map((course) => (
                    <tr key={course.course_id}>
                      <th scope="row">{course.name}</th>
                      <td className="mono">{course.course_id}</td>
                      <td>{course.section ?? '—'}</td>
                      <td>
                        <StatusChip tone="ok">VERIFIED</StatusChip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : null}

      <Panel title="Allocated classes" note="Read-only; the platform operator assigns these">
        {allocations.state === 'loading' ? (
          <p className="panel-copy">Reading this workspace’s allocations…</p>
        ) : allocations.state === 'unavailable' || allocations.state === 'error' ? (
          <p className="panel-copy">{allocations.reason}</p>
        ) : allocations.data.length === 0 ? (
          <p className="panel-copy">
            No Google Classroom course is currently allocated to this workspace. Allocation is
            an operator action; a teacher cannot request or move a course.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Classes allocated to this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Class</th>
                  <th scope="col">Course ID</th>
                  <th scope="col">Allocated</th>
                  <th scope="col">Verification</th>
                </tr>
              </thead>
              <tbody>
                {allocations.data.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="data-table__strong">{row.class_name}</span>
                      {row.class_section ? (
                        <span className="gem-footnote">{row.class_section}</span>
                      ) : null}
                    </td>
                    <td className="mono">{row.course_id}</td>
                    <td>
                      {new Date(row.allocated_at).toLocaleDateString('en-GB')}
                      <span className="gem-footnote">
                        {row.allocated_by_label ?? 'platform operator'}
                      </span>
                    </td>
                    <td>
                      <StatusChip tone={row.verification === 'VERIFIED' ? 'ok' : 'attention'}>
                        {row.verification}
                      </StatusChip>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="What the connection covers" note="Scopes are exact, not implied">
        <CapabilityList
          items={[
            {
              label: 'Google Classroom authorisation',
              detail: connected?.configured
                ? 'OAuth with the classroom.courses.readonly scope, access_type=offline and prompt=consent; tokens are stored encrypted.'
                : 'Implemented, but this deployment has no Google OAuth client configured, so authorisation reports CLASSROOM_NOT_CONFIGURED.',
              state: connected?.configured ? 'available' : 'pending',
              icon: 'lock',
            },
            {
              label: 'Course discovery',
              detail:
                'A sync reads the ACTIVE courses Google lists for the connected teacher and records them VERIFIED with source google_classroom.',
              state: connected?.configured ? 'available' : 'pending',
              icon: 'classroom',
            },
            {
              label: 'Roster import',
              detail:
                'Not implemented: course discovery does not read students, coursework or submissions.',
              state: 'pending',
              icon: 'records',
            },
            {
              label: 'Class allocation',
              detail:
                'The platform operator allocates discovered or recorded courses; this workspace can only read them.',
              state: 'available',
              icon: 'shield',
            },
          ]}
        />
      </Panel>

      <Panel title="How a class reaches this workspace" note="Four steps, one owner each">
        <StepList
          steps={[
            {
              title: 'The operator allocates the class',
              body: 'A platform owner or administrator assigns the Classroom course to exactly one workspace.',
            },
            {
              title: 'The workspace connects Classroom',
              body: 'An owner or administrator authorises read-only course access. Google shows its own consent screen.',
            },
            {
              title: 'The workspace syncs courses',
              body: 'Every ACTIVE course Google lists is upserted as a VERIFIED platform record, keyed by course id.',
            },
            {
              title: 'Rosters and grades stay separate',
              body: 'Coursework, student rosters and grade write-back are not part of this integration and are not claimed.',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="Course discovery is implemented; rosters and grades are not"
        capability="Google Classroom courses.list · classroom.courses.readonly"
      >
        <p>
          The connection, encrypted token storage, refresh, revoked-access handling and course
          sync are real. A sync lists courses only: it does not download coursework, import
          student rosters or publish grades. Allocation remains an operator action enforced by
          the platform.
        </p>
      </StatePanel>
    </div>
  )
}

import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { EmptyTable, Panel } from '../components/app/PageBlocks'
import { StatusChip } from '../components/app/StatePanel'
import { HubHero } from '../components/hub/HubHero'
import { Icon } from '../components/ui/Icons'
import { workspaceAllocations, type WorkspaceAllocation } from '../lib/api/allocations'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Dashboard as DashboardData } from '../lib/api/types'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/dashboard')({
  component: Dashboard,
})

function DashStat({ label, value, note }: { label: string; value: number | null; note: string }) {
  return (
    <div className="hub-stat">
      <dt className="hub-stat__label">{label}</dt>
      <dd className="hub-stat__value mono" aria-label={`${label}: ${value ?? 'not available'}`}>
        {value === null ? '—' : value}
      </dd>
      <dd className="hub-stat__note">{note}</dd>
    </div>
  )
}

function Dashboard() {
  const { user } = useAuth()
  const session = useEngineSession()
  const [state, reload] = useResource<DashboardData>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) =>
          workspaceService.dashboard(session.tenantId!, {
            token: session.token,
            signal,
          })
      : null,
  )
  // The workspace route returns ACTIVE allocations only. Released history is
  // deliberately absent here: it belongs to the platform operator, not the
  // teacher dashboard.
  const [allocationsState, reloadAllocations] = useResource<WorkspaceAllocation[]>(
    `classroom-allocations:${session.tenantId ?? 'none'}`,
    session.tenantId
      ? (signal) =>
          workspaceAllocations(session.tenantId!, {
            token: session.token,
            signal,
          })
      : null,
  )
  const name = displayName(user)
  const firstName = name.split(/\s+/)[0] || name
  const data = state.state === 'ok' ? state.data : null
  const allocations = allocationsState.state === 'ok' ? allocationsState.data : []
  const allocationCount = allocationsState.state === 'ok' ? allocations.length : null

  const refresh = () => {
    reload()
    reloadAllocations()
  }

  return (
    <div className="hub-main">
      <HubHero
        name={firstName}
        lede="Your workspace: its classes, assignments and marking load. Every figure is a count the engine holds; where it has none, the value stays blank."
        actions={
          <>
            <Link to="/queue" className="btn btn--primary">
              Open marking queue
              <Icon name="arrow" size={16} />
            </Link>
            <Link to="/assignments" className="btn btn--outline">
              Assignments
            </Link>
          </>
        }
      />

      <DataState state={state} capability="GET /api/v1/workspaces/{id}/dashboard">
        <dl className="hub-stats">
          <DashStat
            label="Assignments"
            value={data ? data.assignments : null}
            note="in this workspace"
          />
          <DashStat
            label="Submissions"
            value={data ? data.submissions : null}
            note="registered scripts"
          />
          <DashStat
            label="Jobs active"
            value={data ? data.jobs_active : null}
            note="validating, marking or verifying"
          />
          <DashStat
            label="Awaiting review"
            value={data ? data.awaiting_review : null}
            note="stopped for a person"
          />
          <DashStat
            label="Failed jobs"
            value={data ? data.failed_jobs : null}
            note="failed or parked"
          />
          <DashStat
            label="Approved results"
            value={data ? data.approved_results : null}
            note="signed off by a teacher"
          />
          <DashStat
            label="Classroom classes"
            value={allocationCount}
            note="active allocations in this workspace"
          />
        </dl>
      </DataState>

      <Panel
        title="Classroom classes"
        note={
          allocationsState.state === 'ok'
            ? `${allocationCount} active`
            : 'Read-only allocations'
        }
      >
        <DataState
          state={allocationsState}
          capability="GET /api/v1/workspaces/{id}/classroom-allocations"
        >
          {allocations.length === 0 ? (
            <EmptyTable
              columns={['Class', 'Course ID', 'Allocated', 'Verification']}
              caption="Classroom classes allocated to this workspace"
              note="No Google Classroom course is currently allocated to this workspace. Allocation is an operator action; a teacher cannot request or move a course."
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Classroom classes allocated to this workspace
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Course ID</th>
                    <th scope="col">Allocated</th>
                    <th scope="col">Verification</th>
                  </tr>
                </thead>
                <tbody>
                  {allocations.map((allocation) => (
                    <tr key={allocation.id}>
                      <td>
                        <span className="data-table__strong">{allocation.class_name}</span>
                        {allocation.class_section ? (
                          <span className="gem-footnote">{allocation.class_section}</span>
                        ) : null}
                      </td>
                      <td className="mono">{allocation.course_id}</td>
                      <td>
                        {new Date(allocation.allocated_at).toLocaleDateString('en-GB')}
                        <span className="gem-footnote">
                          {allocation.allocated_by_label ?? 'platform operator'}
                        </span>
                      </td>
                      <td>
                        <StatusChip
                          tone={allocation.verification === 'VERIFIED' ? 'ok' : 'attention'}
                        >
                          {allocation.verification}
                        </StatusChip>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </DataState>
      </Panel>

      <Panel
        title="Recent correction jobs"
        note={session.me ? session.me.workspace_name : 'Engine activity'}
      >
        <div className="app-toolbar">
          <p className="app-toolbar__note mono">
            The eight jobs the engine changed most recently.
          </p>
          <button type="button" className="btn btn--small btn--outline" onClick={refresh}>
            Refresh
          </button>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Recent correction jobs</caption>
            <thead>
              <tr>
                <th scope="col">Student</th>
                <th scope="col">State</th>
                <th scope="col">Progress</th>
                <th scope="col">Error</th>
                <th scope="col">Updated</th>
                <th scope="col">Open</th>
              </tr>
            </thead>
            <tbody>
              {data && data.recent_jobs.length > 0 ? (
                data.recent_jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.student_ref ?? '—'}</td>
                    <td>
                      <span className="chip app-chip" data-tone={job.error_code ? 'attention' : 'neutral'}>
                        {job.state}
                      </span>
                    </td>
                    <td className="mono">{Math.round(job.progress * 100)}%</td>
                    <td className="mono">{job.error_code ?? '—'}</td>
                    <td className="mono">{new Date(job.updated_at).toLocaleString()}</td>
                    <td>
                      <Link
                        className="btn btn--small btn--outline"
                        to="/submissions/$submissionId"
                        params={{ submissionId: job.submission_id }}
                      >
                        Review
                      </Link>
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="data-table__empty">
                    {data
                      ? 'No correction jobs yet. Register a submission on an assignment to create one.'
                      : 'No rows — the engine has not answered this screen.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

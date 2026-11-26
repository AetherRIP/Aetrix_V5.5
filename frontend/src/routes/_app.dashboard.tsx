import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { HubSection } from '../components/hub/HubSection'
import {
  Bars,
  DashboardFallback,
  DashboardHero,
  DashboardSkeleton,
  FlowRail,
  Pulse,
  PulseStat,
  QuickAction,
  Timeline,
  dashboardStamp,
  percent,
  type BarRow,
  type FlowStage,
} from '../components/hub/DashboardKit'
import { StatusChip } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { workspaceAllocations, type WorkspaceAllocation } from '../lib/api/allocations'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type {
  AuditEventPage,
  Dashboard as DashboardData,
  Gradebook,
  InboxItem,
  ReportRow,
  SchoolClass,
} from '../lib/api/types'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { workspaceService, rosterService } from '../lib/services'
import { jobTone } from '../lib/jobs/presentation'

export const Route = createFileRoute('/_app/dashboard')({
  component: Dashboard,
})

const STATE_ORDER: Record<string, number> = {
  REVIEW_REQUIRED: 0,
  FAILED: 1,
  RETRY_SUSPENDED: 2,
  PROCESSING_DOCUMENTS: 3,
  CORRECTING: 3,
  VERIFYING: 3,
  VALIDATING: 3,
}

function humanise(value: string): string {
  const spaced = value.replace(/[_-]/g, ' ').replace(/\./g, ' · ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function TeacherSignal({
  data,
  mean,
  loading,
}: {
  data: DashboardData | null
  mean: number | null
  loading: boolean
}) {
  return (
    <div className="dash-signal">
      <p className="dash-signal__eyebrow mono">Teaching signal</p>
      <p className="dash-signal__headline">
        {loading ? 'Reading the workspace…' : data ? `${data.awaiting_review}` : '—'}
      </p>
      <p className="dash-signal__caption">
        {loading
          ? 'The engine is answering.'
          : data
            ? `job${data.awaiting_review === 1 ? '' : 's'} waiting for a teacher decision`
            : 'No review figure is available.'}
      </p>
      <div className="dash-signal__split">
        <span>
          <strong className="mono">{data ? data.jobs_active : '—'}</strong>
          <small>active</small>
        </span>
        <span>
          <strong className="mono">{data ? data.failed_jobs : '—'}</strong>
          <small>failed</small>
        </span>
        <span>
          <strong className="mono">{mean === null ? '—' : percent(mean)}</strong>
          <small>approved mean</small>
        </span>
      </div>
      <div className="dash-signal__rule" aria-hidden="true" />
      <p className="dash-signal__foot mono">
        {data
          ? `${data.approved_results} approved result${data.approved_results === 1 ? '' : 's'}`
          : 'Engine figures stay blank until they are read.'}
      </p>
    </div>
  )
}

function MarkingFlow({
  data,
  state,
}: {
  data: DashboardData | null
  state: 'loading' | 'ok' | 'unavailable' | 'error'
}) {
  const stages: FlowStage[] = [
    {
      id: 'assignments',
      label: 'Assignments',
      value: data ? data.assignments : null,
      note: 'work defined',
      to: '/assignments',
      icon: 'assignment',
    },
    {
      id: 'submissions',
      label: 'Submissions',
      value: data ? data.submissions : null,
      note: 'scripts registered',
      to: '/assignments',
      icon: 'records',
    },
    {
      id: 'active',
      label: 'Active jobs',
      value: data ? data.jobs_active : null,
      note: 'validating or marking',
      to: '/queue',
      icon: 'pulse',
    },
    {
      id: 'review',
      label: 'Awaiting review',
      value: data ? data.awaiting_review : null,
      note: 'stopped for a person',
      to: '/inbox',
      icon: 'review',
      tone: data && data.awaiting_review > 0 ? 'attention' : 'default',
    },
    {
      id: 'approved',
      label: 'Approved',
      value: data ? data.approved_results : null,
      note: 'signed off',
      to: '/gradebook',
      icon: 'checkDouble',
      tone: 'ok',
    },
  ]

  return <FlowRail stages={stages} state={state} label="Marking flow" />
}

function ReviewLane({
  data,
  loading,
  unavailable,
}: {
  data: DashboardData | null
  loading: boolean
  unavailable: string | null
}) {
  if (loading) return <DashboardSkeleton rows={3} />
  if (!data) {
    return (
      <DashboardFallback
        title="The review lane is not available"
        reason={unavailable ?? 'The engine has not returned the workspace dashboard.'}
        capability="GET /api/v1/workspaces/{id}/dashboard"
      />
    )
  }
  const jobs = [...data.recent_jobs].sort(
    (a, b) => (STATE_ORDER[a.state] ?? 9) - (STATE_ORDER[b.state] ?? 9),
  )
  if (jobs.length === 0) {
    return (
      <div className="dash-empty-state">
        <p className="dash-empty-state__title">Nothing is waiting in the lane.</p>
        <p className="dash-empty">
          The engine reports no correction job yet. Register a submission on an assignment to
          create the first one.
        </p>
        <Link className="btn btn--small btn--outline" to="/assignments">
          Open assignments
        </Link>
      </div>
    )
  }

  return (
    <ul className="dash-lane" aria-label="Recent correction jobs">
      {jobs.slice(0, 5).map((job) => (
        <li className="dash-lane__row" key={job.id} data-tone={jobTone(job.state)}>
          <div className="dash-lane__id">
            <span className="mono">{job.student_ref ?? 'Student not recorded'}</span>
            <small className="mono">{job.id.slice(0, 8)}</small>
          </div>
          <div className="dash-lane__state">
            <span className="chip app-chip" data-tone={jobTone(job.state)}>
              {humanise(job.state)}
            </span>
            <span className="dash-lane__progress mono">
              {Math.round(job.progress * 100)}% · {dashboardStamp(job.updated_at)}
            </span>
          </div>
          <div
            className="dash-lane__meter"
            role="img"
            aria-label={`${Math.round(job.progress * 100)}% progress`}
          >
            <span style={{ width: `${Math.min(100, Math.max(0, job.progress * 100))}%` }} />
          </div>
          <Link
            className="btn btn--small btn--outline"
            to="/submissions/$submissionId"
            params={{ submissionId: job.submission_id }}
          >
            Review
          </Link>
        </li>
      ))}
    </ul>
  )
}

function CohortSignal({
  reports,
  book,
  state,
}: {
  reports: readonly ReportRow[]
  book: Gradebook | null
  state: 'loading' | 'ok' | 'unavailable' | 'error'
}) {
  const [mode, setMode] = useState<'mean' | 'volume'>('mean')
  if (state === 'loading') return <DashboardSkeleton rows={3} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="The cohort signal is not available"
        reason="The engine did not return assignment reports. No mean is being estimated."
        capability="GET /api/v1/workspaces/{id}/reports"
      />
    )
  }

  const rows: BarRow[] = reports.slice(0, 7).map((row) => ({
    id: row.assignment_id,
    label: row.name,
    value: mode === 'mean' ? row.mean_percent : row.submissions,
    suffix: mode === 'mean' ? '%' : '',
    detail:
      mode === 'mean'
        ? `${row.approved} approved · ${row.awaiting_review} awaiting review`
        : `${row.submissions} script${row.submissions === 1 ? '' : 's'} · ${row.jobs_completed} completed`,
  }))
  const reportable = reports.filter((row) => row.state === 'OK').length

  return (
    <div className="dash-cohort">
      <div className="dash-cohort__toolbar">
        <div className="dash-toggle" role="group" aria-label="Cohort signal measure">
          <button
            type="button"
            className="dash-toggle__button"
            aria-pressed={mode === 'mean'}
            onClick={() => setMode('mean')}
          >
            Approved mean
          </button>
          <button
            type="button"
            className="dash-toggle__button"
            aria-pressed={mode === 'volume'}
            onClick={() => setMode('volume')}
          >
            Submission pace
          </button>
        </div>
        <span className="dash-cohort__note mono">
          {reportable} of {reports.length} assignment{reports.length === 1 ? '' : 's'} reportable
        </span>
      </div>

      <Bars
        rows={rows}
        label={mode === 'mean' ? 'Approved mean by assignment' : 'Submissions by assignment'}
        empty="No assignment has a report yet. Upload a submission to begin the signal."
      />

      <div className="dash-cohort__footer">
        <span>
          <strong className="mono">{book ? book.approved_jobs : '—'}</strong>
          <small>approved jobs</small>
        </span>
        <span>
          <strong className="mono">{book ? book.provisional_jobs : '—'}</strong>
          <small>provisional</small>
        </span>
        <span>
          <strong className="mono">{book ? percent(book.mean_percent) : '—'}</strong>
          <small>approved mean</small>
        </span>
        <Link className="panel-link" to="/reports">
          Full reports <Icon name="arrow" size={14} />
        </Link>
      </div>
    </div>
  )
}

function NeedsAttention({
  items,
  state,
}: {
  items: readonly InboxItem[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
}) {
  if (state === 'loading') return <DashboardSkeleton rows={2} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="The attention feed is not available"
        reason="The engine has not returned this workspace’s exceptions."
        capability="GET /api/v1/workspaces/{id}/inbox"
        compact
      />
    )
  }
  if (items.length === 0) {
    return <p className="dash-empty">No exception is waiting for a person.</p>
  }
  return (
    <ul className="dash-attention">
      {items.slice(0, 4).map((item) => (
        <li className="dash-attention__row" key={item.id}>
          <span className="dash-attention__kind chip app-chip" data-tone="attention">
            {item.kind === 'REVIEW_REQUIRED' ? 'Review' : 'Failed'}
          </span>
          <div>
            <strong>{item.title}</strong>
            <p>{item.detail}</p>
          </div>
          {item.submission_id ? (
            <Link
              className="btn btn--small btn--outline"
              to="/submissions/$submissionId"
              params={{ submissionId: item.submission_id }}
            >
              Open
            </Link>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

function ClassesPanel({
  rows,
  state,
}: {
  rows: readonly SchoolClass[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
}) {
  if (state === 'loading') return <DashboardSkeleton rows={2} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="Classes are not available"
        reason="The workspace roster has not answered."
        capability="GET /api/v1/workspaces/{id}/classes"
        compact
      />
    )
  }
  if (rows.length === 0) {
    return (
      <p className="dash-empty">
        No class exists in this workspace yet. Classes are workspace records; a Classroom sync
        lists courses but does not create them.
      </p>
    )
  }
  return (
    <ul className="dash-classes">
      {rows.slice(0, 5).map((row) => (
        <li className="dash-classes__row" key={row.id}>
          <span className="dash-classes__icon" aria-hidden="true">
            <Icon name="classroom" size={15} />
          </span>
          <span className="dash-classes__copy">
            <strong>{row.name}</strong>
            <small>{row.year_group ?? 'Year group not recorded'}</small>
          </span>
          <span className="dash-classes__count mono">{row.student_count}</span>
        </li>
      ))}
    </ul>
  )
}

function ClassroomPanel({
  rows,
  state,
}: {
  rows: readonly WorkspaceAllocation[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
}) {
  return (
    <Panel title="Classroom classes" note="Active allocations" index={6}>
      {state === 'loading' ? (
        <DashboardSkeleton rows={2} />
      ) : state !== 'ok' ? (
        <DashboardFallback
          title="Classroom allocations are not available"
          reason="The engine has not returned this workspace’s active allocations."
          capability="GET /api/v1/workspaces/{id}/classroom-allocations"
          compact
        />
      ) : (
        <div className="dash-classroom">
          <div className="hub-stat dash-classroom__stat">
            <span className="hub-stat__label">Classroom classes</span>
            <span
              className="hub-stat__value mono"
              aria-label={`Classroom classes: ${rows.length} active`}
            >
              {rows.length}
            </span>
            <span className="hub-stat__note">{rows.length} active</span>
          </div>
          {rows.length === 0 ? (
            <p className="dash-empty dash-classroom__empty">
              No Google Classroom course is currently allocated to this workspace.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table dash-classroom__table">
                <caption className="visually-hidden">Active Classroom allocations</caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">State</th>
                    <th scope="col">Allocated by</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row" className="dash-classroom__classcell">
                        <strong>{row.class_name}</strong>
                        <span className="mono">{row.course_id}</span>
                        <small>{row.class_section ?? 'Section not recorded'}</small>
                      </th>
                      <td>
                        <StatusChip tone={row.verification === 'VERIFIED' ? 'ok' : 'attention'}>
                          {row.verification}
                        </StatusChip>
                      </td>
                      <td>{row.allocated_by_label ?? 'Not recorded'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
      <div className="dash-section-foot">
        <Link className="panel-link" to="/classroom">
          Google Classroom <Icon name="arrow" size={14} />
        </Link>
      </div>
    </Panel>
  )
}

function Dashboard() {
  const { user } = useAuth()
  const session = useEngineSession()
  const name = displayName(user)
  const firstName = name.split(/\s+/)[0] || name
  const workspace = session.tenantId

  const [dashboardState, reloadDashboard] = useResource<DashboardData>(
    workspace ?? 'none',
    workspace
      ? (signal) => workspaceService.dashboard(workspace, { token: session.token, signal })
      : null,
  )
  const [reportsState, reloadReports] = useResource<ReportRow[]>(
    `reports:${workspace ?? 'none'}`,
    workspace
      ? (signal) => workspaceService.reports(workspace, { token: session.token, signal })
      : null,
  )
  const [gradebookState, reloadGradebook] = useResource<Gradebook>(
    `gradebook:${workspace ?? 'none'}`,
    workspace
      ? (signal) => workspaceService.gradebook(workspace, { token: session.token, signal })
      : null,
  )
  const [inboxState, reloadInbox] = useResource<InboxItem[]>(
    `inbox:${workspace ?? 'none'}`,
    workspace
      ? (signal) => workspaceService.inbox(workspace, { token: session.token, signal })
      : null,
  )
  const [classesState, reloadClasses] = useResource<SchoolClass[]>(
    `classes:${workspace ?? 'none'}`,
    workspace
      ? (signal) => rosterService.classes(workspace, { token: session.token, signal })
      : null,
  )
  const [allocationsState, reloadAllocations] = useResource<WorkspaceAllocation[]>(
    `classroom-allocations:${workspace ?? 'none'}`,
    workspace
      ? (signal) => workspaceAllocations(workspace, { token: session.token, signal })
      : null,
  )
  const [auditState, reloadAudit] = useResource<AuditEventPage>(
    `audit:${workspace ?? 'none'}`,
    workspace
      ? (signal) =>
          workspaceService.audit(
            workspace,
            { limit: 8 },
            { token: session.token, signal },
          )
      : null,
  )

  const dash = dashboardState.state === 'ok' ? dashboardState.data : null
  const reports = reportsState.state === 'ok' ? reportsState.data : []
  const book = gradebookState.state === 'ok' ? gradebookState.data : null
  const inbox = inboxState.state === 'ok' ? inboxState.data : []
  const classes = classesState.state === 'ok' ? classesState.data : []
  const allocations = allocationsState.state === 'ok' ? allocationsState.data : []
  const audit = auditState.state === 'ok' ? auditState.data.items : []

  const refresh = () => {
    reloadDashboard()
    reloadReports()
    reloadGradebook()
    reloadInbox()
    reloadClasses()
    reloadAllocations()
    reloadAudit()
  }

  const activity = audit.slice(0, 5).map((event) => ({
    id: event.id,
    title: humanise(event.action),
    detail: `${event.actor_label ?? event.actor_type} · ${event.entity_type}`,
    stamp: dashboardStamp(event.created_at),
    tone: 'accent' as const,
  }))

  return (
    <div className="hub-main dash-page dash-teacher">
      <DashboardHero
        role="teacher"
        eyebrow="Teaching control room"
        title={`Good morning, ${firstName}.`}
        lede="Your workspace at a glance: the review lane, the cohort signal and the classes that need you. Every figure is read from the engine; where it has no answer, the value stays blank."
        aside={
          <TeacherSignal
            data={dash}
            mean={book?.mean_percent ?? null}
            loading={dashboardState.state === 'loading'}
          />
        }
        actions={
          <>
            <QuickAction
              to="/queue"
              icon="pulse"
              label="Open marking queue"
              note="Review every job waiting for a person"
              primary
            />
            <QuickAction
              to="/gradebook"
              icon="checkDouble"
              label="Gradebook"
              note="Approved and provisional marks"
            />
            <QuickAction
              to="/students"
              icon="classroom"
              label="Classes & students"
              note="Roster and class records"
            />
            <QuickAction
              to="/assignments"
              icon="assignment"
              label="Assignments"
              note="Papers, schemes and submissions"
            />
          </>
        }
      />

      <HubSection
        id="teacher-flow"
        title="Marking flow"
        note={
          dashboardState.state === 'ok'
            ? 'Current state counts, not conversion'
            : dashboardState.state === 'loading'
              ? 'Reading the engine'
              : 'Pipeline unavailable'
        }
        index={1}
        className="dash-flow-section"
      >
        <MarkingFlow data={dash} state={dashboardState.state} />
      </HubSection>

      <div className="dash-grid dash-grid--teacher">
        <div className="dash-col">
          <HubSection
            id="teacher-review"
            title="Review lane"
            note={dash ? `${dash.awaiting_review} awaiting review` : 'Reading the engine'}
            index={1}
            action={
              <button
                type="button"
                className="btn btn--small btn--outline"
                onClick={refresh}
                disabled={dashboardState.state === 'loading'}
              >
                Refresh
              </button>
            }
          >
            <ReviewLane
              data={dash}
              loading={dashboardState.state === 'loading'}
              unavailable={dashboardState.state === 'error' ? dashboardState.reason : null}
            />
            {dash && dash.recent_jobs.length > 0 ? (
              <div className="dash-section-foot">
                <span className="mono">
                  Latest {Math.min(5, dash.recent_jobs.length)} correction jobs
                </span>
                <Link className="panel-link" to="/history">
                  Marking history <Icon name="arrow" size={14} />
                </Link>
              </div>
            ) : null}
          </HubSection>

          <HubSection
            id="teacher-cohort"
            title="Cohort signal"
            note="Approved outcomes only"
            index={2}
          >
            <CohortSignal
              reports={reports}
              book={book}
              state={
                reportsState.state === 'ok'
                  ? 'ok'
                  : reportsState.state === 'loading'
                    ? 'loading'
                    : reportsState.state
              }
            />
          </HubSection>

          <HubSection
            id="teacher-attention"
            title="Needs attention"
            note="Exceptions raised by the engine"
            index={3}
          >
            <NeedsAttention
              items={inbox}
              state={
                inboxState.state === 'ok'
                  ? 'ok'
                  : inboxState.state === 'loading'
                    ? 'loading'
                    : inboxState.state
              }
            />
          </HubSection>
        </div>

        <aside className="dash-col dash-col--rail" aria-label="Teaching context">
          <HubSection id="teacher-pulse" title="Teaching pulse" note="Live counts" index={4}>
            <Pulse label="Teaching pulse" note="Read from the workspace dashboard.">
              <PulseStat
                label="Assignments"
                value={dash ? dash.assignments : null}
                note="in this workspace"
              />
              <PulseStat
                label="Submissions"
                value={dash ? dash.submissions : null}
                note="registered scripts"
              />
              <PulseStat
                label="Active jobs"
                value={dash ? dash.jobs_active : null}
                note="validating or marking"
              />
              <PulseStat
                label="Awaiting review"
                value={dash ? dash.awaiting_review : null}
                note="stopped for a person"
                tone="attention"
              />
            </Pulse>
            <div className="dash-pulse__divider" />
            <Pulse label="Approved outcomes" note="Only approved marks contribute.">
              <PulseStat
                label="Approved"
                value={dash ? dash.approved_results : null}
                note="signed off"
                tone="ok"
              />
              <PulseStat
                label="Failed"
                value={dash ? dash.failed_jobs : null}
                note="failed jobs"
                tone={dash && dash.failed_jobs > 0 ? 'attention' : 'default'}
              />
              <PulseStat
                label="Mean"
                value={book ? percent(book.mean_percent) : null}
                note="approved marks"
              />
            </Pulse>
          </HubSection>

          <HubSection id="teacher-classes" title="Classes" note="Workspace roster" index={5}>
            <ClassesPanel
              rows={classes}
              state={
                classesState.state === 'ok'
                  ? 'ok'
                  : classesState.state === 'loading'
                    ? 'loading'
                    : classesState.state
              }
            />
            <div className="dash-section-foot">
              <Link className="panel-link" to="/students">
                Open classes & students <Icon name="arrow" size={14} />
              </Link>
            </div>
          </HubSection>

          <ClassroomPanel
            rows={allocations}
            state={
              allocationsState.state === 'ok'
                ? 'ok'
                : allocationsState.state === 'loading'
                  ? 'loading'
                  : allocationsState.state
            }
          />

          <HubSection id="teacher-activity" title="Recent activity" note="Audit trail" index={7}>
            {auditState.state === 'loading' ? (
              <DashboardSkeleton rows={3} />
            ) : auditState.state !== 'ok' ? (
              <DashboardFallback
                title="Activity is not available"
                reason="The engine has not returned the workspace audit trail."
                capability="GET /api/v1/workspaces/{id}/audit"
                compact
              />
            ) : (
              <Timeline items={activity} />
            )}
          </HubSection>
        </aside>
      </div>
    </div>
  )
}

import { useMemo, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { HubSection } from '../components/hub/HubSection'
import {
  DashboardFallback,
  DashboardHero,
  DashboardSkeleton,
  Pulse,
  PulseStat,
  QuickAction,
  Timeline,
  WorkloadBar,
  dashboardStamp,
  type TimelineItem,
} from '../components/hub/DashboardKit'
import { Panel } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { InboxItem, Job } from '../lib/api/types'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { queueService, workspaceService } from '../lib/services'
import { jobTone } from '../lib/jobs/presentation'

export const Route = createFileRoute('/_app/assistant/')({
  component: AssistantOverview,
})

type Filter = 'all' | 'review' | 'active' | 'failed'

const ACTIVE_STATES = new Set([
  'QUEUED',
  'PROCESSING_DOCUMENTS',
  'MAPPING_QUESTIONS',
  'CORRECTING',
  'VERIFYING',
  'VALIDATING',
])

function matchesFilter(job: Job, filter: Filter): boolean {
  if (filter === 'all') return true
  if (filter === 'review') return job.state === 'REVIEW_REQUIRED'
  if (filter === 'failed') return job.state === 'FAILED' || job.state === 'RETRY_SUSPENDED'
  return ACTIVE_STATES.has(job.state)
}

function humanise(value: string): string {
  const spaced = value.replace(/_/g, ' ').toLowerCase()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function QueueRows({ jobs, loading, error }: { jobs: readonly Job[]; loading: boolean; error: string | null }) {
  if (loading) return <DashboardSkeleton rows={4} />
  if (error) {
    return (
      <DashboardFallback
        title="Your queue is not available"
        reason={error}
        capability="GET /api/v1/workspaces/{id}/corrections"
      />
    )
  }
  if (jobs.length === 0) {
    return (
      <div className="dash-empty-state">
        <p className="dash-empty-state__title">Nothing matches this view.</p>
        <p className="dash-empty">
          The queue holds no job in this state. Choose another view or open the full marking
          queue.
        </p>
        <Link className="btn btn--small btn--outline" to="/queue">
          Open marking queue
        </Link>
      </div>
    )
  }

  return (
    <ul className="dash-lane dash-lane--assistant" aria-label="Correction jobs">
      {jobs.map((job) => (
        <li className="dash-lane__row" key={job.id} data-tone={jobTone(job.state)}>
          <div className="dash-lane__id">
            <span className="mono">Submission {job.submission_id.slice(0, 8)}</span>
            <small className="mono">Job {job.id.slice(0, 8)}</small>
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
            Open
          </Link>
        </li>
      ))}
    </ul>
  )
}

function WaitingOnMe({
  items,
  state,
  reason,
}: {
  items: readonly InboxItem[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
  reason: string | null
}) {
  if (state === 'loading') return <DashboardSkeleton rows={2} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="The inbox is not available"
        reason={reason ?? 'The engine has not returned the shared inbox.'}
        capability="GET /api/v1/workspaces/{id}/inbox"
        compact
      />
    )
  }
  if (items.length === 0) {
    return (
      <p className="dash-empty">
        No review request or failure is waiting. New exceptions appear here as the engine raises
        them.
      </p>
    )
  }
  return (
    <ul className="dash-attention dash-attention--desk">
      {items.slice(0, 5).map((item) => (
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

function AssistantOverview() {
  const { user } = useAuth()
  const session = useEngineSession()
  const firstName = displayName(user).split(/\s+/)[0]
  const workspace = session.tenantId
  const [filter, setFilter] = useState<Filter>('all')

  const [queueState, reloadQueue] = useResource<Job[]>(
    `queue:${workspace ?? 'none'}`,
    workspace
      ? (signal) => queueService.list(workspace, { token: session.token, signal })
      : null,
  )
  const [inboxState, reloadInbox] = useResource<InboxItem[]>(
    `assistant-inbox:${workspace ?? 'none'}`,
    workspace
      ? (signal) => workspaceService.inbox(workspace, { token: session.token, signal })
      : null,
  )

  const jobs = queueState.state === 'ok' ? queueState.data : []
  const inbox = inboxState.state === 'ok' ? inboxState.data : []
  const loading = queueState.state === 'loading'

  const counts = useMemo(() => {
    if (queueState.state !== 'ok') return null
    return {
      total: jobs.length,
      review: jobs.filter((job) => job.state === 'REVIEW_REQUIRED').length,
      active: jobs.filter((job) => ACTIVE_STATES.has(job.state)).length,
      failed: jobs.filter((job) => job.state === 'FAILED' || job.state === 'RETRY_SUSPENDED').length,
      completed: jobs.filter((job) => job.state === 'COMPLETED').length,
    }
  }, [jobs, queueState.state])

  const filtered = useMemo(
    () =>
      [...jobs]
        .filter((job) => matchesFilter(job, filter))
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 7),
    [jobs, filter],
  )

  const activity: TimelineItem[] = useMemo(
    () =>
      [...jobs]
        .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
        .slice(0, 5)
        .map((job) => ({
          id: job.id,
          title: humanise(job.state),
          detail: `Submission ${job.submission_id.slice(0, 8)} · job ${job.id.slice(0, 8)}`,
          stamp: dashboardStamp(job.updated_at),
          tone: jobTone(job.state),
          action: (
            <Link
              className="panel-link"
              to="/submissions/$submissionId"
              params={{ submissionId: job.submission_id }}
            >
              Open submission <Icon name="arrow" size={14} />
            </Link>
          ),
        })),
    [jobs],
  )

  const filterCounts: Record<Filter, number | null> = counts
    ? {
        all: counts.total,
        review: counts.review,
        active: counts.active,
        failed: counts.failed,
      }
    : { all: null, review: null, active: null, failed: null }

  const refresh = () => {
    reloadQueue()
    reloadInbox()
  }

  return (
    <div className="hub-main dash-page dash-assistant">
      <DashboardHero
        role="assistant"
        eyebrow="Reviewer’s desk"
        title={`Good morning, ${firstName}.`}
        lede="One desk for the scripts this workspace exposes to you. The live counts below come from the correction queue; personal task and deadline records are not implemented, so this desk does not invent them."
        aside={
          <div className="dash-signal dash-signal--assistant">
            <div className="dash-signal__topline">
              <p className="dash-signal__eyebrow mono">Queue load</p>
              <span className="dash-signal__status mono">
                {loading ? 'reading' : queueState.state === 'ok' ? 'live' : 'unavailable'}
              </span>
            </div>
            <p className="dash-signal__headline">{counts ? counts.total : '—'}</p>
            <p className="dash-signal__caption">
              {counts
                ? `${counts.review} waiting for a person · ${counts.active} running`
                : 'The queue has not answered yet.'}
            </p>
            <WorkloadBar
              loading={loading}
              empty="The queue holds no correction job."
              parts={[
                { label: 'Review', value: counts ? counts.review : null, tone: 'attention' },
                { label: 'Running', value: counts ? counts.active : null, tone: 'accent' },
                { label: 'Failed', value: counts ? counts.failed : null, tone: 'neutral' },
                { label: 'Complete', value: counts ? counts.completed : null, tone: 'accent' },
              ]}
            />
          </div>
        }
        actions={
          <>
            <QuickAction
              to="/queue"
              icon="pulse"
              label="Marking queue"
              note="Review scripts and job state"
              primary
            />
            <QuickAction to="/inbox" icon="review" label="Shared inbox" note="Review requests and failures" />
            <QuickAction
              to="/assistant/tasks"
              icon="assignment"
              label="My tasks"
              note="What is, and is not, assigned"
            />
            <QuickAction to="/assignments" icon="records" label="Uploads" note="Add a script to an assignment" />
          </>
        }
      />

      <div className="dash-grid dash-grid--assistant">
        <div className="dash-col">
          <HubSection
            id="assistant-queue"
            title="Live queue"
            note={counts ? `${counts.total} job${counts.total === 1 ? '' : 's'} the engine exposes` : 'Reading the engine'}
            index={1}
            action={
              <button
                type="button"
                className="btn btn--small btn--outline"
                onClick={refresh}
                disabled={loading}
              >
                Refresh
              </button>
            }
          >
            <div className="dash-filterbar">
              <div className="dash-toggle" role="group" aria-label="Filter queue by state">
                {(
                  [
                    ['all', 'All'],
                    ['review', 'Review'],
                    ['active', 'Running'],
                    ['failed', 'Failed'],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    type="button"
                    className="dash-toggle__button"
                    aria-pressed={filter === value}
                    key={value}
                    onClick={() => setFilter(value)}
                  >
                    {label}
                    <span className="dash-toggle__count mono">
                      {filterCounts[value] === null ? '—' : filterCounts[value]}
                    </span>
                  </button>
                ))}
              </div>
              <Link className="panel-link" to="/queue">
                Full queue <Icon name="arrow" size={14} />
              </Link>
            </div>
            <QueueRows
              jobs={filtered}
              loading={loading}
              error={
                queueState.state === 'error'
                  ? queueState.reason
                  : queueState.state === 'unavailable'
                    ? queueState.reason
                    : null
              }
            />
          </HubSection>

          <HubSection
            id="assistant-attention"
            title="Waiting on a person"
            note="Shared inbox"
            index={2}
          >
            <WaitingOnMe
              items={inbox}
              state={
                inboxState.state === 'ok'
                  ? 'ok'
                  : inboxState.state === 'loading'
                    ? 'loading'
                    : inboxState.state
              }
              reason={inboxState.state === 'error' || inboxState.state === 'unavailable' ? inboxState.reason : null}
            />
          </HubSection>

          <HubSection id="assistant-activity" title="Recent queue activity" note="Newest first" index={3}>
            {loading ? (
              <DashboardSkeleton rows={3} />
            ) : queueState.state !== 'ok' ? (
              <DashboardFallback
                title="Activity is not available"
                reason="Recent queue events are read from the correction jobs list."
                capability="GET /api/v1/workspaces/{id}/corrections"
                compact
              />
            ) : (
              <Timeline items={activity} />
            )}
          </HubSection>
        </div>

        <aside className="dash-col dash-col--rail" aria-label="Assistant context">
          <HubSection id="assistant-workload" title="Queue workload" note="Live queue only" index={4}>
            <Pulse
              label="Assistant workload"
              note="Counts include every correction job this workspace exposes to you."
            >
              <PulseStat
                label="In queue"
                value={counts ? counts.total : null}
                note="all states"
              />
              <PulseStat
                label="Awaiting review"
                value={counts ? counts.review : null}
                note="needs a person"
                tone="attention"
              />
              <PulseStat
                label="Running"
                value={counts ? counts.active : null}
                note="engine working"
              />
              <PulseStat
                label="Completed"
                value={counts ? counts.completed : null}
                note="finished jobs"
                tone="ok"
              />
            </Pulse>
            <div className="dash-pulse__divider" />
            <p className="dash-note">
              The engine does not expose a personal task, class or deadline table, so no
              personal count is shown here.
            </p>
          </HubSection>

          <Panel title="Review rules" index={5} note="Engine-enforced">
            <p className="panel-copy">
              A review you submit is recorded against your account. The correction pipeline runs
              through <span className="mono">aetrix_v5_5</span>; a result that needs a person is
              stopped for review rather than guessed through. Reading a script here never creates
              a mark on its own.
            </p>
            <div className="dash-rulelist">
              <span>
                <Icon name="eye" size={14} /> Read the script and its evidence
              </span>
              <span>
                <Icon name="pen" size={14} /> Review decisions are attributed
              </span>
              <span>
                <Icon name="lock" size={14} /> Workspace administration stays out of scope
              </span>
            </div>
            <Link className="panel-link" to="/assistant/work">
              <Icon name="pen" size={15} />
              Marking workspace
            </Link>
          </Panel>

          <Panel title="Personal records" index={6} note="Not implemented">
            <p className="panel-copy">
              Tasks, personal classes and deadlines have no engine record yet. These links explain
              what the build does and does not hold; they do not show a placeholder queue.
            </p>
            <div className="dash-linkstack">
              <Link className="panel-link" to="/assistant/tasks">
                <Icon name="assignment" size={15} /> Task list
              </Link>
              <Link className="panel-link" to="/assistant/classes">
                <Icon name="classroom" size={15} /> What is in scope
              </Link>
              <Link className="panel-link" to="/assistant/progress">
                <Icon name="chart" size={15} /> Progress definitions
              </Link>
            </div>
          </Panel>
        </aside>
      </div>
    </div>
  )
}

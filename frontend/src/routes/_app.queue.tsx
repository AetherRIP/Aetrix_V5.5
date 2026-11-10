import { useEffect, useRef, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource, type Loaded } from '../lib/api/useResource'
import type { Job, JobDetail, JobState } from '../lib/api/types'
import { queueService } from '../lib/services'

export const Route = createFileRoute('/_app/queue')({
  component: Queue,
})

/** Filtering terminality is not action eligibility.  REVIEW_REQUIRED is shown
 * under "Needs review", but the engine still lets a reviewer cancel it. */
const TERMINAL: JobState[] = ['COMPLETED', 'FAILED', 'CANCELLED', 'REVIEW_REQUIRED']
const RETRYABLE_STATES: JobState[] = ['FAILED', 'RETRY_SUSPENDED']

const FILTERS: { id: string; label: string; match: (job: Job) => boolean }[] = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'active', label: 'Active', match: (job) => !TERMINAL.includes(job.state) },
  {
    id: 'review',
    label: 'Needs review',
    match: (job) => job.state === 'REVIEW_REQUIRED',
  },
  {
    id: 'failed',
    label: 'Failed',
    match: (job) => job.state === 'FAILED' || job.state === 'RETRY_SUSPENDED',
  },
]

type Notice = { tone: 'ok' | 'error'; text: string }

function tone(state: JobState): 'ok' | 'attention' | 'neutral' {
  if (state === 'COMPLETED') return 'ok'
  if (state === 'FAILED' || state === 'REVIEW_REQUIRED' || state === 'RETRY_SUSPENDED') {
    return 'attention'
  }
  return 'neutral'
}

function formatTime(value: string | null): string {
  return value ? new Date(value).toLocaleString() : 'Not recorded'
}

function cancelBlockedReason(job: Job | JobDetail, canReview: boolean): string | null {
  if (!canReview) return 'Your role can view this job but cannot cancel it.'
  if (job.state === 'COMPLETED') return 'Completed jobs cannot be cancelled.'
  if (job.state === 'FAILED') return 'Failed jobs cannot be cancelled; retry instead.'
  if (job.state === 'CANCELLED') return 'This job is already cancelled.'
  if (job.cancel_requested) return 'Cancellation has already been requested.'
  return null
}

function retryBlockedReason(job: Job | JobDetail, canReview: boolean): string | null {
  if (!canReview) return 'Your role can view this job but cannot retry it.'
  if (job.state === 'REVIEW_REQUIRED') {
    return 'Teacher review is required first; retry applies to failed or suspended jobs.'
  }
  if (!RETRYABLE_STATES.includes(job.state)) {
    return `Only failed or suspended jobs can be retried (this job is ${job.state}).`
  }
  if (job.retryable === false) {
    return 'This job exhausted its attempt budget; create a new correction job.'
  }
  return null
}

function actionNote(job: Job | JobDetail, canReview: boolean): string | null {
  const cancelReason = cancelBlockedReason(job, canReview)
  const retryReason = retryBlockedReason(job, canReview)
  if (cancelReason && retryReason) return `${cancelReason} ${retryReason}`
  return cancelReason ?? retryReason
}

function Queue() {
  const session = useEngineSession()
  const [filter, setFilter] = useState('all')
  const [openId, setOpenId] = useState<string | null>(null)
  const [confirmCancelId, setConfirmCancelId] = useState<string | null>(null)
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)

  const [jobsState, reloadJobs] = useResource<Job[]>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => queueService.list(session.tenantId!, { token: session.token, signal })
      : null,
  )
  const [detailState, reloadDetail] = useResource<JobDetail>(
    openId ?? 'none',
    openId && session.token
      ? (signal) => queueService.detail(openId, { token: session.token, signal })
      : null,
  )

  const active = FILTERS.find((entry) => entry.id === filter) ?? FILTERS[0]
  const jobs = jobsState.state === 'ok' ? jobsState.data.filter(active.match) : []
  const canReview = session.capabilities.includes('review')
  const actionsBusy = busyJobId !== null

  async function act(jobId: string, action: 'cancel' | 'retry') {
    if (!session.token || actionsBusy) return
    setBusyJobId(jobId)
    setNotice(null)
    const result =
      action === 'cancel'
        ? await queueService.cancel(jobId, { token: session.token })
        : await queueService.retry(jobId, { token: session.token })
    setBusyJobId(null)
    setConfirmCancelId(null)
    if (result.status === 'ok') {
      setNotice({
        tone: 'ok',
        text:
          action === 'cancel'
            ? `Job ${jobId.slice(0, 8)} is ${result.data.state}. The queue was refreshed from the engine.`
            : `Job ${jobId.slice(0, 8)} is ${result.data.state}. It was returned to the worker queue.`,
      })
      reloadJobs()
      if (openId === jobId) reloadDetail()
    } else {
      setNotice({
        tone: 'error',
        text: `${result.reason}${
          result.status === 'error' && result.errorCode ? ` (${result.errorCode})` : ''
        }`,
      })
    }
  }

  return (
    <div className="app-stack">
      <div className="app-toolbar" aria-label="Queue filters">
        <div className="app-toolbar__tabs" role="group" aria-label="Filter jobs">
          {FILTERS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              className={entry.id === filter ? 'app-tab is-active' : 'app-tab'}
              aria-pressed={entry.id === filter}
              onClick={() => setFilter(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="app-inline-actions">
          <Link className="btn btn--small btn--outline" to="/history">
            Marking history
          </Link>
          <button type="button" className="btn btn--small btn--outline" onClick={reloadJobs}>
            Refresh
          </button>
        </div>
      </div>

      {notice ? (
        <p
          className="app-message"
          data-tone={notice.tone}
          role={notice.tone === 'error' ? 'alert' : 'status'}
          aria-live="polite"
        >
          {notice.text}
        </p>
      ) : null}

      <DataState state={jobsState} capability="GET /api/v1/workspaces/{id}/corrections">
        <Panel title="Correction jobs" note={`${jobs.length} shown`}>
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Correction jobs in this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Job</th>
                  <th scope="col">Submission</th>
                  <th scope="col">State</th>
                  <th scope="col">Progress</th>
                  <th scope="col">Attempts</th>
                  <th scope="col">Error</th>
                  <th scope="col">Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.length > 0 ? (
                  jobs.map((job) => {
                    const cancelReason = cancelBlockedReason(job, canReview)
                    const retryReason = retryBlockedReason(job, canReview)
                    const note = actionNote(job, canReview)
                    return (
                      <tr key={job.id}>
                        <td className="mono">{job.id.slice(0, 8)}</td>
                        <td className="mono">{job.submission_id.slice(0, 8)}</td>
                        <td>
                          <span className="chip app-chip" data-tone={tone(job.state)}>
                            {job.state}
                          </span>
                        </td>
                        <td className="mono">{Math.round(job.progress * 100)}%</td>
                        <td className="mono">
                          {job.attempts}/{job.max_attempts}
                        </td>
                        <td className="mono">{job.error_code ?? '—'}</td>
                        <td>
                          <div className="app-inline-actions">
                            <button
                              type="button"
                              className="btn btn--small btn--outline"
                              onClick={() => {
                                setConfirmCancelId(null)
                                setOpenId(job.id)
                              }}
                            >
                              Detail
                            </button>
                            <button
                              type="button"
                              className="btn btn--small btn--outline"
                              disabled={actionsBusy || Boolean(cancelReason)}
                              title={cancelReason ?? undefined}
                              onClick={() => setConfirmCancelId(job.id)}
                            >
                              Cancel
                            </button>
                            <button
                              type="button"
                              className="btn btn--small btn--outline"
                              disabled={actionsBusy || Boolean(retryReason)}
                              title={retryReason ?? undefined}
                              onClick={() => void act(job.id, 'retry')}
                            >
                              {busyJobId === job.id ? 'Retrying…' : 'Retry'}
                            </button>
                          </div>
                          {note ? <span className="app-action-note">{note}</span> : null}
                        </td>
                      </tr>
                    )
                  })
                ) : (
                  <tr>
                    <td colSpan={7} className="data-table__empty">
                      No jobs match this filter. Jobs appear here once a submission is uploaded
                      and queued.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </DataState>

      {confirmCancelId ? (
        <CancelDialog
          jobId={confirmCancelId}
          busy={busyJobId === confirmCancelId}
          onConfirm={() => void act(confirmCancelId, 'cancel')}
          onClose={() => setConfirmCancelId(null)}
        />
      ) : openId ? (
        <JobDetailDialog
          jobId={openId}
          state={detailState}
          canReview={canReview}
          busy={actionsBusy}
          onClose={() => setOpenId(null)}
          onRefresh={reloadDetail}
          onCancel={() => setConfirmCancelId(openId)}
          onRetry={() => void act(openId, 'retry')}
        />
      ) : null}

      {jobsState.state === 'ok' && jobsState.data.length === 0 ? (
        <StatePanel tone="empty" title="The queue is empty" capability="POST /api/v1/corrections">
          <p>
            Queueing happens automatically after a submission's document is accepted, or from an
            assignment's submission tab.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

function useDialogFocus() {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
    panel?.querySelector<HTMLElement>('[data-autofocus]')?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        const close = panel?.querySelector<HTMLElement>('[data-dialog-close]')
        close?.click()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [])

  return panelRef
}

function CancelDialog({
  jobId,
  busy,
  onConfirm,
  onClose,
}: {
  jobId: string
  busy: boolean
  onConfirm: () => void
  onClose: () => void
}) {
  const panelRef = useDialogFocus()
  return (
    <div
      className="app-modal app-modal--confirm"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        className="app-modal__panel"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="cancel-dialog-title"
        ref={panelRef}
      >
        <div className="app-modal__head">
          <div>
            <p className="app-modal__kicker">Correction job</p>
            <h2 className="app-modal__title" id="cancel-dialog-title">
              Cancel this job?
            </h2>
          </div>
          <button
            type="button"
            className="btn btn--small btn--outline"
            onClick={onClose}
            disabled={busy}
            data-autofocus
            data-dialog-close
          >
            Close
          </button>
        </div>
        <p>
          Cancelling job <span className="mono">{jobId.slice(0, 8)}</span> is terminal. A worker
          already inside a provider call may finish that call, but it will not persist results.
        </p>
        <div className="app-inline-actions">
          <button
            type="button"
            className="btn btn--small"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? 'Cancelling…' : 'Confirm cancel'}
          </button>
          <button
            type="button"
            className="btn btn--small btn--outline"
            onClick={onClose}
            disabled={busy}
          >
            Keep job
          </button>
        </div>
      </div>
    </div>
  )
}

function JobDetailDialog({
  jobId,
  state,
  canReview,
  busy,
  onClose,
  onRefresh,
  onCancel,
  onRetry,
}: {
  jobId: string
  state: Loaded<JobDetail>
  canReview: boolean
  busy: boolean
  onClose: () => void
  onRefresh: () => void
  onCancel: () => void
  onRetry: () => void
}) {
  const panelRef = useDialogFocus()
  const job = state.state === 'ok' ? state.data : null
  const cancelReason = job ? cancelBlockedReason(job, canReview) : null
  const retryReason = job ? retryBlockedReason(job, canReview) : null
  const note = job ? actionNote(job, canReview) : null

  return (
    <div
      className="app-modal"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        className="app-modal__panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby="job-detail-title"
        ref={panelRef}
      >
        <div className="app-modal__head">
          <div>
            <p className="app-modal__kicker">Correction job</p>
            <h2 className="app-modal__title" id="job-detail-title">
              Job detail
            </h2>
            <p className="app-modal__subtitle mono">{jobId.slice(0, 8)}</p>
          </div>
          <button
            type="button"
            className="btn btn--small btn--outline"
            onClick={onClose}
            data-autofocus
            data-dialog-close
          >
            Close
          </button>
        </div>

        <div className="app-modal__body">
          <DataState state={state} capability="GET /api/v1/corrections/{job_id}">
            {job ? <JobDetailBody job={job} /> : null}
          </DataState>

          <div className="app-inline-actions app-modal__actions">
            <button type="button" className="btn btn--small btn--outline" onClick={onRefresh}>
              Refresh detail
            </button>
            {job ? (
              <>
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={busy || Boolean(cancelReason)}
                  title={cancelReason ?? undefined}
                  onClick={onCancel}
                >
                  Cancel job
                </button>
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={busy || Boolean(retryReason)}
                  title={retryReason ?? undefined}
                  onClick={onRetry}
                >
                  {busy ? 'Working…' : 'Retry job'}
                </button>
              </>
            ) : null}
          </div>
          {note ? <p className="app-action-note">{note}</p> : null}
        </div>
      </div>
    </div>
  )
}

function JobDetailBody({ job }: { job: JobDetail }) {
  const provider = job.provider_call
  return (
    <>
      <dl className="app-definitions app-definitions--detail">
        <div>
          <dt>Job ID</dt>
          <dd className="mono app-definitions__id">{job.id}</dd>
        </div>
        <div>
          <dt>Submission ID</dt>
          <dd className="mono app-definitions__id">{job.submission_id}</dd>
        </div>
        <div>
          <dt>Assignment</dt>
          <dd>
            {job.assignment_name ?? 'Not reported'}
            <span className="mono app-detail-muted"> · {job.assignment_id}</span>
          </dd>
        </div>
        <div>
          <dt>State</dt>
          <dd>
            <span className="chip app-chip" data-tone={tone(job.state)}>
              {job.state}
            </span>
          </dd>
        </div>
        <div>
          <dt>Progress</dt>
          <dd className="mono">{Math.round(job.progress * 100)}%</dd>
        </div>
        <div>
          <dt>Attempts</dt>
          <dd className="mono">
            {job.attempts} of {job.max_attempts}
          </dd>
        </div>
        <div>
          <dt>Created</dt>
          <dd>{formatTime(job.created_at)}</dd>
        </div>
        <div>
          <dt>Last updated</dt>
          <dd>{formatTime(job.updated_at)}</dd>
        </div>
        <div>
          <dt>Started</dt>
          <dd>{formatTime(job.started_at)}</dd>
        </div>
        <div>
          <dt>Finished</dt>
          <dd>{formatTime(job.finished_at)}</dd>
        </div>
        <div>
          <dt>Processing stage</dt>
          <dd>
            {job.state}
            {job.resume_state ? ` · resumes at ${job.resume_state}` : ''}
          </dd>
        </div>
        <div>
          <dt>Provider / model</dt>
          <dd>{provider ? `${provider.provider} / ${provider.model}` : 'No provider call recorded'}</dd>
        </div>
        <div>
          <dt>Provider result</dt>
          <dd>
            {provider
              ? `${provider.success ? 'Succeeded' : 'Failed'} · ${provider.purpose} · ${formatTime(provider.created_at)}`
              : 'Not recorded'}
          </dd>
        </div>
        <div>
          <dt>Error</dt>
          <dd className="mono">
            {job.error_code
              ? `${job.error_code}: ${job.error_message ?? 'No message recorded'}`
              : 'None recorded'}
          </dd>
        </div>
        <div>
          <dt>Review required reason</dt>
          <dd>
            {job.review_reasons.length > 0 ? (
              <ul className="app-reasons">
                {job.review_reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>
            ) : job.state === 'REVIEW_REQUIRED' ? (
              'The engine did not record a reason.'
            ) : (
              'Not required'
            )}
          </dd>
        </div>
        <div>
          <dt>Cancellation</dt>
          <dd>{job.cancel_requested ? 'Requested' : 'Not requested'}</dd>
        </div>
      </dl>

      <section className="app-modal__section">
        <h3 className="app-modal__section-title">Submission</h3>
        {job.submission ? (
          <dl className="app-definitions app-definitions--detail">
            <div>
              <dt>Student reference</dt>
              <dd>{job.submission.student_ref}</dd>
            </div>
            <div>
              <dt>Submission status</dt>
              <dd className="mono">{job.submission.status}</dd>
            </div>
            <div>
              <dt>Content hash</dt>
              <dd className="mono app-definitions__id">{job.submission.content_hash}</dd>
            </div>
          </dl>
        ) : (
          <p className="app-hint">No authorised submission record was returned for this job.</p>
        )}
      </section>

      <section className="app-modal__section">
        <h3 className="app-modal__section-title">
          Documents <span className="app-detail-muted">({job.documents.length})</span>
        </h3>
        {job.documents.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Documents attached to the submission</caption>
              <thead>
                <tr>
                  <th scope="col">File</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Pages</th>
                  <th scope="col">Status</th>
                  <th scope="col">Ordering</th>
                  <th scope="col">Mapping</th>
                </tr>
              </thead>
              <tbody>
                {job.documents.map((document) => (
                  <tr key={document.id}>
                    <td>{document.original_filename || 'Unnamed document'}</td>
                    <td className="mono">{document.kind}</td>
                    <td className="mono">{document.page_count}</td>
                    <td className="mono">{document.status}</td>
                    <td className="mono">{document.ordering_status}</td>
                    <td className="mono">{document.mapping_status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="app-hint">No document is recorded for this submission.</p>
        )}
      </section>

      <section className="app-modal__section">
        <h3 className="app-modal__section-title">
          Review decisions <span className="app-detail-muted">({job.review_decisions.length})</span>
        </h3>
        {job.review_decisions.length > 0 ? (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Review decisions recorded for this job</caption>
              <thead>
                <tr>
                  <th scope="col">Question</th>
                  <th scope="col">Reason</th>
                  <th scope="col">Mode</th>
                  <th scope="col">Outcome</th>
                  <th scope="col">Decided</th>
                </tr>
              </thead>
              <tbody>
                {job.review_decisions.map((decision) => (
                  <tr key={`${decision.question_id}-${decision.created_at}`}>
                    <td className="mono">{decision.question_id}</td>
                    <td>{decision.requested_reason}</td>
                    <td className="mono">{decision.mode}</td>
                    <td className="mono">{decision.outcome ?? 'Pending'}</td>
                    <td className="mono">
                      {decision.decided_by
                        ? `${decision.decided_by} · ${formatTime(decision.decided_at)}`
                        : 'Not decided'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="app-hint">No review decision has been recorded.</p>
        )}
      </section>

      <section className="app-modal__section">
        <h3 className="app-modal__section-title">State transitions</h3>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Job state transitions</caption>
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">From</th>
                <th scope="col">To</th>
                <th scope="col">Actor</th>
                <th scope="col">When</th>
              </tr>
            </thead>
            <tbody>
              {job.events.length > 0 ? (
                job.events.map((event) => (
                  <tr key={event.id}>
                    <td className="mono">{event.event_seq}</td>
                    <td className="mono">{event.from_state ?? '—'}</td>
                    <td className="mono">{event.to_state}</td>
                    <td>{event.actor}</td>
                    <td className="mono">{formatTime(event.created_at)}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={5} className="data-table__empty">
                    No transitions recorded for this job.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}

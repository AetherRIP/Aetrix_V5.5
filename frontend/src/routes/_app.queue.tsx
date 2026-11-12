import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { createPortal } from 'react-dom'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { JobDetailRecord } from '../components/app/JobDetailRecord'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource, type Loaded } from '../lib/api/useResource'
import type { Job, JobDetail, JobState } from '../lib/api/types'
import { engineProvenance, jobTone } from '../lib/jobs/presentation'
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

function recoverBlockedReason(job: Job | JobDetail, canApprove: boolean): string | null {
  if (!canApprove) return 'Your role can view this job but cannot re-mark a refused paper.'
  if (job.state !== 'REVIEW_REQUIRED') {
    return `Only a refused run waiting for review can be re-marked (this job is ${job.state}).`
  }
  if (job.result_source !== 'AUTOMATED_REFUSED') {
    return 'This run was not refused by the result guard, so there is nothing to re-mark.'
  }
  return null
}

function actionNote(
  job: Job | JobDetail,
  canReview: boolean,
  canApprove: boolean,
): string | null {
  // A refused run has exactly one way forward: a fresh, linked job. Showing the
  // retry note beside it would name the wrong action.
  if (job.result_source === 'AUTOMATED_REFUSED') {
    return recoverBlockedReason(job, canApprove)
  }
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
  const [confirmRecoverId, setConfirmRecoverId] = useState<string | null>(null)
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
  const allJobs = jobsState.state === 'ok' ? jobsState.data : []
  const jobs = allJobs.filter(active.match)
  const activeCount = allJobs.filter((job) => !TERMINAL.includes(job.state)).length
  const reviewCount = allJobs.filter((job) => job.state === 'REVIEW_REQUIRED').length
  const canReview = session.capabilities.includes('review')
  const canApprove = session.capabilities.includes('approve')
  const actionsBusy = busyJobId !== null

  async function act(jobId: string, action: 'cancel' | 'retry' | 'recover', reason?: string) {
    if (!session.token || actionsBusy) return
    setBusyJobId(jobId)
    setNotice(null)
    const result =
      action === 'cancel'
        ? await queueService.cancel(jobId, { token: session.token })
        : action === 'retry'
          ? await queueService.retry(jobId, { token: session.token })
          : await queueService.recover(jobId, { reason: reason ?? '' }, { token: session.token })
    setBusyJobId(null)
    setConfirmCancelId(null)
    setConfirmRecoverId(null)
    if (result.status === 'ok') {
      setNotice({
        tone: 'ok',
        text:
          action === 'cancel'
            ? `Job ${jobId.slice(0, 8)} is ${result.data.state}. The queue was refreshed from the engine.`
            : action === 'retry'
              ? `Job ${jobId.slice(0, 8)} is ${result.data.state}. It was returned to the worker queue.`
              : `Job ${jobId.slice(0, 8)} was refused. Job ${result.data.id.slice(0, 8)} is ${result.data.state} and will mark the paper again; the refused run stays as evidence.`,
      })
      reloadJobs()
      if (openId === jobId) reloadDetail()
      if (action === 'recover') setOpenId(result.data.id)
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
    <div className="rd-desk rd-queue">
      <header className="rd-hero">
        <div className="rd-hero__copy">
          {/* The shell renders the route h1; this is the record line. */}
          <p className="rd-hero__kicker mono">Queue</p>
          <p className="rd-hero__ref">
            {jobs.length} job{jobs.length === 1 ? '' : 's'} shown
          </p>
          <p className="rd-hero__sub">
            <span>{active.label}</span>
            <span aria-hidden="true">·</span>
            <span className="mono">{activeCount} active</span>
            <span aria-hidden="true">·</span>
            <span className="mono">{reviewCount} awaiting review</span>
          </p>
        </div>
        <div className="rd-hero__actions">
          <Link className="btn btn--small btn--outline" to="/history">
            Marking history
          </Link>
          <button type="button" className="btn btn--small btn--outline" onClick={reloadJobs}>
            Refresh
          </button>
        </div>
      </header>

      <div className="rd-seg" role="group" aria-label="Filter jobs">
        {FILTERS.map((entry) => (
          <button
            key={entry.id}
            type="button"
            className="rd-seg__btn"
            aria-pressed={entry.id === filter}
            onClick={() => setFilter(entry.id)}
          >
            {entry.label}
          </button>
        ))}
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
        <section
          className="rd-pane"
          style={{ '--i': 0 } as CSSProperties}
          aria-label="Correction jobs"
        >
          <div className="rd-pane__head">
            <h2 className="rd-pane__title">Jobs</h2>
            <span className="rd-pane__note mono">{jobs.length} shown</span>
          </div>

          {jobs.length > 0 ? (
            <ul className="rd-queue__list">
              {jobs.map((job) => {
                const engine = engineProvenance(job)
                const cancelReason = cancelBlockedReason(job, canReview)
                const retryReason = retryBlockedReason(job, canReview)
                const recoverReason = recoverBlockedReason(job, canApprove)
                const note = actionNote(job, canReview, canApprove)
                return (
                  <li
                    key={job.id}
                    className="rd-queue__row"
                    data-attention={jobTone(job.state) === 'attention' ? 'true' : undefined}
                  >
                    <div className="rd-queue__id">
                      <span className="mono">{job.id.slice(0, 8)}</span>
                      <span className="rd-queue__ref mono">
                        submission {job.submission_id.slice(0, 8)}
                      </span>
                    </div>

                    <div className="rd-queue__state">
                      <span className="chip app-chip" data-tone={jobTone(job.state)}>
                        {job.state}
                      </span>
                      <span className="rd-queue__hint mono">
                        {Math.round(job.progress * 100)}% · {job.attempts}/{job.max_attempts}{' '}
                        attempts
                      </span>
                      {job.error_code ? (
                        <span className="rd-queue__hint mono">{job.error_code}</span>
                      ) : null}
                      <span
                        className="rd-queue__hint mono rd-queue__engine"
                        data-recorded={engine.recorded ? 'true' : 'false'}
                        title={
                          engine.recorded
                            ? 'The correction engine that produced this run'
                            : 'This job carries no recorded engine'
                        }
                      >
                        {engine.label}
                      </span>
                    </div>

                    <div
                      className="rd-meter"
                      style={
                        { '--fill': Math.min(1, Math.max(0, job.progress)) } as CSSProperties
                      }
                      role="img"
                      aria-label={`${Math.round(job.progress * 100)}% progress`}
                    >
                      <span />
                    </div>

                    <div className="rd-queue__actions">
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
                      {job.result_source === 'AUTOMATED_REFUSED' ? (
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          disabled={actionsBusy || Boolean(recoverReason)}
                          title={recoverReason ?? undefined}
                          onClick={() => setConfirmRecoverId(job.id)}
                        >
                          Re-mark
                        </button>
                      ) : (
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          disabled={actionsBusy || Boolean(retryReason)}
                          title={retryReason ?? undefined}
                          onClick={() => void act(job.id, 'retry')}
                        >
                          {busyJobId === job.id ? 'Retrying…' : 'Retry'}
                        </button>
                      )}
                    </div>

                    {/* Why an action is disabled belongs on its own line, not
                        inside the action cell where it widens the column. */}
                    {note ? <p className="rd-queue__note">{note}</p> : null}
                  </li>
                )
              })}
            </ul>
          ) : (
            <p className="rd-queue__empty">
              No jobs match this filter. Jobs appear here once a submission is uploaded and
              queued.
            </p>
          )}
        </section>
      </DataState>

      {confirmCancelId ? (
        <CancelDialog
          jobId={confirmCancelId}
          busy={busyJobId === confirmCancelId}
          onConfirm={() => void act(confirmCancelId, 'cancel')}
          onClose={() => setConfirmCancelId(null)}
        />
      ) : confirmRecoverId ? (
        <RecoverDialog
          jobId={confirmRecoverId}
          busy={busyJobId === confirmRecoverId}
          onConfirm={(reason) => void act(confirmRecoverId, 'recover', reason)}
          onClose={() => setConfirmRecoverId(null)}
        />
      ) : openId ? (
        <JobDetailDialog
          state={detailState}
          canReview={canReview}
          canApprove={canApprove}
          busy={actionsBusy}
          onClose={() => setOpenId(null)}
          onRefresh={reloadDetail}
          onCancel={() => setConfirmCancelId(openId)}
          onRetry={() => void act(openId, 'retry')}
          onRecover={() => setConfirmRecoverId(openId)}
        />
      ) : null}

      {jobsState.state === 'ok' && allJobs.length === 0 ? (
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
        className="app-modal__panel rd-modal"
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

function RecoverDialog({
  jobId,
  busy,
  onConfirm,
  onClose,
}: {
  jobId: string
  busy: boolean
  onConfirm: (reason: string) => void
  onClose: () => void
}) {
  const panelRef = useDialogFocus()
  const [reason, setReason] = useState('')
  const valid = reason.trim().length >= 5

  return (
    <div
      className="app-modal app-modal--confirm"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        className="app-modal__panel rd-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="recover-dialog-title"
        ref={panelRef}
      >
        <div className="app-modal__head">
          <div>
            <p className="app-modal__kicker">Refused marking run</p>
            <h2 className="app-modal__title" id="recover-dialog-title">
              Re-mark this paper
            </h2>
            <p className="app-modal__subtitle mono">{jobId.slice(0, 8)}</p>
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
          This run was refused because the engine could not trust its own result. A new
          correction job will mark the paper again, pinned to the engine that produced this
          run. The refused run's marks, evidence and refusal stay exactly as they are.
        </p>
        <label className="app-modal__field">
          <span className="app-modal__kicker">Why is this being re-marked?</span>
          <textarea
            className="app-input"
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            maxLength={2000}
            aria-label="Reason for re-marking this paper"
          />
        </label>
        {valid ? null : (
          <p className="app-hint">A reason of at least five characters is required.</p>
        )}
        <div className="app-inline-actions">
          <button
            type="button"
            className="btn btn--small"
            onClick={() => onConfirm(reason.trim())}
            disabled={busy || !valid}
          >
            {busy ? 'Starting…' : 'Start re-mark'}
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
  state,
  canReview,
  canApprove,
  busy,
  onClose,
  onRefresh,
  onCancel,
  onRetry,
  onRecover,
}: {
  state: Loaded<JobDetail>
  canReview: boolean
  canApprove: boolean
  busy: boolean
  onClose: () => void
  onRefresh: () => void
  onCancel: () => void
  onRetry: () => void
  onRecover: () => void
}) {
  const panelRef = useDialogFocus()
  const job = state.state === 'ok' ? state.data : null
  const cancelReason = job ? cancelBlockedReason(job, canReview) : null
  const retryReason = job ? retryBlockedReason(job, canReview) : null
  const recoverReason = job ? recoverBlockedReason(job, canApprove) : null
  const note = job ? actionNote(job, canReview, canApprove) : null

  // The record is portalled to the body: the workspace content creates its own
  // stacking context, so an in-place dialog cannot cover the fixed tab bar on a
  // phone. The dialog only mounts after a click, so there is no SSR divergence.
  return createPortal(
    <div
      className="app-modal"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target) onClose()
      }}
    >
      <div
        className="app-modal__panel rd-modal rd-job__panel"
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

        <div className="app-modal__body rd-job__body">
          <DataState state={state} capability="GET /api/v1/corrections/{job_id}">
            {job ? <JobDetailRecord job={job} /> : null}
          </DataState>

          <div className="app-inline-actions app-modal__actions rd-job__footer">
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
                {job.result_source === 'AUTOMATED_REFUSED' ? (
                  <button
                    type="button"
                    className="btn btn--small btn--outline"
                    disabled={busy || Boolean(recoverReason)}
                    title={recoverReason ?? undefined}
                    onClick={onRecover}
                  >
                    Re-mark paper
                  </button>
                ) : null}
              </>
            ) : null}
          </div>
          {note ? <p className="app-action-note rd-job__note">{note}</p> : null}
        </div>
      </div>
    </div>,
    document.body,
  )
}


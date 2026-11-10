import { useEffect, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { JobResults, PageMeta, QuestionResult, Submission } from '../lib/api/types'
import { resultsService, submissionService } from '../lib/services'

export const Route = createFileRoute('/_app/submissions/$submissionId')({
  component: SubmissionReview,
})

function statusTone(status: string): 'ok' | 'attention' | 'neutral' {
  if (status === 'AWARDED' || status === 'ZERO') return 'ok'
  if (status === 'REVIEW_REQUIRED') return 'attention'
  return 'neutral'
}

function QuestionRow({
  result,
  jobId,
  token,
  recordVersion,
  onChanged,
  canReview,
}: {
  result: QuestionResult
  jobId: string
  token: string | null
  recordVersion: number
  onChanged: () => void
  canReview: boolean
}) {
  const [marks, setMarks] = useState(String(result.awarded_marks))
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function override(event: React.FormEvent) {
    event.preventDefault()
    if (!token) return
    const awarded = Number.parseInt(marks, 10)
    if (Number.isNaN(awarded) || awarded < 0 || awarded > result.max_marks) {
      setError(`Enter a whole number between 0 and ${result.max_marks}.`)
      return
    }
    if (reason.trim().length < 5) {
      setError('A stated reason of at least five characters is required.')
      return
    }
    setBusy(true)
    setError(null)
    const response = await resultsService.override(
      result.id,
      { awarded_marks: awarded, reason: reason.trim(), expected_record_version: recordVersion },
      { token },
    )
    setBusy(false)
    if (response.status === 'ok') {
      setReason('')
      onChanged()
    } else {
      setError(response.reason)
    }
  }

  async function uphold() {
    if (!token) return
    if (reason.trim().length < 5) {
      setError('A stated reason of at least five characters is required.')
      return
    }
    setBusy(true)
    setError(null)
    const response = await resultsService.review(
      jobId,
      result.question_id,
      { decision: 'UPHOLD', reason: reason.trim() },
      { token },
    )
    setBusy(false)
    if (response.status === 'ok') {
      setReason('')
      onChanged()
    } else {
      setError(response.reason)
    }
  }

  return (
    <div className="app-question">
      <div className="app-question__head">
        <span className="mono app-question__id">{result.question_id}</span>
        <span className="mono">
          {result.awarded_marks} / {result.max_marks}
        </span>
        <span className="chip app-chip" data-tone={statusTone(result.status)}>
          {result.status}
        </span>
        {result.confidence !== null ? (
          <span className="mono app-hint">confidence {result.confidence.toFixed(2)}</span>
        ) : null}
      </div>

      {result.student_answer ? (
        <p className="app-card__body">
          <strong>Answer:</strong> {result.student_answer}
        </p>
      ) : null}

      {result.criteria.length ? (
        <ul className="app-criteria">
          {result.criteria.map((criterion) => (
            <li key={criterion.id} className="app-criteria__row">
              <span className="chip app-chip" data-tone={criterion.awarded ? 'ok' : 'neutral'}>
                {criterion.code} {criterion.awarded ? 'awarded' : 'not awarded'}
              </span>
              <span className="app-criteria__reason">{criterion.reason ?? '—'}</span>
            </li>
          ))}
        </ul>
      ) : null}

      {result.scheme_concerns.length ? (
        <ul className="app-concerns">
          {result.scheme_concerns.map((concern, index) => (
            <li key={`${concern.code ?? 'concern'}-${index}`}>
              <span className="mono">{concern.code ?? 'NOTE'}</span> {concern.message ?? ''}
            </li>
          ))}
        </ul>
      ) : null}

      {canReview ? (
        <form className="app-form app-form--inline" onSubmit={override}>
          <input
            className="app-input app-input--narrow"
            type="number"
            min={0}
            max={result.max_marks}
            value={marks}
            onChange={(event) => setMarks(event.target.value)}
            aria-label={`Mark for question ${result.question_id}`}
          />
          <input
            className="app-input"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Reason for the change (required)"
            aria-label={`Reason for changing question ${result.question_id}`}
            maxLength={2000}
          />
          <button type="submit" className="btn btn--small btn--outline" disabled={busy}>
            {busy ? 'Saving…' : 'Override'}
          </button>
          {result.review_required ? (
            <button
              type="button"
              className="btn btn--small btn--outline"
              disabled={busy}
              onClick={() => void uphold()}
              title="Keep the engine's award and clear the review flag"
            >
              Uphold award
            </button>
          ) : null}
          {error ? <span className="app-form__error">{error}</span> : null}
        </form>
      ) : null}
    </div>
  )
}

function SubmissionReview() {
  const { submissionId } = Route.useParams()
  const session = useEngineSession()
  const [pageIndex, setPageIndex] = useState(1)
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imageError, setImageError] = useState<string | null>(null)
  const [approvalNote, setApprovalNote] = useState('')
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)

  const [submissionState] = useResource<Submission>(
    submissionId,
    session.token
      ? (signal) => submissionService.get(submissionId, { token: session.token, signal })
      : null,
  )
  const [resultsState, reloadResults] = useResource<JobResults>(
    submissionId,
    session.token
      ? (signal) => submissionService.results(submissionId, { token: session.token, signal })
      : null,
  )
  const [pagesState] = useResource<PageMeta[]>(
    submissionId,
    session.token
      ? (signal) => submissionService.pages(submissionId, { token: session.token, signal })
      : null,
  )

  const pages = pagesState.state === 'ok' ? pagesState.data : []
  const pageCount = pages.length

  useEffect(() => {
    if (!session.token || pageCount === 0) return
    const controller = new AbortController()
    let objectUrl: string | null = null
    setImageError(null)
    void submissionService
      .pageImage(submissionId, pageIndex, { token: session.token, signal: controller.signal })
      .then((result) => {
        if (result.status === 'ok') {
          objectUrl = URL.createObjectURL(result.data)
          setImageUrl(objectUrl)
        } else if (result.status === 'error') {
          setImageError(result.reason)
        }
      })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
      setImageUrl(null)
    }
  }, [submissionId, pageIndex, session.token, pageCount])

  const results = resultsState.state === 'ok' ? resultsState.data : null
  const canApprove = session.capabilities.includes('approve')
  const canReview = session.capabilities.includes('review')
  const unresolved = results ? results.totals.review_required : 0

  async function approve() {
    if (!session.token || !results) return
    setApproving(true)
    setApprovalError(null)
    const response = await resultsService.approve(
      results.job_id,
      { note: approvalNote.trim() || undefined, expected_record_version: results.record_version },
      { token: session.token },
    )
    setApproving(false)
    if (response.status === 'ok') {
      setApprovalNote('')
      reloadResults()
    } else {
      setApprovalError(response.reason)
    }
  }

  return (
    <div className="app-stack">
      <section className="record-head" aria-label="Submission record">
        <div>
          <p className="record-head__kicker mono">Submission</p>
          <p className="record-head__id mono">
            {results ? results.student_ref : submissionId}
          </p>
        </div>
        <div className="record-head__meta">
          <span className="chip app-chip" data-tone={results ? 'ok' : 'attention'}>
            {submissionState.state === 'ok' ? submissionState.data.status : 'Not loaded'}
          </span>
          <Link className="btn btn--small btn--outline" to="/queue">
            Back to queue
          </Link>
        </div>
      </section>

      {resultsState.state === 'error' && resultsState.code === 404 ? (
        <StatePanel
          tone="empty"
          title="This submission has not produced marks yet"
          capability="POST /api/v1/corrections"
        >
          <p>
            The engine has no correction job results for this submission. Queue a job once its
            scheme and blueprint are approved; this screen updates when the worker finishes.
          </p>
          <p>
            <button type="button" className="btn btn--small btn--outline" onClick={reloadResults}>
              Check again
            </button>
          </p>
        </StatePanel>
      ) : (
        <DataState state={resultsState} capability="GET /api/v1/submissions/{id}/results">
          {results ? (
            <Panel
              title="Result summary"
              note={`${results.job_state} · ${results.totals.awarded}/${results.totals.total} marks`}
            >
              <dl className="app-definitions">
                <div>
                  <dt>Questions marked</dt>
                  <dd className="mono">{results.totals.questions}</dd>
                </div>
                <div>
                  <dt>Needs review</dt>
                  <dd className="mono">{results.totals.review_required}</dd>
                </div>
                <div>
                  <dt>Approval</dt>
                  <dd>
                    {results.totals.approved
                      ? `Approved by ${results.approved_by ?? 'a teacher'} on ${results.approved_at ? new Date(results.approved_at).toLocaleString() : ''}`
                      : 'Provisional — not approved'}
                  </dd>
                </div>
              </dl>
              <div className="app-inline-actions">
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  onClick={reloadResults}
                >
                  Refresh results
                </button>
                {canApprove ? (
                  <>
                    <input
                      className="app-input"
                      value={approvalNote}
                      onChange={(event) => setApprovalNote(event.target.value)}
                      placeholder="Approval note (optional)"
                      aria-label="Approval note"
                    />
                    <button
                      type="button"
                      className="btn btn--small btn--primary"
                      disabled={approving || results.totals.approved || unresolved > 0}
                      onClick={() => void approve()}
                      title={
                        unresolved > 0
                          ? 'Resolve every question that needs review first'
                          : undefined
                      }
                    >
                      {approving ? 'Approving…' : results.totals.approved ? 'Approved' : 'Approve results'}
                    </button>
                  </>
                ) : null}
              </div>
              {approvalError ? <p className="app-form__error">{approvalError}</p> : null}
            </Panel>
          ) : null}

          <div className="app-split">
            <Panel title="Script pages" note={pageCount ? `${pageCount} page(s)` : 'No pages'}>
              {imageError ? <p className="app-form__error">{imageError}</p> : null}
              {imageUrl ? (
                <img className="app-page-image" src={imageUrl} alt={`Page ${pageIndex}`} />
              ) : pagesState.state === 'ok' && pageCount === 0 ? (
                <p className="app-card__body">
                  This submission has no stored document, so there is nothing to display.
                </p>
              ) : (
                <p className="app-hint mono">Loading page {pageIndex}…</p>
              )}
              <div className="app-inline-actions">
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={pageIndex <= 1}
                  onClick={() => setPageIndex((value) => Math.max(1, value - 1))}
                >
                  Previous
                </button>
                <span className="mono app-hint">
                  {pageCount ? `Page ${pageIndex} of ${pageCount}` : 'No pages'}
                </span>
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={pageCount === 0 || pageIndex >= pageCount}
                  onClick={() => setPageIndex((value) => Math.min(pageCount, value + 1))}
                >
                  Next
                </button>
              </div>
            </Panel>

            <Panel title="Question evidence" note="Marks, reasons and uncertainty">
              {results && results.questions.length ? (
                <div className="app-stack">
                  {results.questions.map((question) => (
                    <QuestionRow
                      key={question.id}
                      result={question}
                      jobId={results.job_id}
                      token={session.token}
                      recordVersion={results.record_version}
                      onChanged={reloadResults}
                      canReview={canReview}
                    />
                  ))}
                </div>
              ) : (
                <p className="app-card__body">
                  The job has produced no question results yet. Nothing is inferred here.
                </p>
              )}
            </Panel>
          </div>
        </DataState>
      )}
    </div>
  )
}

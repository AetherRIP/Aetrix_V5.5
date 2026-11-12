import { useEffect, useState, type CSSProperties } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import { isDecidedState, markLabel, questionState, stateLabel } from '../lib/results/presentation'
import type {
  JobResults,
  PageMeta,
  QuestionResult,
  Submission,
  Verification,
} from '../lib/api/types'
import { queueService, resultsService, submissionService } from '../lib/services'

export const Route = createFileRoute('/_app/submissions/$submissionId')({
  component: SubmissionReview,
})

function statusTone(status: string): 'ok' | 'attention' | 'neutral' {
  if (status === 'AWARDED' || status === 'ZERO') return 'ok'
  if (status === 'REVIEW_REQUIRED') return 'attention'
  return 'neutral'
}


/** A mark as a proportion of what the question is worth. */
function fillVar(awarded: number, maximum: number): CSSProperties {
  const ratio = maximum > 0 ? Math.min(1, Math.max(0, awarded / maximum)) : 0
  return { '--fill': ratio } as CSSProperties
}

function numberField(detail: Record<string, unknown>, key: string): number | null {
  const value = detail[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function textField(detail: Record<string, unknown>, key: string): string | null {
  const value = detail[key]
  return typeof value === 'string' && value.trim() ? value : null
}

function verificationTone(verification: Verification): 'ok' | 'attention' | 'neutral' {
  if (verification.kind === 'DOUBLE_CHECK') {
    if (verification.status === 'AGREES') return 'ok'
    if (verification.status === 'DISAGREES') return 'attention'
    return 'neutral'
  }
  if (verification.kind === 'MATHEMATICAL') {
    if (verification.status === 'EQUIVALENT') return 'ok'
    if (verification.status === 'DIFFERENT') return 'attention'
    return 'neutral'
  }
  return verification.status === 'PASS' ? 'ok' : 'attention'
}

function verificationLabel(verification: Verification): string {
  if (verification.kind === 'DOUBLE_CHECK') return `Second examiner · ${verification.status}`
  if (verification.kind === 'MATHEMATICAL') return `Mathematics · ${verification.status}`
  return `Integrity · ${verification.status}`
}

/**
 * What the record actually proves.
 *
 * A second award is evidence for a person, never a replacement: the first award
 * stands until someone decides, so a disagreement names both numbers. An
 * expression comparison only says the two expressions agree — it does not
 * certify that the expected answer is right, so it is quoted beside the award.
 */
function verificationMessage(verification: Verification): string {
  const { detail, status } = verification
  if (verification.kind === 'DOUBLE_CHECK') {
    const first = numberField(detail, 'first_awarded')
    const second = numberField(detail, 'second_awarded')
    const max = numberField(detail, 'max_marks')
    const outOf = max === null ? '' : ` of ${max}`
    if (status === 'DISAGREES' && first !== null && second !== null) {
      return `First examiner awarded ${first}${outOf}; the second examiner awarded ${second}${outOf}. The first award stands until a person decides.`
    }
    if (status === 'AGREES' && first !== null && second !== null) {
      return `Both examiners awarded ${first}${outOf}.`
    }
    if (status === 'UNVERIFIABLE') {
      return 'The second marking could not be read, so it is not evidence of agreement or disagreement.'
    }
    return 'A second marking was recorded for this question.'
  }
  if (verification.kind === 'MATHEMATICAL') {
    const student = textField(detail, 'student_expression')
    const expected = textField(detail, 'expected_expression')
    const pair =
      student && expected ? ` The script states ${student}; the marker expected ${expected}.` : ''
    if (status === 'EQUIVALENT') {
      return `SymPy found the final answer equivalent to the expected expression.${pair}`
    }
    if (status === 'DIFFERENT') {
      return `SymPy found the final answer different from the expected expression.${pair}`
    }
    return `The expressions could not be compared, so this check proved nothing.${pair}`
  }
  return status === 'PASS'
    ? 'The award is internally consistent with what the marker reported.'
    : 'The award failed an internal consistency check.'
}

function QuestionRow({
  result,
  verifications,
  jobId,
  token,
  recordVersion,
  onChanged,
  canReview,
}: {
  result: QuestionResult
  verifications: Verification[]
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
  const state = questionState(result)
  const decided = isDecidedState(state)

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
    <article
      className="rd-row"
      data-review={result.review_required ? 'true' : undefined}
      aria-label={`Question ${result.question_id}`}
    >
      <div className="rd-row__gutter">
        <span className="rd-row__id">{result.question_id}</span>
        {decided ? (
          <span className="rd-row__marks mono">
            {result.awarded_marks} / {result.max_marks}
          </span>
        ) : (
          /* An undecided question has no mark: printing 0 / max would state a
             zero the engine never decided. */
          <span className="rd-row__marks mono" data-undecided="true">
            {markLabel(result)}
          </span>
        )}
        {decided ? (
          <span
            className="rd-row__meter"
            style={fillVar(result.awarded_marks, result.max_marks)}
            aria-hidden="true"
          >
            <span />
          </span>
        ) : null}
        <span className="rd-row__state mono">{stateLabel(state)}</span>
      </div>

      <div className="rd-row__body">
        <div className="rd-row__head">
          <span className="chip app-chip" data-tone={statusTone(result.status)}>
            {result.status}
          </span>
          {result.confidence !== null ? (
            <span className="mono app-hint">{result.confidence.toFixed(2)} confidence</span>
          ) : null}
        </div>

        {result.student_answer ? (
          <p className="rd-row__answer">
            <span className="rd-row__label mono">Answer</span>
            {result.student_answer}
          </p>
        ) : decided ? (
          <p className="rd-row__empty">
            {state === 'CONFIRMED_ZERO'
              ? 'No answer was read for this question, so nothing was awarded.'
              : 'No answer text was recorded for this question.'}
          </p>
        ) : null}

        {!decided ? (
          <p className="rd-row__empty">
            {state === 'UNMARKED'
              ? 'This question was not marked, so it has no award. It is not a zero.'
              : 'The engine has no decided award for this question, so no mark is shown. A person needs to decide it.'}
          </p>
        ) : null}

        {decided &&
        result.normalisation_anomaly !== null &&
        result.raw_awarded_marks !== null &&
        result.raw_awarded_marks !== result.awarded_marks ? (
          <p className="rd-row__raw mono">
            Model awarded {result.raw_awarded_marks} of {result.max_marks} (
            {result.normalisation_anomaly}); the stored award is {result.awarded_marks}.
          </p>
        ) : null}

        {result.criteria.length ? (
          <ul className="rd-criteria">
            {result.criteria.map((criterion) => (
              <li key={criterion.id} className="rd-criteria__row">
                <span className="chip app-chip" data-tone={criterion.awarded ? 'ok' : 'neutral'}>
                  {criterion.code} {criterion.awarded ? 'awarded' : 'not awarded'}
                </span>
                <span>{criterion.reason ?? '—'}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {result.scheme_concerns.length ? (
          <ul className="rd-concerns">
            {result.scheme_concerns.map((concern, index) => (
              <li key={`${concern.code ?? 'concern'}-${index}`}>
                <span className="mono">{concern.code ?? 'NOTE'}</span> {concern.message ?? ''}
              </li>
            ))}
          </ul>
        ) : null}

        {verifications.length ? (
          <ul className="rd-verifications" aria-label={`Verification for question ${result.question_id}`}>
            {verifications.map((verification) => (
              <li
                key={`${verification.kind}-${verification.status}`}
                className="rd-verifications__row"
              >
                <span className="chip app-chip" data-tone={verificationTone(verification)}>
                  {verificationLabel(verification)}
                </span>
                <span>{verificationMessage(verification)}</span>
              </li>
            ))}
          </ul>
        ) : null}

        {canReview ? (
          <details className="rd-override" open={result.review_required}>
            <summary className="rd-override__summary">Change this mark</summary>
            <form className="rd-override__form" onSubmit={override}>
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
          </details>
        ) : null}
      </div>
    </article>
  )
}

function SubmissionReview() {
  const { submissionId } = Route.useParams()
  const session = useEngineSession()
  const [pageIndex, setPageIndex] = useState(1)
  const [flip, setFlip] = useState<'next' | 'prev'>('next')
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [imageError, setImageError] = useState<string | null>(null)
  const [approvalNote, setApprovalNote] = useState('')
  const [approvalError, setApprovalError] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const [recoveryReason, setRecoveryReason] = useState('')
  const [recoveryError, setRecoveryError] = useState<string | null>(null)
  const [recovering, setRecovering] = useState(false)

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
  // An examiner reads the script in paper order, not in arrival order.
  const orderedQuestions = results
    ? [...results.questions].sort((a, b) =>
        a.question_id.localeCompare(b.question_id, undefined, { numeric: true }),
      )
    : []
  // Verification records are per question; group them so a row shows its own
  // verdicts instead of repeating the whole paper's findings on every mark.
  const verificationsByQuestion: Record<string, Verification[]> = {}
  for (const verification of results?.verifications ?? []) {
    const existing = verificationsByQuestion[verification.question_id]
    if (existing) existing.push(verification)
    else verificationsByQuestion[verification.question_id] = [verification]
  }
  const doubleChecks = results
    ? results.verifications.filter((verification) => verification.kind === 'DOUBLE_CHECK')
    : []
  const disagreements = doubleChecks.filter(
    (verification) => verification.status === 'DISAGREES',
  ).length
  const canApprove = session.capabilities.includes('approve')
  const canReview = session.capabilities.includes('review')
  const refusedNewerId = results?.refused_newer_job_id ?? null
  const unresolved = results ? results.totals.review_required : 0
  const tallyFill =
    results && results.totals.total > 0
      ? Math.min(1, Math.max(0, results.totals.awarded / results.totals.total))
      : 0

  function turn(delta: number) {
    setFlip(delta > 0 ? 'next' : 'prev')
    setPageIndex((value) => Math.min(Math.max(1, value + delta), Math.max(1, pageCount)))
  }

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

  /**
   * Re-mark the refused run. This creates a new job pinned to the engine that
   * produced the refusal; nothing about the refused run changes.
   */
  async function recoverPaper(jobId: string) {
    if (!session.token || recovering) return
    if (recoveryReason.trim().length < 5) {
      setRecoveryError('A reason of at least five characters is required.')
      return
    }
    setRecovering(true)
    setRecoveryError(null)
    const response = await queueService.recover(
      jobId,
      { reason: recoveryReason.trim() },
      { token: session.token },
    )
    setRecovering(false)
    if (response.status === 'ok') {
      setRecoveryReason('')
      reloadResults()
    } else {
      setRecoveryError(response.reason)
    }
  }

  return (
    <div className="rd-desk">
      <header className="rd-hero">
        <div className="rd-hero__copy">
          {/* The shell already renders the route's h1, so the record name is
              not a second one. */}
          <p className="rd-hero__kicker mono">Submission</p>
          <p className="rd-hero__ref">{results ? results.student_ref : submissionId}</p>
          <p className="rd-hero__sub">
            <span className="mono">
              {submissionState.state === 'ok' ? submissionState.data.status : 'Not loaded'}
            </span>
            <span aria-hidden="true">·</span>
            <span>
              {pageCount ? `${pageCount} scanned page${pageCount === 1 ? '' : 's'}` : 'Pages not loaded'}
            </span>
            {results ? (
              <>
                <span aria-hidden="true">·</span>
                <span className="mono">{results.job_state}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="rd-hero__actions">
          <Link className="btn btn--small btn--outline" to="/queue">
            Back to queue
          </Link>
        </div>
      </header>

      {resultsState.state === 'error' && resultsState.code === 409 ? (
        <StatePanel
          tone="error"
          title="This paper's marking was refused"
          capability="POST /api/v1/corrections/{job_id}/recover"
        >
          <p>{resultsState.reason}</p>
          <p>
            A refused run is not a result. Its marks are kept as evidence and cannot be
            approved; a new, linked correction job has to mark the paper again.
          </p>
          <p>
            <Link className="btn btn--small btn--outline" to="/queue">
              Re-mark from the queue
            </Link>
          </p>
        </StatePanel>
      ) : resultsState.state === 'error' && resultsState.code === 404 ? (
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
            <>
              {refusedNewerId ? (
                <div className="app-message" data-tone="error" role="status">
                  <p>
                    A newer marking run for this submission was refused by the result guard,
                    so its marks are not shown and cannot be approved. These are the marks the
                    engine last stored for this submission.
                  </p>
                  {canApprove ? (
                    <>
                      <div className="app-inline-actions">
                        <input
                          className="app-input"
                          value={recoveryReason}
                          onChange={(event) => setRecoveryReason(event.target.value)}
                          placeholder="Why is this being re-marked? (required)"
                          aria-label="Reason for re-marking this paper"
                          maxLength={2000}
                        />
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          disabled={recovering}
                          onClick={() => void recoverPaper(refusedNewerId)}
                        >
                          {recovering ? 'Starting…' : 'Re-mark paper'}
                        </button>
                      </div>
                      <p className="app-hint">
                        Re-marking creates a new correction job. The refused run's marks,
                        evidence and refusal stay exactly as they are.
                      </p>
                    </>
                  ) : (
                    <p className="app-hint">
                      A teacher can re-mark this paper from the queue.
                    </p>
                  )}
                  {recoveryError ? (
                    <p className="app-form__error">{recoveryError}</p>
                  ) : null}
                </div>
              ) : null}
              <section
                className="rd-pane"
                style={{ '--i': 0 } as CSSProperties}
                aria-label="Result summary"
              >
                <div className="rd-pane__head">
                  <h2 className="rd-pane__title">Marks so far</h2>
                  <span className="rd-pane__note mono">{results.totals.state}</span>
                </div>

                <div className="rd-tally">
                  <div>
                    <p className="rd-tally__figures">
                      <span className="rd-tally__awarded">{results.totals.awarded}</span>
                      <span className="rd-tally__of">
                        / {results.totals.total}
                      </span>
                    </p>
                    <p className="rd-tally__caption">
                      {results.totals.complete
                        ? `Marks awarded on all ${results.totals.scoreable} scoreable question${
                            results.totals.scoreable === 1 ? '' : 's'
                          }.`
                        : `Marks awarded on the ${results.totals.decided} of ${
                            results.totals.scoreable
                          } scoreable questions decided so far. This is not the paper's full total.`}
                      {results.totals.undecided > 0
                        ? ` ${results.totals.undecided} question${
                            results.totals.undecided === 1 ? ' is' : 's are'
                          } still undecided and contribute no mark.`
                        : ''}
                      {results.totals.approved ? '' : ' Nothing is approved yet.'}
                    </p>
                  </div>
                  <div
                    className="rd-tally__track"
                    style={{ '--fill': tallyFill } as CSSProperties}
                    role="img"
                    aria-label={`${results.totals.awarded} of ${results.totals.total} marks on decided questions`}
                  >
                    <span className="rd-tally__fill" />
                  </div>
                </div>

                <dl className="rd-facts">
                  <div>
                    <dt>Questions marked</dt>
                    <dd className="mono">
                      {results.totals.decided} of {results.totals.scoreable}
                    </dd>
                  </div>
                  <div>
                    <dt>Undecided</dt>
                    <dd className="mono">{results.totals.undecided}</dd>
                  </div>
                  <div>
                    <dt>Needs review</dt>
                    <dd className="mono">{results.totals.review_required}</dd>
                  </div>
                  <div>
                    <dt>Double check</dt>
                    <dd className="mono">
                      {doubleChecks.length === 0
                        ? 'Not run'
                        : `${doubleChecks.length} checked · ${disagreements} disagree${
                            disagreements === 1 ? '' : 's'
                          }`}
                    </dd>
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
                        disabled={
                          approving ||
                          results.totals.approved ||
                          unresolved > 0 ||
                          results.totals.undecided > 0
                        }
                        onClick={() => void approve()}
                        title={
                          results.totals.undecided > 0
                            ? 'Every question must have a decided mark before approval'
                            : unresolved > 0
                              ? 'Resolve every question that needs review first'
                              : undefined
                        }
                      >
                        {approving
                          ? 'Approving…'
                          : results.totals.approved
                            ? 'Approved'
                            : 'Approve results'}
                      </button>
                    </>
                  ) : null}
                </div>
                {approvalError ? <p className="app-form__error">{approvalError}</p> : null}
              </section>

              <div className="rd-body">
                <section
                  className="rd-pane rd-viewer"
                  style={{ '--i': 1 } as CSSProperties}
                  aria-label="Script pages"
                >
                  <div className="rd-pane__head">
                    <h2 className="rd-pane__title">Script</h2>
                    <span className="rd-pane__note mono">
                      {pageCount ? `Page ${pageIndex} of ${pageCount}` : 'No pages'}
                    </span>
                  </div>

                  <div className="rd-stage">
                    {imageError ? (
                      <div className="rd-stage__placeholder">{imageError}</div>
                    ) : imageUrl ? (
                      <img
                        key={pageIndex}
                        className="rd-stage__image"
                        data-flip={flip}
                        src={imageUrl}
                        alt={`Scanned page ${pageIndex}`}
                      />
                    ) : pagesState.state === 'ok' && pageCount === 0 ? (
                      <div className="rd-stage__placeholder">
                        This submission has no stored document, so there is nothing to display.
                      </div>
                    ) : (
                      <div className="rd-stage__placeholder mono" role="status" aria-live="polite">
                        Loading page {pageIndex}…
                      </div>
                    )}
                  </div>

                  <div className="rd-pager">
                    <button
                      type="button"
                      className="btn btn--small btn--outline"
                      disabled={pageIndex <= 1}
                      onClick={() => turn(-1)}
                    >
                      Previous
                    </button>
                    <span className="rd-pager__count mono">
                      {pageIndex} / {pageCount || '—'}
                    </span>
                    <button
                      type="button"
                      className="btn btn--small btn--outline"
                      disabled={pageCount === 0 || pageIndex >= pageCount}
                      onClick={() => turn(1)}
                    >
                      Next
                    </button>
                  </div>
                </section>

                <section
                  className="rd-pane rd-evidence"
                  style={{ '--i': 2 } as CSSProperties}
                  aria-label="Question evidence"
                >
                  <div className="rd-pane__head">
                    <h2 className="rd-pane__title">Evidence</h2>
                    <span className="rd-pane__note mono">
                      {results.totals.decided} of {results.totals.scoreable} decided
                    </span>
                  </div>

                  {orderedQuestions.length ? (
                    <div className="rd-list">
                      {orderedQuestions.map((question) => (
                        <QuestionRow
                          key={question.id}
                          result={question}
                          jobId={results.job_id}
                          token={session.token}
                          recordVersion={results.record_version}
                          verifications={
                            verificationsByQuestion[question.question_id] ?? []
                          }
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
                </section>
              </div>
            </>
          ) : null}
        </DataState>
      )}
    </div>
  )
}

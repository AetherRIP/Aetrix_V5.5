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
  QuestionVerification,
  ReviewDecision,
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

type Tone = 'ok' | 'attention' | 'neutral'

/**
 * Every verification kind the engine records, labelled as itself.
 *
 * A kind this build does not recognise is shown by name, in a neutral tone,
 * and never falls through to another check's label.  Guessing would tell a
 * reviewer that an independent reading of the script was an integrity check.
 */
const VERIFICATION_NAMES: Record<string, string> = {
  INTEGRITY: 'Integrity',
  MATHEMATICAL: 'Mathematics',
  SCHEME_MATHEMATICAL: 'Scheme mathematics',
  TRANSCRIPTION: 'Independent reading',
  EVIDENCE: 'Evidence in script',
  DOUBLE_CHECK: 'Second examiner',
}

function verificationTone(verification: Verification): Tone {
  const { kind, status } = verification
  if (kind === 'INTEGRITY') {
    if (status === 'PASS') return 'ok'
    if (status === 'REVIEW_REQUIRED' || status === 'FAIL') return 'attention'
    return 'neutral'
  }
  if (kind === 'MATHEMATICAL' || kind === 'SCHEME_MATHEMATICAL') {
    if (status === 'EQUIVALENT') return 'ok'
    if (status === 'DIFFERENT') return 'attention'
    return 'neutral'
  }
  if (kind === 'TRANSCRIPTION' || kind === 'EVIDENCE') {
    if (status === 'PASS' || status === 'AGREES') return 'ok'
    if (status === 'FAIL' || status === 'DIFFERS') return 'attention'
    return 'neutral'
  }
  if (kind === 'DOUBLE_CHECK') {
    if (status === 'AGREES') return 'ok'
    if (status === 'DISAGREES') return 'attention'
    return 'neutral'
  }
  return 'neutral'
}

function verificationLabel(verification: Verification): string {
  const name = VERIFICATION_NAMES[verification.kind]
  return name
    ? `${name} · ${verification.status}`
    : `Unrecognised check (${verification.kind}) · ${verification.status}`
}

const QUESTION_VERIFICATION_NAMES: Record<string, string> = {
  FULLY_VERIFIED: 'Fully verified',
  PARTIALLY_VERIFIED: 'Partially verified',
  REVIEW_REQUIRED: 'Verification needs review',
  VERIFICATION_FAILED: 'Verification failed',
  VERIFICATION_NOT_REQUIRED: 'No independent check required',
}

function questionVerificationLabel(status: string | null | undefined): string {
  if (!status) return 'Verification not recorded'
  return QUESTION_VERIFICATION_NAMES[status] ?? `Verification: ${status}`
}

function questionVerificationTone(status: string | null | undefined): Tone {
  if (status === 'FULLY_VERIFIED') return 'ok'
  if (status === 'VERIFICATION_FAILED' || status === 'REVIEW_REQUIRED') return 'attention'
  return 'neutral'
}

/**
 * How much the paper's verification actually establishes.
 *
 * Completion and verification are two facts, so the paper states the second
 * one beside the first instead of letting a finished run imply a verified
 * result. The wording says what the state means, not merely its name.
 */
const VERIFICATION_STATUS_HELP: Record<string, string> = {
  FULLY_VERIFIED: 'every required check ran and passed',
  PARTIALLY_VERIFIED: 'some required checks did not run',
  REVIEW_REQUIRED: 'a person must decide before approval',
  VERIFICATION_FAILED: 'a check contradicted an award',
  VERIFICATION_NOT_REQUIRED: 'no independent check applied',
}

function verificationStatusHelp(status: string | null | undefined): string {
  if (!status) return 'the engine recorded no verification state'
  return VERIFICATION_STATUS_HELP[status] ?? 'an unrecognised verification state'
}

function verificationKindList(kinds: string[]): string {
  return kinds.map((kind) => VERIFICATION_NAMES[kind] ?? kind).join(', ')
}

/**
 * Which required checks did not pass, named rather than counted.
 *
 * `PARTIALLY_VERIFIED` alone cannot tell a reviewer what is absent, and an
 * absent check must never be mistaken for one that succeeded.
 */
function verificationGaps(verification: QuestionVerification): string[] {
  const lines: string[] = []
  if (verification.contradicted.length) {
    lines.push(`Contradicted: ${verificationKindList(verification.contradicted)}`)
  }
  if (verification.missing.length) {
    lines.push(`Missing required: ${verificationKindList(verification.missing)}`)
  }
  if (verification.unverifiable.length) {
    lines.push(`Could not be checked: ${verificationKindList(verification.unverifiable)}`)
  }
  return lines
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
  if (verification.kind === 'TRANSCRIPTION') {
    if (status === 'AGREES') {
      return 'The independent reading found the same writing. That does not by itself establish that the marking is correct.'
    }
    if (status === 'DIFFERS') {
      return 'The independent reading of the page differs from what the marking pass recorded. Both readings are stored; a person decides which the mark rests on.'
    }
    if (status === 'ABSENT') {
      return 'Neither reading found an answer for this question.'
    }
    return 'The independent reading could not be used, so it neither confirms nor contradicts the answer.'
  }
  if (verification.kind === 'EVIDENCE') {
    if (status === 'PASS') {
      return 'Every quotation this question awarded against was found in the independent reading of its page.'
    }
    if (status === 'FAIL') {
      return 'At least one quotation was not found in the independent reading of the page. The award is not changed; a person decides.'
    }
    return 'The quoted evidence could not be checked against an independent reading.'
  }
  if (verification.kind === 'SCHEME_MATHEMATICAL') {
    const student = textField(detail, 'student_expression')
    const expected = textField(detail, 'expected_expression')
    const pair =
      student && expected ? ` The script states ${student}; the scheme states ${expected}.` : ''
    if (status === 'EQUIVALENT') {
      return `SymPy found the student's answer equivalent to the answer the approved scheme prints.${pair}`
    }
    if (status === 'DIFFERENT') {
      return `SymPy found the student's answer different from the answer the approved scheme prints.${pair}`
    }
    return `The answer could not be compared with the approved scheme's answer.${pair}`
  }
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
  if (verification.kind === 'INTEGRITY') {
    return status === 'PASS'
      ? 'The award is internally consistent with what the marker reported.'
      : 'The award failed an internal consistency check.'
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
  return `This check recorded ${status}. This interface does not know how to interpret that kind of check, so read the stored detail before deciding.`
}

function QuestionRow({
  result,
  verifications,
  review,
  jobId,
  token,
  recordVersion,
  onChanged,
  canReview,
}: {
  result: QuestionResult
  verifications: Verification[]
  review: ReviewDecision | null
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
          {result.verification ? (
            <span
              className="chip app-chip"
              data-tone={questionVerificationTone(result.verification.status)}
            >
              {questionVerificationLabel(result.verification.status)}
            </span>
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

        {review && review.requested_reason ? (
          <p className="rd-row__review">
            <span className="rd-row__label mono">Review reason</span>
            {review.requested_reason}
          </p>
        ) : null}

        {result.evidence.length ? (
          <ul
            className="rd-evidence"
            aria-label={`Stored quotations for question ${result.question_id}`}
          >
            {result.evidence.map((item) => (
              <li key={item.id}>
                <span className="rd-evidence__kind mono">
                  {item.kind === 'QUOTE' ? 'quote' : item.kind}
                </span>
                <span>
                  {item.quote
                    ? `“${item.quote}”`
                    : 'No quotation text was stored for this evidence record.'}
                </span>
              </li>
            ))}
          </ul>
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

        {result.verification ? (
          verificationGaps(result.verification).length || result.verification.reasons.length ? (
            <div className="rd-verification-note">
              {verificationGaps(result.verification).map((line) => (
                <p key={line} className="rd-verification-note__line mono">
                  {line}
                </p>
              ))}
              {result.verification.reasons.map((reason) => (
                <p key={reason} className="rd-verification-note__reason">
                  {reason}
                </p>
              ))}
            </div>
          ) : null
        ) : (
          <p className="rd-verification-note rd-verification-note--absent">
            The engine recorded no verification state for this question. That is not a passed check.
          </p>
        )}

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
          {/*
           * The submission record names its student even when no result can be
           * read (every run refused, or none yet). Falling back to the UUID hid
           * the one identifier the record already had.
           */}
          <p className="rd-hero__ref">
            {results?.student_ref ??
              (submissionState.state === 'ok' ? submissionState.data.student_ref : submissionId)}
          </p>
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
                <span
                  className="chip app-chip"
                  data-tone="neutral"
                  data-job-state={results.job_state}
                  title="Correction state reported by the engine. Verification is a separate fact."
                >
                  {results.job_state}
                </span>
                {results.verification_status ? (
                  <>
                    <span aria-hidden="true">·</span>
                    <span
                      className="chip app-chip"
                      data-tone={questionVerificationTone(results.verification_status)}
                      data-verification-status={results.verification_status}
                      title={verificationStatusHelp(results.verification_status)}
                    >
                      {questionVerificationLabel(results.verification_status)}
                    </span>
                    <span className="app-hint">
                      {verificationStatusHelp(results.verification_status)}
                    </span>
                  </>
                ) : null}
              </>
            ) : null}
          </p>
        </div>
        <div className="rd-hero__actions">
          <Link
            className="btn btn--small btn--outline"
            to="/preview/$submissionId"
            params={{ submissionId }}
          >
            Correction preview
          </Link>
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
                          review={
                            results.reviews.find(
                              (review) => review.question_id === question.question_id,
                            ) ?? null
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

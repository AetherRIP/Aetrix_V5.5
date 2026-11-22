import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { StatePanel } from '../components/app/StatePanel'
import { PageCanvas } from '../components/preview/PageCanvas'
import { Icon } from '../components/ui/Icons'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import {
  PREVIEW_ENDPOINT_DEPLOYED,
  PREVIEW_ENDPOINT_NOT_DEPLOYED_REASON,
  previewService,
  submissionService,
} from '../lib/services'
import type {
  CorrectionPreview,
  PreviewDecision,
  PreviewQuestion,
  PreviewStudent,
  PreviewVerification,
} from '../lib/api/types'

export const Route = createFileRoute('/_app/preview/$submissionId')({
  component: CorrectionPreviewPage,
})

/* ── criterion language ────────────────────────────────────────────────────
 * One tone per printed code family, used by the scheme, the assessment and the
 * evidence alike so a reader can follow a mark across the spread by colour as
 * well as by label.
 */
type CriterionTone = 'method' | 'accuracy' | 'independent' | 'other'

function criterionTone(code: string): CriterionTone {
  const base = code.replace(/-\d+$/, '').trim().toUpperCase()
  if (base.startsWith('M')) return 'method'
  if (base.startsWith('A')) return 'accuracy'
  if (base.startsWith('B')) return 'independent'
  return 'other'
}

function shortQuestion(id: string): string {
  return `Q${id}`
}

function statusTone(question: PreviewQuestion): 'ok' | 'attention' | 'neutral' {
  if (question.processing_state === 'NEEDS_REVIEW') return 'attention'
  if (question.processing_state === 'UNMARKED') return 'neutral'
  return 'ok'
}

function verificationTone(verification: PreviewVerification): 'ok' | 'attention' | 'neutral' {
  if (verification.kind === 'INTEGRITY') {
    if (verification.status === 'PASS') return 'ok'
    if (verification.status === 'REVIEW_REQUIRED' || verification.status === 'FAIL') return 'attention'
    return 'neutral'
  }
  if (verification.kind === 'SCHEME_MATHEMATICAL' || verification.kind === 'MATHEMATICAL') {
    if (verification.status === 'EQUIVALENT') return 'ok'
    if (verification.status === 'DIFFERENT') return 'attention'
    return 'neutral'
  }
  if (verification.kind === 'EVIDENCE') {
    if (verification.status === 'PASS') return 'ok'
    if (verification.status === 'FAIL') return 'attention'
    return 'neutral'
  }
  if (verification.kind === 'TRANSCRIPTION') {
    if (verification.status === 'AGREES') return 'ok'
    if (verification.status === 'DIFFERS') return 'attention'
    return 'neutral'
  }
  if (verification.status === 'AGREES') return 'ok'
  if (verification.status === 'DISAGREES') return 'attention'
  return 'neutral'
}

function numberDetail(verification: PreviewVerification, key: string): number | null {
  const value = verification.detail[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function textDetail(verification: PreviewVerification, key: string): string | null {
  const value = verification.detail[key]
  return typeof value === 'string' && value.trim() ? value : null
}

/**
 * What a verification record actually says. Each message quotes the stored
 * detail and never upgrades a check into a stronger claim than it made.
 */
function verificationText(verification: PreviewVerification): string {
  if (verification.kind === 'INTEGRITY') {
    const component = numberDetail(verification, 'component_total')
    const award = numberDetail(verification, 'awarded_marks')
    const max = numberDetail(verification, 'max_marks')
    const outOf = max === null ? '' : ` of ${max}`
    if (verification.status === 'PASS') {
      return component === null
        ? 'The award is internally consistent with the components the reply marked.'
        : `The components the reply marked total ${component}${outOf}, which matches the stated award.`
    }
    if (verification.status === 'REVIEW_REQUIRED') {
      return component === null
        ? 'The integrity check could not confirm the award, so a person has to decide it.'
        : `The components the reply marked total ${component}, but the stated award is ${award}${outOf}. A person has to decide it.`
    }
    return `Integrity check recorded ${verification.status}.`
  }
  if (verification.kind === 'SCHEME_MATHEMATICAL' || verification.kind === 'MATHEMATICAL') {
    const student = textDetail(verification, 'student_expression')
    const expected = textDetail(verification, 'expected_expression')
    const pair =
      student && expected ? ` The script states ${student}; the scheme states ${expected}.` : ''
    if (verification.status === 'EQUIVALENT') {
      return `SymPy found the final answer equivalent to the expected expression.${pair}`
    }
    if (verification.status === 'DIFFERENT') {
      return `SymPy found the final answer different from the expected expression.${pair}`
    }
    return `SymPy could not compare the expressions, so this check proved nothing.${pair}`
  }
  if (verification.kind === 'TRANSCRIPTION') {
    if (verification.status === 'AGREES') {
      return 'The independent reading found the same writing; it does not by itself prove the marking is correct.'
    }
    if (verification.status === 'DIFFERS') {
      return 'The independent reading differs from the marking pass. Both readings are stored; a person decides.'
    }
    return `Independent reading recorded ${verification.status}.`
  }
  if (verification.kind === 'EVIDENCE') {
    if (verification.status === 'PASS') {
      return 'Every quotation the award cites was found in the independent reading of the page.'
    }
    if (verification.status === 'FAIL') {
      return 'At least one quotation was not found in the independent reading of the page. The award is not changed; a person decides.'
    }
    return `Evidence check recorded ${verification.status}.`
  }
  if (verification.kind === 'DOUBLE_CHECK') {
    const first = numberDetail(verification, 'first_awarded')
    const second = numberDetail(verification, 'second_awarded')
    if (verification.status === 'DISAGREES' && first !== null && second !== null) {
      return `The first examiner awarded ${first}; the second awarded ${second}. The first award stands until a person decides.`
    }
    if (verification.status === 'AGREES' && first !== null && second !== null) {
      return `Both examiners awarded ${first}.`
    }
    return `Second marking recorded ${verification.status}.`
  }
  return `${verification.kind} recorded ${verification.status}.`
}

function schemeFor(question: PreviewQuestion, decision: PreviewDecision) {
  if (decision.scheme_ordinal === null) return null
  return (
    question.scheme_criteria.find((criterion) => criterion.ordinal === decision.scheme_ordinal) ?? null
  )
}

function expectedAnswers(question: PreviewQuestion): string[] {
  const answers = new Set<string>()
  for (const criterion of question.scheme_criteria) {
    if (criterion.expected_answer) answers.add(criterion.expected_answer)
  }
  return [...answers]
}

function formatAlternative(alternative: Record<string, unknown>): string {
  return Object.entries(alternative)
    .filter(([, value]) => typeof value === 'string' || typeof value === 'number')
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${String(value)}`)
    .join(' · ')
}

function scoreLabel(student: PreviewStudent): string {
  return `${student.awarded_marks}/${student.total_marks}`
}

function CorrectionPreviewPage() {
  const { submissionId } = Route.useParams()
  const session = useEngineSession()
  const [state] = useResource<CorrectionPreview>(
    submissionId,
    session.token
      ? (signal) => previewService.get(submissionId, { token: session.token, signal })
      : null,
  )
  const preview = state.state === 'ok' ? state.data : null
  const [activeId, setActiveId] = useState<string | null>(null)
  const [showSchemePage, setShowSchemePage] = useState(false)
  const indexRef = useRef<HTMLOListElement>(null)

  const questions = preview?.questions ?? []
  const activeIndex = questions.findIndex((question) => question.question_id === activeId)
  const active = activeIndex >= 0 ? questions[activeIndex] : null

  useEffect(() => {
    if (!preview || preview.questions.length === 0) return
    if (activeId && preview.questions.some((question) => question.question_id === activeId)) return
    const firstReview = preview.questions.find((question) => question.review_required)
    setActiveId(firstReview?.question_id ?? preview.questions[0].question_id)
  }, [preview, activeId])

  useEffect(() => {
    setShowSchemePage(false)
    const list = indexRef.current
    if (!list) return
    const current = list.querySelector<HTMLElement>('[data-active]')
    current?.scrollIntoView({ block: 'nearest' })
  }, [activeId])

  const schemePage = useMemo(() => {
    if (!active) return null
    return active.scheme_criteria.find((criterion) => criterion.source_page !== null)?.source_page ?? null
  }, [active])

  function step(delta: number) {
    if (activeIndex < 0) return
    const next = questions[activeIndex + delta]
    if (next) setActiveId(next.question_id)
  }

  return (
    <div className="cp-desk">
      {!PREVIEW_ENDPOINT_DEPLOYED && (state.state === 'unavailable' || state.state === 'error') ? (
        <div className="app-stack">
          <StatePanel
            tone="wip"
            title="The correction preview endpoint is not deployed"
            capability="GET /api/v1/submissions/{id}/preview"
          >
            <p>{PREVIEW_ENDPOINT_NOT_DEPLOYED_REASON}</p>
            <p>
              <Link
                className="btn btn--outline btn--small"
                to="/submissions/$submissionId"
                params={{ submissionId }}
              >
                Back to the submission record
              </Link>
            </p>
          </StatePanel>
        </div>
      ) : (
      <DataState state={state} capability="GET /api/v1/submissions/{id}/preview">
        {preview ? (
          <>
            <header className="cp-overview">
              <div className="cp-overview__head">
                <div className="cp-overview__copy">
                  <p className="cp-kicker mono">
                    <Icon name="eye" size={13} /> Correction preview
                  </p>
                  <h1 className="cp-student">{preview.student_ref}</h1>
                  <p className="cp-paper">{preview.paper.exam_title}</p>
                  <p className="cp-paper__meta mono">
                    {preview.paper.paper_code ? <span>{preview.paper.paper_code}</span> : null}
                    <span aria-hidden="true">·</span>
                    <span>{preview.paper.assignment_name}</span>
                    <span aria-hidden="true">·</span>
                    <span>{preview.paper.questions_reviewed} questions reviewed</span>
                  </p>
                </div>
                <div className="cp-overview__score">
                  <p className="cp-score">
                    <span className="cp-score__earned">{preview.paper.paper_awarded}</span>
                    <span className="cp-score__of">/ {preview.paper.paper_total}</span>
                  </p>
                  <p className="cp-score__caption">
                    marks awarded across every stored question row.
                    {preview.paper.undecided > 0 ? (
                      <>
                        {' '}
                        Formally decided: {preview.paper.decided_awarded} of{' '}
                        {preview.paper.decided_total} marks; {preview.paper.undecided} question
                        {preview.paper.undecided === 1 ? ' awaits' : 's await'} a decision.
                      </>
                    ) : (
                      <> All {preview.paper.scoreable} scoreable questions have a decision.</>
                    )}
                  </p>
                </div>
                <div className="cp-overview__actions">
                  <Link
                    className="btn btn--small btn--outline"
                    to="/submissions/$submissionId"
                    params={{ submissionId }}
                  >
                    Submission record
                  </Link>
                  <Link className="btn btn--small btn--outline" to="/queue">
                    Queue
                  </Link>
                </div>
              </div>

              <dl className="cp-facts">
                <div>
                  <dt>Attention</dt>
                  <dd>
                    <span className="mono">{preview.paper.attention}</span> question
                    {preview.paper.attention === 1 ? '' : 's'} flagged
                  </dd>
                </div>
                <div>
                  <dt>Model</dt>
                  <dd className="mono">{preview.paper.primary_model ?? 'Not recorded'}</dd>
                </div>
                <div>
                  <dt>Correction status</dt>
                  <dd>
                    <span
                      className="chip app-chip"
                      data-tone={
                        preview.paper.result_source === 'AUTOMATED_REFUSED'
                          ? 'attention'
                          : preview.paper.job_state === 'COMPLETED'
                            ? 'ok'
                            : 'attention'
                      }
                    >
                      {preview.paper.result_source === 'AUTOMATED_REFUSED'
                        ? 'Evidence run · refused'
                        : preview.paper.job_state}
                    </span>
                  </dd>
                </div>
                <div>
                  <dt>Approval</dt>
                  <dd>
                    {preview.paper.approved
                      ? `Approved${preview.paper.approved_by ? ` by ${preview.paper.approved_by}` : ''}`
                      : 'Provisional — not approved'}
                  </dd>
                </div>
                <div>
                  <dt>Engine</dt>
                  <dd className="mono">
                    {[preview.paper.engine_name, preview.paper.engine_version]
                      .filter(Boolean)
                      .join(' · ') || 'Not recorded'}
                  </dd>
                </div>
                <div>
                  <dt>Marking mode</dt>
                  <dd className="mono">{preview.paper.marking_mode ?? 'Not recorded'}</dd>
                </div>
              </dl>

              <nav className="cp-students" aria-label="Students in this pilot">
                <p className="cp-students__label mono">Pilot students</p>
                <ul>
                  {preview.students.map((student) => (
                    <li key={student.submission_id}>
                      <Link
                        className="cp-studentlink"
                        to="/preview/$submissionId"
                        params={{ submissionId: student.submission_id }}
                        data-active={student.current ? 'true' : undefined}
                        data-evidence={
                          student.result_source === 'AUTOMATED_REFUSED' ? 'true' : undefined
                        }
                      >
                        <span className="cp-studentlink__ref">{student.student_ref}</span>
                        <span className="cp-studentlink__score mono">{scoreLabel(student)}</span>
                        <span className="cp-studentlink__review mono">
                          {student.review_required} review
                        </span>
                        {student.result_source === 'AUTOMATED_REFUSED' ? (
                          <span className="cp-studentlink__tag mono">evidence</span>
                        ) : null}
                      </Link>
                    </li>
                  ))}
                </ul>
              </nav>

              {preview.warnings.length ? (
                <section className="cp-notices" aria-label="Stored data notices">
                  <p className="cp-notices__label mono">Stored warnings</p>
                  <ul>
                    {preview.warnings.map((warning) => (
                      <li key={warning.code} data-code={warning.code}>
                        <span className="cp-notices__code mono">{warning.code.replace(/_/g, ' ')}</span>
                        <span>{warning.message}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              ) : null}
            </header>

            <div className="cp-body">
              <nav className="cp-index" aria-label="Question navigation">
                <div className="cp-index__head">
                  <p className="mono">Questions</p>
                  <span className="mono">
                    {questions.filter((question) => question.review_required).length} review
                  </span>
                </div>
                <ol className="cp-index__list" ref={indexRef}>
                  {questions.map((question) => (
                    <li key={question.question_id}>
                      <button
                        type="button"
                        className="cp-index__item"
                        data-active={question.question_id === activeId ? 'true' : undefined}
                        data-review={question.review_required ? 'true' : undefined}
                        onClick={() => setActiveId(question.question_id)}
                        aria-current={question.question_id === activeId ? 'true' : undefined}
                      >
                        <span className="cp-index__q mono">{shortQuestion(question.question_id)}</span>
                        <span className="cp-index__marks mono">
                          {question.awarded_marks}/{question.max_marks}
                        </span>
                        <span
                          className="cp-index__dot"
                          data-tone={question.review_required ? 'attention' : 'ok'}
                          aria-hidden="true"
                        />
                      </button>
                    </li>
                  ))}
                </ol>
              </nav>

              {active ? (
                <div className="cp-work">
                  <section className="cp-pane cp-script" aria-label="Student's work">
                    <div className="cp-pane__head">
                      <h2 className="cp-pane__title">Student&apos;s work</h2>
                      <span className="cp-pane__note mono">
                        {preview.student_document
                          ? `Page ${active.location?.page_index ?? 1} of ${preview.student_document.page_count}`
                          : 'No document'}
                      </span>
                    </div>

                    <div className="cp-map">
                      {active.location ? (
                        <>
                          <span className="chip app-chip" data-tone="neutral">
                            {active.location.method === 'MANUAL' ? 'Manual link' : 'Model link'}
                          </span>
                          <span className="mono">
                            {shortQuestion(active.question_id)} → page {active.location.page_index} ·{' '}
                            {Math.round(active.location.confidence * 100)}% confidence
                          </span>
                        </>
                      ) : (
                        <span className="mono">{active.mapping_note}</span>
                      )}
                    </div>

                    {preview.student_document ? (
                      <PageCanvas
                        refreshKey={`${preview.student_document.id}:${active.location?.page_index ?? 1}`}
                        alt={`${preview.student_ref} script, stored page ${active.location?.page_index ?? 1}`}
                        load={(signal) =>
                          submissionService.pageImage(
                            submissionId,
                            active.location?.page_index ?? 1,
                            { token: session.token, signal },
                          )
                        }
                      />
                    ) : (
                      <p className="cp-empty">
                        This submission has no stored student document, so there is no page to show.
                      </p>
                    )}

                    <div className="cp-script__foot">
                      <p className="cp-source mono">
                        {preview.student_document
                          ? `${preview.student_document.original_filename} · page ${active.location?.page_index ?? 1} · ${preview.student_document.ordering_status}`
                          : 'No document recorded'}
                      </p>
                      <p className="cp-provenance">
                        The stored question-page mapping names a page, not a region, and the reply
                        recorded no page coordinates. No area of this page is highlighted; the quotes
                        beside each criterion are the evidence the reply actually recorded.
                      </p>
                      {active.mapping_note ? <p className="cp-note">{active.mapping_note}</p> : null}
                    </div>
                  </section>

                  <section className="cp-pane cp-decision" aria-label={`Question ${active.question_id}`}>
                    <div className="cp-question__head">
                      <div>
                        <p className="cp-question__label mono">{active.label}</p>
                        <h2 className="cp-question__id">{shortQuestion(active.question_id)}</h2>
                      </div>
                      <div className="cp-question__award">
                        <p className="cp-question__score mono">
                          {active.awarded_marks}
                          <span> / {active.max_marks}</span>
                        </p>
                        <span className="chip app-chip" data-tone={statusTone(active)}>
                          {active.processing_state === 'NEEDS_REVIEW'
                            ? 'Needs review'
                            : active.processing_state === 'UNMARKED'
                              ? 'Not marked'
                              : 'Marked'}
                        </span>
                      </div>
                      <div className="cp-question__nav">
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          onClick={() => step(-1)}
                          disabled={activeIndex <= 0}
                        >
                          ← Previous
                        </button>
                        <button
                          type="button"
                          className="btn btn--small btn--outline"
                          onClick={() => step(1)}
                          disabled={activeIndex >= questions.length - 1}
                        >
                          Next →
                        </button>
                      </div>
                    </div>

                    <div className="cp-block">
                      <div className="cp-block__head">
                        <h3 className="cp-block__title">What the model read</h3>
                        {active.confidence !== null ? (
                          <span className="mono cp-confidence">
                            {active.confidence.toFixed(2)} confidence
                          </span>
                        ) : null}
                      </div>
                      {active.student_answer ? (
                        <p className="cp-transcript mono">{active.student_answer}</p>
                      ) : (
                        <p className="cp-empty">
                          The archived reply recorded no transcription for this question. The
                          scanned page is the only record of the student&apos;s work.
                        </p>
                      )}
                      {active.working_summary ? (
                        <p className="cp-working">
                          <span className="mono">Working summary</span> {active.working_summary}
                        </p>
                      ) : null}
                      {active.answer_check ? (
                        <p className="cp-working">
                          <span className="mono">Answer check</span> {active.answer_check}
                        </p>
                      ) : null}
                      {active.notes ? (
                        <p className="cp-working">
                          <span className="mono">Model note</span> {active.notes}
                        </p>
                      ) : null}
                      {active.question_text ? (
                        <p className="cp-question__text">
                          <span className="mono">Printed question</span> {active.question_text}
                        </p>
                      ) : null}
                    </div>

                    <div className="cp-block">
                      <div className="cp-block__head">
                        <h3 className="cp-block__title">Against the scheme</h3>
                        <span className="mono cp-block__meta">
                          {active.criteria.length} assessment
                          {active.criteria.length === 1 ? '' : 's'} · {active.scheme_marks} scheme marks
                        </span>
                      </div>

                      <div className="cp-tablewrap">
                        <table className="cp-table">
                          <thead>
                            <tr>
                              <th scope="col">Criterion</th>
                              <th scope="col">Printed scheme</th>
                              <th scope="col">AI assessment</th>
                              <th scope="col">Marks</th>
                            </tr>
                          </thead>
                          <tbody>
                            {active.criteria.map((decision, index) => {
                              const criterion = schemeFor(active, decision)
                              return (
                                <tr
                                  key={`${decision.code}-${decision.scheme_ordinal ?? 'extra'}-${index}`}
                                  data-tone={criterionTone(decision.code)}
                                  data-awarded={
                                    decision.awarded === null
                                      ? 'none'
                                      : decision.awarded
                                        ? 'true'
                                        : 'false'
                                  }
                                >
                                  <td className="cp-table__code">
                                    <span className="cp-code" data-tone={criterionTone(decision.code)}>
                                      {decision.code}
                                    </span>
                                    <span className="cp-code__marks mono">
                                      {decision.scheme_marks ?? '—'} mark
                                      {decision.scheme_marks === 1 ? '' : 's'}
                                    </span>
                                    {decision.scheme_ordinal !== null ? (
                                      <span className="cp-code__ordinal mono">
                                        point{' '}
                                        {active.scheme_criteria.filter(
                                          (entry) => entry.code === criterion?.code,
                                        ).length > 1
                                          ? active.scheme_criteria
                                              .filter((entry) => entry.code === criterion?.code)
                                              .findIndex(
                                                (entry) => entry.ordinal === decision.scheme_ordinal,
                                              ) + 1
                                          : decision.scheme_ordinal + 1}
                                      </span>
                                    ) : null}
                                    {decision.ambiguous ? (
                                      <span className="cp-flag">ambiguous code</span>
                                    ) : null}
                                  </td>
                                  <td>
                                    {criterion ? (
                                      <>
                                        <p className="cp-printed__quote">
                                          {criterion.source_quote ?? criterion.description}
                                        </p>
                                        <p className="cp-printed__structured">
                                          <span className="mono">Structured</span>{' '}
                                          {criterion.description}
                                        </p>
                                        {criterion.source_page !== null ? (
                                          <p className="cp-printed__page mono">
                                            scheme page {criterion.source_page}
                                          </p>
                                        ) : null}
                                      </>
                                    ) : (
                                      <p className="cp-empty">
                                        The stored scheme has no matching point for this code.
                                      </p>
                                    )}
                                  </td>
                                  <td>
                                    <p className="cp-assessment">
                                      {decision.awarded === null
                                        ? 'No separate assessment recorded'
                                        : decision.awarded
                                          ? 'Awarded'
                                          : 'Not awarded'}
                                    </p>
                                    {decision.component_description ? (
                                      <p className="cp-assessment__desc">
                                        {decision.component_description}
                                      </p>
                                    ) : null}
                                    {decision.evidence.length ? (
                                      <ul className="cp-evidence">
                                        {decision.evidence.map((quote, quoteIndex) => (
                                          <li key={`${quote}-${quoteIndex}`}>
                                            <mark>{quote}</mark>
                                          </li>
                                        ))}
                                      </ul>
                                    ) : null}
                                    {decision.reason ? (
                                      <p className="cp-assessment__reason">{decision.reason}</p>
                                    ) : null}
                                    {decision.note ? (
                                      <p className="cp-note">{decision.note}</p>
                                    ) : null}
                                  </td>
                                  <td className="cp-table__marks mono">
                                    {decision.awarded_marks === null ? '—' : decision.awarded_marks}
                                    {decision.scheme_marks !== null ? (
                                      <span> / {decision.scheme_marks}</span>
                                    ) : null}
                                  </td>
                                </tr>
                              )
                            })}
                          </tbody>
                        </table>
                      </div>

                      <p className="cp-total">
                        <span className="mono">Components</span>{' '}
                        {active.component_total === null
                          ? 'The reply recorded no component assessments for this question.'
                          : `Awarded ${active.component_total} of the ${active.max_marks} available.`}{' '}
                        <span className="mono">Question award</span> {active.awarded_marks} /{' '}
                        {active.max_marks}.
                        {active.component_consistent === false ? (
                          <strong className="cp-total__mismatch">
                            {' '}
                            These figures disagree, and the stored review reasons say so.
                          </strong>
                        ) : null}
                      </p>
                    </div>

                    <div className="cp-block cp-scheme">
                      <details open>
                        <summary className="cp-block__summary">
                          <span className="cp-block__title">Mark scheme</span>
                          <span className="mono cp-block__meta">
                            {active.scheme_marks} marks across {active.scheme_criteria.length} points
                            {schemePage !== null ? ` · source page ${schemePage}` : ''}
                          </span>
                        </summary>

                        <div className="cp-scheme__body">
                          {active.special_instructions.length ? (
                            <div className="cp-scheme__block">
                              <p className="cp-scheme__label mono">Special instructions</p>
                              <ul className="cp-list">
                                {active.special_instructions.map((instruction) => (
                                  <li key={instruction}>{instruction}</li>
                                ))}
                              </ul>
                            </div>
                          ) : null}

                          {expectedAnswers(active).length ? (
                            <div className="cp-scheme__block">
                              <p className="cp-scheme__label mono">Expected answer</p>
                              <ul className="cp-answers">
                                {expectedAnswers(active).map((answer) => (
                                  <li key={answer} className="mono">
                                    {answer}
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}

                          <ul className="cp-scheme__criteria">
                            {active.scheme_criteria.map((criterion) => (
                              <li
                                key={`${criterion.code}-${criterion.ordinal}`}
                                data-tone={criterionTone(criterion.code)}
                                className="cp-scheme__criterion"
                              >
                                <div className="cp-scheme__criterionhead">
                                  <span className="cp-code" data-tone={criterionTone(criterion.code)}>
                                    {criterion.code}
                                  </span>
                                  <span className="mono">{criterion.marks} mark</span>
                                  {criterion.source_page !== null ? (
                                    <span className="mono cp-scheme__page">
                                      page {criterion.source_page}
                                    </span>
                                  ) : null}
                                </div>
                                <div className="cp-scheme__printed">
                                  <p className="cp-scheme__label mono">Printed</p>
                                  <p>{criterion.source_quote ?? 'No printed quote recorded.'}</p>
                                </div>
                                <div className="cp-scheme__structured">
                                  <p className="cp-scheme__label mono">Structured criterion</p>
                                  <p>{criterion.description}</p>
                                  {criterion.expected_answer ? (
                                    <p>
                                      <span className="mono">Answer</span> {criterion.expected_answer}
                                    </p>
                                  ) : null}
                                  {criterion.award_conditions ? (
                                    <p>
                                      <span className="mono">Award when</span>{' '}
                                      {criterion.award_conditions}
                                    </p>
                                  ) : null}
                                  {criterion.withhold_conditions ? (
                                    <p>
                                      <span className="mono">Withhold when</span>{' '}
                                      {criterion.withhold_conditions}
                                    </p>
                                  ) : null}
                                  {criterion.required_evidence ? (
                                    <p>
                                      <span className="mono">Required evidence</span>{' '}
                                      {criterion.required_evidence}
                                    </p>
                                  ) : null}
                                  {criterion.dependencies.length ? (
                                    <p>
                                      <span className="mono">Depends on</span>{' '}
                                      {criterion.dependencies.join(', ')}
                                    </p>
                                  ) : null}
                                  {criterion.alternatives.length ? (
                                    <ul className="cp-alternatives">
                                      {criterion.alternatives.map((alternative, index) => (
                                        <li key={index}>{formatAlternative(alternative)}</li>
                                      ))}
                                    </ul>
                                  ) : null}
                                </div>
                              </li>
                            ))}
                          </ul>

                          <div className="cp-scheme__source">
                            <p className="cp-scheme__label mono">Scheme source</p>
                            <p>{preview.scheme_document.note}</p>
                            {preview.scheme_document.document_id && schemePage !== null ? (
                              <>
                                <button
                                  type="button"
                                  className="btn btn--small btn--outline"
                                  onClick={() => setShowSchemePage((value) => !value)}
                                  aria-expanded={showSchemePage}
                                >
                                  {showSchemePage ? 'Hide printed page' : `Show printed page ${schemePage}`}
                                </button>
                                {showSchemePage ? (
                                  <PageCanvas
                                    refreshKey={`${preview.scheme_document.document_id}:${schemePage}`}
                                    alt={`Mark scheme page ${schemePage}`}
                                    load={(signal) =>
                                      previewService.documentPageImage(
                                        preview.scheme_document.document_id as string,
                                        schemePage,
                                        { token: session.token, signal },
                                      )
                                    }
                                  />
                                ) : null}
                              </>
                            ) : (
                              <p className="cp-empty">
                                No stored scheme page can be shown; the structured criteria above are
                                the record.
                              </p>
                            )}
                          </div>
                        </div>
                      </details>
                    </div>

                    <div className="cp-block cp-review" data-review={active.review_required ? 'true' : undefined}>
                      <div className="cp-block__head">
                        <h3 className="cp-block__title">Review and verification</h3>
                        <span className="chip app-chip" data-tone={statusTone(active)}>
                          {active.review_required ? 'Requires a person' : 'No review flag'}
                        </span>
                      </div>

                      {active.review_reasons.length ? (
                        <ul className="cp-reasons">
                          {active.review_reasons.map((reason, index) => (
                            <li key={`${reason}-${index}`}>{reason}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="cp-empty">
                          The stored row records no review reason for this question.
                        </p>
                      )}

                      {active.verifications.length ? (
                        <ul className="cp-checks">
                          {active.verifications.map((verification) => (
                            <li key={`${verification.kind}-${verification.status}`}>
                              <span className="chip app-chip" data-tone={verificationTone(verification)}>
                                {verification.kind.replace(/_/g, ' ')} · {verification.status}
                              </span>
                              <span>{verificationText(verification)}</span>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="cp-empty">No verification record was stored for this question.</p>
                      )}

                      <details className="cp-archive">
                        <summary className="cp-block__summary">
                          <span className="cp-block__title">Archived reply</span>
                          <span className="mono cp-block__meta">
                            {active.archive ? active.archive.model ?? 'model not recorded' : 'no archive'}
                          </span>
                        </summary>
                        {active.archive ? (
                          <dl className="cp-archive__facts">
                            <div>
                              <dt>Reply</dt>
                              <dd className="mono">{active.archive.provider_response_id}</dd>
                            </div>
                            <div>
                              <dt>SHA-256</dt>
                              <dd className="mono">{active.archive.content_sha256}</dd>
                            </div>
                            <div>
                              <dt>Source</dt>
                              <dd className="mono">
                                {active.response_source ?? active.archive.response_source}
                                {active.response_sequence !== null
                                  ? ` · position ${active.response_sequence}`
                                  : ''}
                              </dd>
                            </div>
                            <div>
                              <dt>Finish reason</dt>
                              <dd className="mono">{active.archive.finish_reason ?? 'Not recorded'}</dd>
                            </div>
                            <div>
                              <dt>Stored</dt>
                              <dd className="mono">
                                {new Date(active.archive.created_at).toLocaleString()}
                              </dd>
                            </div>
                            <div>
                              <dt>Prompt</dt>
                              <dd className="mono">{active.prompt_version ?? 'Not recorded'}</dd>
                            </div>
                          </dl>
                        ) : (
                          <p className="cp-empty">
                            This question has no archived provider reply. Its award and criteria come
                            from the stored question result.
                          </p>
                        )}
                      </details>
                    </div>
                  </section>
                </div>
              ) : (
                <p className="cp-empty">This correction has no question rows to display.</p>
              )}
            </div>
          </>
        ) : null}
      </DataState>
      )}
    </div>
  )
}

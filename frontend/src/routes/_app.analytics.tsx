import { useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Assignment, CohortQuestion, CohortRead } from '../lib/api/types'
import { assignmentService, workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/analytics')({
  component: Analytics,
})

type SortKey = 'question' | 'average' | 'full' | 'zero' | 'sample'

function percent(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(1)}%`
}

function classLabel(assignment: Assignment): string {
  return assignment.class_name ?? 'Unassigned / legacy'
}

function Analytics() {
  const session = useEngineSession()
  const [assignments] = useResource<Assignment[]>(
    `cohort-assignments:${session.tenantId ?? 'none'}`,
    session.tenantId
      ? (signal) =>
          assignmentService.list(session.tenantId!, { token: session.token, signal })
      : null,
  )

  const [chosen, setChosen] = useState('')
  const [sort, setSort] = useState<SortKey>('question')
  const [openQuestion, setOpenQuestion] = useState<string | null>(null)

  const list = assignments.state === 'ok' ? assignments.data : []
  const selected = chosen || list[0]?.id || ''

  const [cohort, reload] = useResource<CohortRead>(
    `cohort:${session.tenantId ?? 'none'}:${selected}`,
    session.tenantId && selected
      ? (signal) =>
          workspaceService.cohort(session.tenantId!, selected, {
            token: session.token,
            signal,
          })
      : null,
  )

  const data = cohort.state === 'ok' ? cohort.data : null

  const grouped = new Map<string, Assignment[]>()
  for (const assignment of list) {
    const key = classLabel(assignment)
    grouped.set(key, [...(grouped.get(key) ?? []), assignment])
  }

  return (
    <div className="app-stack">
      <Panel title="Cohort intelligence" note="Question-level, from stored results">
        <p className="app-hint">
          Every figure below is aggregated from persisted question results. Missing or
          undecided questions are excluded from denominators, never counted as zero, and
          approved and provisional results are shown separately.
        </p>
        {assignments.state === 'error' ? (
          <p className="app-hint" role="alert">
            The assignment list did not load: {assignments.reason}
          </p>
        ) : null}
        <div className="app-inline-actions">
          <label htmlFor="cohort-assignment" className="mono app-hint">
            Class / assignment
          </label>
          <select
            id="cohort-assignment"
            className="input"
            value={selected}
            onChange={(event) => {
              setChosen(event.target.value)
              setOpenQuestion(null)
            }}
            disabled={list.length === 0}
          >
            {list.length === 0 ? <option value="">No assignments yet</option> : null}
            {[...grouped.entries()].map(([label, rows]) => (
              <optgroup key={label} label={label}>
                {rows.map((assignment) => (
                  <option key={assignment.id} value={assignment.id}>
                    {assignment.name}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          <button
            type="button"
            className="btn btn--small btn--outline"
            onClick={reload}
            disabled={!selected}
          >
            Refresh
          </button>
        </div>
        {list.length === 0 && assignments.state === 'ok' ? (
          <p className="app-hint">
            No assignment exists in this workspace yet, so there is no cohort to analyse.
          </p>
        ) : null}
      </Panel>

      <DataState state={cohort} capability="GET /api/v1/workspaces/{id}/cohort">
        {data ? <CohortBody data={data} sort={sort} setSort={setSort} openQuestion={openQuestion} setOpenQuestion={setOpenQuestion} /> : null}
      </DataState>
    </div>
  )
}

function CohortBody({
  data,
  sort,
  setSort,
  openQuestion,
  setOpenQuestion,
}: {
  data: CohortRead
  sort: SortKey
  setSort: (value: SortKey) => void
  openQuestion: string | null
  setOpenQuestion: (value: string | null) => void
}) {
  const questions = [...data.questions]
  questions.sort((left, right) => {
    if (sort === 'average') {
      return (left.average_percent ?? 101) - (right.average_percent ?? 101)
    }
    if (sort === 'full') return right.full_marks - left.full_marks
    if (sort === 'zero') return right.zero_marks - left.zero_marks
    if (sort === 'sample') return right.sample_size - left.sample_size
    return left.question_id.localeCompare(right.question_id, undefined, { numeric: true })
  })
  const selected = questions.find((question) => question.question_id === openQuestion)
  const lowest = questions
    .filter((question) => question.state === 'OK')
    .sort((left, right) => (left.average_percent ?? 0) - (right.average_percent ?? 0))[0]
  const flaggedStudents = data.students.filter((student) => student.support_flagged)
  const provisionalOnly = data.overview.approved_jobs === 0 && data.overview.provisional_jobs > 0

  return (
    <>
      <Panel
        title="Overview"
        note={`${data.assignment.class_name ?? 'Workspace'} · ${data.assignment.scope.toLowerCase()} scope`}
      >
        <dl className="hub-stats">
          <div className="hub-stat">
            <dt className="hub-stat__label">Mean</dt>
            <dd className="hub-stat__value mono">{percent(data.overview.mean_percent)}</dd>
            <dd className="hub-stat__note">
              {data.overview.approved_jobs > 0
                ? `${data.overview.approved_jobs} approved, ${data.overview.provisional_jobs} provisional`
                : 'provisional marks only — not approved'}
            </dd>
          </div>
          <div className="hub-stat">
            <dt className="hub-stat__label">Students included</dt>
            <dd className="hub-stat__value mono">{data.overview.included_students}</dd>
            <dd className="hub-stat__note">
              of {data.overview.eligible_submissions} eligible submission(s)
            </dd>
          </div>
          <div className="hub-stat">
            <dt className="hub-stat__label">Corrections</dt>
            <dd className="hub-stat__value mono">
              {data.overview.completed_corrections}/{data.overview.eligible_submissions}
            </dd>
            <dd className="hub-stat__note">
              {data.overview.pending_corrections} still pending
            </dd>
          </div>
          <div className="hub-stat">
            <dt className="hub-stat__label">Awaiting review</dt>
            <dd className="hub-stat__value mono">{data.overview.pending_reviews}</dd>
            <dd className="hub-stat__note">jobs in REVIEW_REQUIRED</dd>
          </div>
          <div className="hub-stat">
            <dt className="hub-stat__label">Questions to revisit</dt>
            <dd className="hub-stat__value mono">
              {data.overview.questions_requiring_attention}
            </dd>
            <dd className="hub-stat__note">at least 3 results and under 50%</dd>
          </div>
        </dl>
        {provisionalOnly ? (
          <p className="app-hint">
            No result on this assignment has been approved yet, so the figures are
            provisional. They are computed from decided marks, not from missing ones.
          </p>
        ) : null}
        {data.completeness.excluded_submissions > 0 ? (
          <p className="app-hint">
            {data.completeness.excluded_submissions} FAILED submission(s) were excluded
            from the denominator. {data.completeness.excluded_rows} EXCLUDED question
            row(s) were also left out.
          </p>
        ) : null}
        {lowest && lowest.average_percent !== null ? (
          <p className="app-hint">
            Lowest question average: <strong>Q{lowest.question_id}</strong> at{' '}
            {lowest.average_percent.toFixed(1)}% across {lowest.sample_size} decided
            result(s).
          </p>
        ) : null}
      </Panel>

      <Panel title="Question analysis" note={`${questions.length} question(s)`}>
        <div className="app-inline-actions">
          <label htmlFor="cohort-sort" className="mono app-hint">
            Sort by
          </label>
          <select
            id="cohort-sort"
            className="input"
            value={sort}
            onChange={(event) => setSort(event.target.value as SortKey)}
          >
            <option value="question">Question</option>
            <option value="average">Lowest average</option>
            <option value="full">Most full marks</option>
            <option value="zero">Most zero marks</option>
            <option value="sample">Largest sample</option>
          </select>
        </div>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">
              Question-level cohort performance for {data.assignment.name}
            </caption>
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col">Average</th>
                <th scope="col">Full marks</th>
                <th scope="col">Zero marks</th>
                <th scope="col">Partial</th>
                <th scope="col">Sample</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {questions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="data-table__empty">
                    No question result has been stored for this assignment yet.
                  </td>
                </tr>
              ) : (
                questions.map((question) => (
                  <tr key={question.question_id}>
                    <th scope="row">
                      <button
                        type="button"
                        className="btn btn--small btn--outline"
                        onClick={() => setOpenQuestion(question.question_id)}
                      >
                        Q{question.question_id}
                      </button>
                      <span className="mono app-hint">
                        {' '}
                        /{question.max_marks ?? `${question.max_marks_min}-${question.max_marks_max}`}
                      </span>
                    </th>
                    <td className="mono">{percent(question.average_percent)}</td>
                    <td className="mono">
                      {question.full_marks}/{question.sample_size}
                    </td>
                    <td className="mono">
                      {question.zero_marks}/{question.sample_size}
                    </td>
                    <td className="mono">{question.partial_marks}</td>
                    <td className="mono">{question.sample_size}</td>
                    <td>
                      <span
                        className="chip app-chip"
                        data-tone={
                          question.attention
                            ? 'attention'
                            : question.state === 'OK'
                              ? 'ok'
                              : 'neutral'
                        }
                      >
                        {question.state === 'OK'
                          ? question.attention
                            ? 'Needs attention'
                            : 'Reportable'
                          : question.state === 'INSUFFICIENT_SAMPLE'
                            ? 'Small sample'
                            : 'No results'}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <p className="app-hint">
          Averages are per-question percentages, so questions with different maximum
          marks are comparable. Sample counts only decided results; approved and
          provisional counts are shown in the question detail.
        </p>
        {selected ? <QuestionDetail question={selected} /> : null}
      </Panel>

      <Panel title="Topic analysis" note={data.topics.state}>
        {data.topics.state === 'available' ? (
          <ul>
            {data.topics.items.map((item) => (
              <li key={item.name}>
                {item.name}: {percent(item.average_percent)} ({item.sample_size})
              </li>
            ))}
          </ul>
        ) : (
          <p className="app-hint">
            {data.topics.reason ??
              'No topic classification is stored, so no topic aggregate is shown.'}
          </p>
        )}
      </Panel>

      <Panel
        title="Student support"
        note={`${flaggedStudents.length} flagged of ${data.students.length}`}
      >
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">
              Evidence-based support indicators for this assignment
            </caption>
            <thead>
              <tr>
                <th scope="col">Student</th>
                <th scope="col">Overall</th>
                <th scope="col">Decided</th>
                <th scope="col">Low questions</th>
                <th scope="col">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {data.students.length === 0 ? (
                <tr>
                  <td colSpan={5} className="data-table__empty">
                    No student has a decided result on this assignment.
                  </td>
                </tr>
              ) : (
                data.students.slice(0, 50).map((student) => (
                  <tr key={student.student_ref}>
                    <th scope="row">{student.student_ref}</th>
                    <td className="mono">{percent(student.percentage)}</td>
                    <td className="mono">
                      {student.decided}/{student.possible} marks
                    </td>
                    <td className="mono">
                      {student.low_question_ids.length > 0
                        ? student.low_question_ids.map((id) => `Q${id}`).join(', ')
                        : '—'}
                    </td>
                    <td>
                      <span
                        className="chip app-chip"
                        data-tone={student.support_flagged ? 'attention' : 'ok'}
                      >
                        {student.support_flagged ? 'Support' : 'No flag'}
                      </span>{' '}
                      <span className="app-hint">{student.evidence}</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        {data.students.length > 50 ? (
          <p className="app-hint">
            Showing the first 50 students by support priority. The engine returns the
            whole class; this screen limits the table for readability.
          </p>
        ) : null}
        <p className="app-hint">{data.rules.support}</p>
      </Panel>

      <Panel title="Trends" note={`${data.trends.points.length} assignment(s)`}>
        {data.trends.state === 'OK' ? (
          <>
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Assignment means for this class, oldest first
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Assignment</th>
                    <th scope="col">Mean</th>
                    <th scope="col">Students</th>
                    <th scope="col">Approved</th>
                  </tr>
                </thead>
                <tbody>
                  {data.trends.points.map((point) => (
                    <tr key={point.assignment_id}>
                      <th scope="row">{point.name}</th>
                      <td className="mono">{percent(point.mean_percent)}</td>
                      <td className="mono">{point.included_students}</td>
                      <td className="mono">{point.approved_jobs}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {data.trends.question_changes.length > 0 ? (
              <>
                <h3 className="app-hint">Direct question comparisons</h3>
                <ul>
                  {data.trends.question_changes.map((change) => (
                    <li key={change.question_id}>
                      Q{change.question_id}: {percent(change.previous_percent)} →{' '}
                      {percent(change.current_percent)} (
                      {change.delta_percent > 0 ? '+' : ''}
                      {change.delta_percent.toFixed(1)} points)
                    </li>
                  ))}
                </ul>
                <p className="app-hint">
                  Only questions whose identifier and maximum marks both match are
                  compared directly. Assignment means above are broader trends.
                </p>
              </>
            ) : (
              <p className="app-hint">
                No question is directly comparable with the previous assignment: either
                the question ids or their maximum marks differ, or a sample is too small.
              </p>
            )}
          </>
        ) : (
          <p className="app-hint">{data.trends.reason}</p>
        )}
      </Panel>
    </>
  )
}

function QuestionDetail({ question }: { question: CohortQuestion }) {
  return (
    <div className="app-card" aria-live="polite">
      <div className="app-card__head">
        <h3 className="app-card__title">Q{question.question_id} detail</h3>
        <span className="app-card__note mono">
          /{question.max_marks ?? `${question.max_marks_min}-${question.max_marks_max}`}
        </span>
      </div>
      <dl className="hub-stats">
        <div className="hub-stat">
          <dt className="hub-stat__label">Average</dt>
          <dd className="hub-stat__value mono">{percent(question.average_percent)}</dd>
          <dd className="hub-stat__note">median {percent(question.median_percent)}</dd>
        </div>
        <div className="hub-stat">
          <dt className="hub-stat__label">Decided sample</dt>
          <dd className="hub-stat__value mono">{question.sample_size}</dd>
          <dd className="hub-stat__note">
            {question.approved_sample} approved, {question.provisional_sample} provisional
          </dd>
        </div>
        <div className="hub-stat">
          <dt className="hub-stat__label">Struggling</dt>
          <dd className="hub-stat__value mono">
            {percent(question.struggling_percent)}
          </dd>
          <dd className="hub-stat__note">
            {question.struggling_count} under 50%
          </dd>
        </div>
        <div className="hub-stat">
          <dt className="hub-stat__label">Not decided</dt>
          <dd className="hub-stat__value mono">{question.pending_count}</dd>
          <dd className="hub-stat__note">excluded from the denominator</dd>
        </div>
      </dl>
      <p className="app-hint">
        Mark distribution:{' '}
        {question.distribution.length === 0
          ? 'no decided marks'
          : question.distribution
              .map((entry) => `${entry.marks} mark(s): ${entry.count}`)
              .join(' · ')}
      </p>
    </div>
  )
}

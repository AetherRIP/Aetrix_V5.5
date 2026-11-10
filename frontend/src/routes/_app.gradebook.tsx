import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Gradebook } from '../lib/api/types'
import { workspaceService } from '../lib/services'

export const Route = createFileRoute('/_app/gradebook')({
  component: Gradebook,
})

function Gradebook() {
  const session = useEngineSession()
  const [state, reload] = useResource<Gradebook>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => workspaceService.gradebook(session.tenantId!, { token: session.token, signal })
      : null,
  )

  const book = state.state === 'ok' ? state.data : null
  const students = book?.students ?? []
  const assignments = book?.assignments ?? []
  const columns = students.length > 0 ? students[0].cells.length : 0

  return (
    <div className="app-stack">
      <Panel title="Summary" note="Approved marks only, provisional shown separately">
        {book ? (
          <dl className="hub-stats">
            <div className="hub-stat">
              <dt className="hub-stat__label">Students</dt>
              <dd className="hub-stat__value mono">{students.length}</dd>
              <dd className="hub-stat__note">with at least one submission</dd>
            </div>
            <div className="hub-stat">
              <dt className="hub-stat__label">Approved results</dt>
              <dd className="hub-stat__value mono">{book.approved_jobs}</dd>
              <dd className="hub-stat__note">teacher-approved jobs</dd>
            </div>
            <div className="hub-stat">
              <dt className="hub-stat__label">Provisional</dt>
              <dd className="hub-stat__value mono">{book.provisional_jobs}</dd>
              <dd className="hub-stat__note">marked, not yet approved</dd>
            </div>
            <div className="hub-stat">
              <dt className="hub-stat__label">Mean percent</dt>
              <dd className="hub-stat__value mono">
                {book.mean_percent === null ? '—' : `${book.mean_percent.toFixed(1)}%`}
              </dd>
              <dd className="hub-stat__note">
                {book.mean_percent === null ? 'no approved marks yet' : 'approved marks only'}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="app-hint">
            No figures are shown until the engine returns this workspace’s gradebook. A blank
            panel is honest; a zero would not be.
          </p>
        )}
      </Panel>

      <Panel
        title="Marks"
        note={book ? `${assignments.length} assignment column(s)` : 'Waiting for the engine'}
      >
        {book ? (
          <>
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Gradebook: one row per student, one column per assignment
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    {assignments.map((assignment) => (
                      <th key={assignment.id} scope="col">
                        {assignment.name}
                        <span className="mono app-hint"> /{assignment.total_marks}</span>
                      </th>
                    ))}
                    <th scope="col">Approved total</th>
                  </tr>
                </thead>
                <tbody>
                  {students.length > 0 ? (
                    students.map((student) => (
                      <tr key={student.student_ref}>
                        <th scope="row">{student.student_ref}</th>
                        {assignments.map((assignment) => {
                          const cell = student.cells.find(
                            (entry) => entry.assignment_id === assignment.id,
                          )
                          if (!cell) {
                            return (
                              <td key={assignment.id} className="mono">
                                —
                              </td>
                            )
                          }
                          return (
                            <td key={assignment.id}>
                              <span className="mono">
                                {cell.awarded === null ? '—' : cell.awarded} / {cell.total}
                              </span>{' '}
                              <span
                                className="chip app-chip"
                                data-tone={cell.approved ? 'ok' : 'attention'}
                              >
                                {cell.approved
                                  ? 'Approved'
                                  : cell.review_required > 0
                                    ? 'Review'
                                    : 'Provisional'}
                              </span>
                            </td>
                          )
                        })}
                        <td className="mono">
                          {student.approved_possible === 0
                            ? '—'
                            : `${student.approved_awarded} / ${student.approved_possible}`}
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={assignments.length + 2} className="data-table__empty">
                        No students yet. Upload submissions from an assignment to populate the
                        gradebook.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
            {columns === 0 && students.length > 0 ? (
              <p className="app-hint">
                Students exist but no assignment columns do — the numbers are left blank rather
                than filled in.
              </p>
            ) : null}
            <div className="app-inline-actions">
              <button type="button" className="btn btn--small btn--outline" onClick={reload}>
                Refresh
              </button>
            </div>
          </>
        ) : (
          <p className="app-hint">
            No mark cells are shown until the engine returns this workspace’s gradebook.
          </p>
        )}
      </Panel>

      <DataState state={state} capability="GET /api/v1/workspaces/{id}/gradebook" />

      {book?.state === 'INSUFFICIENT_DATA' ? (
        <StatePanel tone="empty" title="Not enough approved marks for a summary">
          <p>
            The engine reports <code>INSUFFICIENT_DATA</code>: no assignment has both a complete
            set of submissions and at least one approved result. Mean percentages stay blank until
            then.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

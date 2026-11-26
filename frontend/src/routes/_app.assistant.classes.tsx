import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { Panel } from '../components/app/PageBlocks'
import { StatusChip } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import {
  classroomRoster,
  workspaceCourses,
  type RosterEntry,
  type TeacherCourse,
} from '../lib/api/classroom'

export const Route = createFileRoute('/_app/assistant/classes')({
  component: AssistantClasses,
})

function AssistantClasses() {
  const session = useEngineSession()
  const workspace = session.tenantId
  const [courseId, setCourseId] = useState<string | null>(null)

  const [courses] = useResource<TeacherCourse[]>(
    `assistant-classroom-courses:${workspace ?? 'none'}:${session.token ?? 'anonymous'}`,
    workspace && session.token
      ? (signal) => workspaceCourses(workspace, { token: session.token, signal })
      : null,
  )

  const [roster] = useResource<RosterEntry[]>(
    `assistant-classroom-roster:${workspace ?? 'none'}:${courseId ?? 'none'}:${session.token ?? 'anonymous'}`,
    workspace && session.token && courseId
      ? (signal) => classroomRoster(workspace, courseId, { token: session.token, signal })
      : null,
  )

  const rows = courses.state === 'ok' ? courses.data : []
  const selected = rows.find((row) => row.course_id === courseId) ?? null

  if (session.status === 'loading') {
    return (
      <div className="app-stack">
        <Panel title="Assigned classes" note="From your workspace administrator">
          <p className="panel-copy">Reading your class assignments…</p>
        </Panel>
      </div>
    )
  }

  if (session.status !== 'ready' || !workspace || !session.token) {
    return (
      <div className="app-stack">
        <Panel title="Assigned classes" note="From your workspace administrator">
          <p className="panel-copy">
            {session.reason ??
              'The engine has not returned your workspace membership, so no class is claimed here.'}
          </p>
        </Panel>
      </div>
    )
  }

  return (
    <div className="app-stack">
      <Panel title="Assigned classes" note="Only classes assigned to this account" index={0}>
        {courses.state === 'loading' ? (
          <p className="panel-copy">Reading assigned Classroom courses…</p>
        ) : courses.state === 'unavailable' || courses.state === 'error' ? (
          <p className="panel-copy">{courses.reason}</p>
        ) : rows.length === 0 ? (
          <p className="panel-copy">
            No class is assigned to this account. A workspace owner or administrator assigns
            a class; workspace membership alone does not grant access to its classes.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">
                Classroom classes assigned to this account
              </caption>
              <thead>
                <tr>
                  <th scope="col">Class</th>
                  <th scope="col">Section</th>
                  <th scope="col">Students</th>
                  <th scope="col">Coursework</th>
                  <th scope="col">Roster</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.allocation_id}>
                    <th scope="row">
                      <span className="data-table__strong">{row.name}</span>
                      <span className="gem-footnote mono">{row.course_id}</span>
                    </th>
                    <td>{row.section ?? '—'}</td>
                    <td className="mono">{row.students}</td>
                    <td className="mono">{row.coursework}</td>
                    <td>
                      <button
                        type="button"
                        className={`btn btn--small ${
                          courseId === row.course_id ? 'btn--primary' : ''
                        }`}
                        onClick={() =>
                          setCourseId(courseId === row.course_id ? null : row.course_id)
                        }
                      >
                        {courseId === row.course_id ? 'Hide roster' : 'View roster'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {selected ? (
        <Panel
          title={`Roster · ${selected.name}`}
          note="Students on the authorised class roster"
          index={1}
        >
          {roster.state === 'loading' ? (
            <p className="panel-copy">Reading the assigned roster…</p>
          ) : roster.state === 'unavailable' || roster.state === 'error' ? (
            <p className="panel-copy">{roster.reason}</p>
          ) : roster.data.length === 0 ? (
            <p className="panel-copy">
              This class has no synchronised student roster yet. The roster comes from Google
              Classroom; no placeholder rows are shown.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">
                  Students on {selected.name}
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    <th scope="col">Reference</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {roster.data.map((entry) => (
                    <tr key={entry.google_user_id}>
                      <td>
                        <span className="data-table__strong">
                          {entry.display_name ?? entry.google_name ?? entry.student_ref}
                        </span>
                        <span className="gem-footnote">{entry.google_name ?? '—'}</span>
                      </td>
                      <td className="mono">{entry.student_ref}</td>
                      <td>
                        <StatusChip tone={entry.status === 'ACTIVE' ? 'ok' : 'attention'}>
                          {entry.status}
                        </StatusChip>
                      </td>
                      <td>
                        {entry.last_seen_at
                          ? new Date(entry.last_seen_at).toLocaleString('en-GB')
                          : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : null}

      <Panel title="What you can do here" note="Review, not teaching" index={2}>
        <ul className="rule-list">
          <li>You see the Classroom classes assigned to you, and no others in the workspace.</li>
          <li>You can read an assigned roster, review its submissions and record review decisions.</li>
          <li>
            Starting corrections, synchronising rosters, publishing coursework and approving or
            publishing grades require a teacher, owner or administrator.
          </li>
          <li>Class assignment is controlled by a workspace owner or administrator.</li>
        </ul>
        <p className="panel-copy">
          Need another class? Ask your workspace administrator; you cannot assign one to
          yourself.{' '}
          <Link className="panel-link" to="/queue">
            Open the review queue
          </Link>
          {' · '}
          <Link className="panel-link" to="/reports">
            Results
          </Link>
        </p>
      </Panel>
    </div>
  )
}

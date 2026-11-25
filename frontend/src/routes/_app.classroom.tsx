import { useCallback, useEffect, useMemo, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useAuth } from '../lib/auth/AuthProvider'
import {
  approveSubmission,
  classroomRoster,
  courseworkSubmissions,
  createCoursework,
  ingestSubmission,
  listCoursework,
  publishCoursework,
  publishSubmissionGrade,
  submissionReview,
  syncClassroomRoster,
  syncCourseworkSubmissions,
  startSubmissionCorrection,
  workspaceAssignments,
  workspaceCourses,
  type Coursework,
  type RosterEntry,
  type Submission,
  type TeacherCourse,
  type WorkspaceAssignment,
} from '../lib/api/classroom'
import { useResource } from '../lib/api/useResource'

export const Route = createFileRoute('/_app/classroom')({
  component: Classroom,
})

type Notice = { tone: 'ok' | 'error'; message: string }

function formatMoment(value: string | null): string {
  if (!value) return 'never'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? 'unknown' : parsed.toLocaleString('en-GB')
}

function stateTone(state: string): 'ok' | 'attention' | 'neutral' {
  if (state === 'PUBLISHED' || state === 'INGESTED' || state === 'CORRECTED') return 'ok'
  if (state === 'FAILED' || state === 'INGEST_FAILED' || state === 'CONFLICT') return 'attention'
  return 'neutral'
}

/**
 * The teacher's Classroom page.
 *
 * Everything here is a workspace-scoped read or an explicitly confirmed action.
 * No Google credential exists in this browser: the central account performs
 * every Classroom call on the engine.  A course the platform has not allocated
 * to this workspace is not listed, and the engine refuses it as nonexistent.
 */
function Classroom() {
  const { session } = useAuth()
  const engine = useEngineSession()
  const token = session?.access_token ?? null
  const tenantId = engine.tenantId

  const [courseId, setCourseId] = useState<string | null>(null)
  const [courseworkId, setCourseworkId] = useState<string | null>(null)
  const [notice, setNotice] = useState<Notice | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [courses, reloadCourses] = useResource<TeacherCourse[]>(
    `classroom-courses:${tenantId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId ? (signal) => workspaceCourses(tenantId, { token, signal }) : null,
  )

  const [assignments] = useResource<WorkspaceAssignment[]>(
    `classroom-assignments:${tenantId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId ? (signal) => workspaceAssignments(tenantId, { token, signal }) : null,
  )

  const [roster, reloadRoster] = useResource<RosterEntry[]>(
    `classroom-roster:${tenantId ?? 'none'}:${courseId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId && courseId
      ? (signal) => classroomRoster(tenantId, courseId, { token, signal })
      : null,
  )

  const [coursework, reloadCoursework] = useResource<Coursework[]>(
    `classroom-coursework:${tenantId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId ? (signal) => listCoursework(tenantId, { token, signal }) : null,
  )

  const [submissions, reloadSubmissions] = useResource<Submission[]>(
    `classroom-submissions:${tenantId ?? 'none'}:${courseworkId ?? 'none'}:${token ?? 'anonymous'}`,
    token && tenantId && courseworkId
      ? (signal) => courseworkSubmissions(tenantId, courseworkId, { token, signal })
      : null,
  )

  const courseList = courses.state === 'ok' ? courses.data : []
  const courseworkList = coursework.state === 'ok' ? coursework.data : []
  const selectedCoursework = useMemo(
    () => courseworkList.find((row) => row.id === courseworkId) ?? null,
    [courseworkId, courseworkList],
  )

  useEffect(() => {
    if (!courseId && courseList.length > 0) setCourseId(courseList[0].course_id)
  }, [courseId, courseList])

  useEffect(() => {
    if (
      selectedCoursework &&
      courseId &&
      selectedCoursework.course_id !== courseId
    ) {
      setCourseworkId(null)
    }
  }, [courseId, selectedCoursework])

  const refreshAll = useCallback(() => {
    reloadCourses()
    reloadCoursework()
    reloadRoster()
    reloadSubmissions()
  }, [reloadCoursework, reloadCourses, reloadRoster, reloadSubmissions])

  const run = async (key: string, action: () => Promise<{ ok: boolean; message: string }>) => {
    setBusy(key)
    setNotice(null)
    const result = await action()
    setBusy(null)
    setNotice({ tone: result.ok ? 'ok' : 'error', message: result.message })
    refreshAll()
  }

  if (!token || !tenantId) {
    return (
      <Panel title="Allocated Classroom courses" note="Platform allocated">
        <StatePanel tone="wip" title="Sign in to use Google Classroom">
          <p>
            Classroom actions run against the workspace you are signed in to. Sign in to see
            the courses allocated to it; allocation itself is a platform decision.
          </p>
        </StatePanel>
      </Panel>
    )
  }

  return (
    <div className="app-stack">
      {notice ? (
        <div className="gem-notice" data-tone={notice.tone} role="status">
          {notice.message}
        </div>
      ) : null}

      <Panel title="Allocated Classroom courses" note="Assigned by platform administration">
        {courses.state === 'loading' ? (
          <p className="panel-copy">Reading this workspace’s courses…</p>
        ) : courses.state === 'unavailable' || courses.state === 'error' ? (
          <p className="panel-copy">{courses.reason}</p>
        ) : courseList.length === 0 ? (
          <p className="panel-copy">
            No Classroom course is allocated to this workspace. Allocation is a platform
            administrator action; teachers cannot request, move or reassign a course.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Classroom courses allocated here</caption>
              <thead>
                <tr>
                  <th scope="col">Class</th>
                  <th scope="col">Course ID</th>
                  <th scope="col">Students</th>
                  <th scope="col">Coursework</th>
                  <th scope="col">Select</th>
                </tr>
              </thead>
              <tbody>
                {courseList.map((course) => (
                  <tr key={course.allocation_id}>
                    <td>
                      <span className="data-table__strong">{course.name}</span>
                      {course.section ? <span className="gem-footnote">{course.section}</span> : null}
                    </td>
                    <td className="mono">{course.course_id}</td>
                    <td>{course.students}</td>
                    <td>{course.coursework}</td>
                    <td>
                      <button
                        type="button"
                        className={`btn btn--small ${courseId === course.course_id ? 'btn--primary' : ''}`}
                        onClick={() => setCourseId(course.course_id)}
                      >
                        {courseId === course.course_id ? 'Selected' : 'Select'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {courseId ? (
        <Panel
          title="Student roster"
          note="Matched by Google user id, never by display name"
        >
          <div className="app-inline-actions">
            <button
              type="button"
              className="btn btn--small btn--primary"
              disabled={busy !== null}
              onClick={() =>
                void run('roster', async () => {
                  const result = await syncClassroomRoster(tenantId, courseId, { token })
                  if (result.status !== 'ok') return { ok: false, message: result.reason }
                  const counts = result.data.counts
                  return {
                    ok: true,
                    message:
                      `Roster read: ${counts.discovered ?? 0} discovered, ` +
                      `${counts.created ?? 0} new, ${counts.matched ?? 0} matched to existing ` +
                      `students, ${counts.removed ?? 0} marked as left` +
                      (result.data.problems.length
                        ? `. ${result.data.problems.length} problem(s): ${result.data.problems[0]}`
                        : result.data.truncated
                          ? '. The roster hit the configured ceiling and is partial.'
                          : '.'),
                  }
                })
              }
            >
              {busy === 'roster' ? 'Synchronising roster…' : 'Synchronise roster'}
            </button>
          </div>

          {roster.state === 'loading' ? (
            <p className="panel-copy">Reading the synchronized roster…</p>
          ) : roster.state === 'unavailable' || roster.state === 'error' ? (
            <p className="panel-copy">{roster.reason}</p>
          ) : roster.data.length === 0 ? (
            <p className="panel-copy">
              No student has been synchronised for this course yet. The roster comes from Google
              Classroom; matching fills a blank Aetrix name and never overwrites one a teacher
              maintained.
            </p>
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Students synchronised from Classroom</caption>
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    <th scope="col">Google name</th>
                    <th scope="col">Matched by</th>
                    <th scope="col">Status</th>
                    <th scope="col">Last seen</th>
                  </tr>
                </thead>
                <tbody>
                  {roster.data.map((entry) => (
                    <tr key={entry.google_user_id}>
                      <td>
                        <span className="data-table__strong">
                          {entry.display_name ?? entry.student_ref}
                        </span>
                        <span className="gem-footnote mono">{entry.student_ref}</span>
                      </td>
                      <td>{entry.google_name ?? '—'}</td>
                      <td>{entry.match_source}</td>
                      <td>
                        <StatusChip tone={entry.status === 'ACTIVE' ? 'ok' : 'attention'}>
                          {entry.status}
                        </StatusChip>
                      </td>
                      <td>{formatMoment(entry.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      ) : null}

      <CourseworkPanel
        tenantId={tenantId}
        token={token}
        courseId={courseId}
        courses={courseList}
        assignments={assignments.state === 'ok' ? assignments.data : []}
        courseworkList={courseworkList}
        courseworkState={coursework.state}
        courseworkReason={
          coursework.state === 'unavailable' || coursework.state === 'error'
            ? coursework.reason
            : null
        }
        busy={busy}
        onSelect={setCourseworkId}
        selectedId={courseworkId}
        onRun={run}
        onRefresh={refreshAll}
      />

      {selectedCoursework ? (
        <SubmissionsPanel
          tenantId={tenantId}
          token={token}
          coursework={selectedCoursework}
          submissions={submissions.state === 'ok' ? submissions.data : []}
          submissionsState={submissions.state}
          submissionsReason={
            submissions.state === 'unavailable' || submissions.state === 'error'
              ? submissions.reason
              : null
          }
          busy={busy}
          onRun={run}
          onRefresh={refreshAll}
        />
      ) : null}

      <Panel title="How a grade reaches Classroom" note="Approval before publication">
        <ol className="panel-copy">
          <li>A submission is retrieved and ingested through the engine’s existing pipeline.</li>
          <li>Marking runs through the single Aetrix V5.5 correction engine; nothing here marks.</li>
          <li>Every uncertain question must be decided before the result can be approved.</li>
          <li>A reviewer approves the final total and states a reason.</li>
          <li>Publication writes the assigned grade, and only then is it visible to the student.</li>
        </ol>
        <p className="panel-copy">
          Nothing is published automatically. A publication that Google did not confirm stays
          <strong> UNKNOWN </strong>until a retry reconciles it against Google, so a retry never
          writes a grade twice.
        </p>
      </Panel>
    </div>
  )
}

type RunAction = (
  key: string,
  action: () => Promise<{ ok: boolean; message: string }>,
) => Promise<void>

function CourseworkPanel({
  tenantId,
  token,
  courseId,
  courses,
  assignments,
  courseworkList,
  courseworkState,
  courseworkReason,
  busy,
  selectedId,
  onSelect,
  onRun,
  onRefresh,
}: {
  tenantId: string
  token: string
  courseId: string | null
  courses: TeacherCourse[]
  assignments: WorkspaceAssignment[]
  courseworkList: Coursework[]
  courseworkState: string
  courseworkReason: string | null
  busy: string | null
  selectedId: string | null
  onSelect: (id: string) => void
  onRun: RunAction
  onRefresh: () => void
}) {
  const [assignmentId, setAssignmentId] = useState('')
  const [title, setTitle] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [maxPoints, setMaxPoints] = useState('')
  const course = courses.find((row) => row.course_id === courseId) ?? null

  return (
    <Panel title="Classroom coursework" note="Created in Aetrix, published explicitly">
      {courseworkState === 'loading' ? (
        <p className="panel-copy">Reading coursework…</p>
      ) : courseworkState === 'unavailable' || courseworkState === 'error' ? (
        <p className="panel-copy">{courseworkReason}</p>
      ) : courseworkList.length === 0 ? (
        <p className="panel-copy">
          No assignment has a Classroom coursework yet. Create one below, then publish it when
          the assignment’s blueprint and mark scheme are approved.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Aetrix assignments published to Classroom</caption>
            <thead>
              <tr>
                <th scope="col">Coursework</th>
                <th scope="col">Coursework ID</th>
                <th scope="col">State</th>
                <th scope="col">Submissions</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {courseworkList.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="data-table__strong">{row.title}</span>
                    <span className="gem-footnote">{row.assignment_name}</span>
                  </td>
                  <td className="mono">{row.coursework_id ?? '—'}</td>
                  <td>
                    <StatusChip tone={stateTone(row.state)}>{row.state}</StatusChip>
                    {row.last_error_message ? (
                      <span className="gem-footnote">{row.last_error_message}</span>
                    ) : null}
                  </td>
                  <td>{row.submissions}</td>
                  <td>
                    <div className="app-inline-actions">
                      <button
                        type="button"
                        className={`btn btn--small ${selectedId === row.id ? 'btn--primary' : ''}`}
                        onClick={() => onSelect(row.id)}
                      >
                        {selectedId === row.id ? 'Selected' : 'Open'}
                      </button>
                      {row.state !== 'PUBLISHED' ? (
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={busy !== null}
                          onClick={() =>
                            void onRun(`publish:${row.id}`, async () => {
                              const result = await publishCoursework(tenantId, row.id, { token })
                              if (result.status !== 'ok') {
                                return { ok: false, message: result.reason }
                              }
                              return {
                                ok: true,
                                message: `Published as coursework ${result.data.coursework_id}.`,
                              }
                            })
                          }
                        >
                          {busy === `publish:${row.id}` ? 'Publishing…' : 'Publish'}
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {course ? (
        <form
          className="app-form"
          onSubmit={(event) => {
            event.preventDefault()
            const points = maxPoints.trim() ? Number(maxPoints) : undefined
            void onRun('create', async () => {
              const result = await createCoursework(
                tenantId,
                {
                  assignment_id: assignmentId,
                  classroom_class_id: course.classroom_class_id,
                  title: title.trim() || undefined,
                  due_at: dueAt ? new Date(dueAt).toISOString() : undefined,
                  max_points: Number.isFinite(points) ? points : undefined,
                },
                { token },
              )
              if (result.status !== 'ok') return { ok: false, message: result.reason }
              setTitle('')
              setDueAt('')
              setMaxPoints('')
              onRefresh()
              return {
                ok: true,
                message: `Drafted “${result.data.title}”. Publish it when you are ready.`,
              }
            })
          }}
        >
          <label className="app-form__label" htmlFor="classroom-assignment">
            Aetrix assignment
          </label>
          <select
            id="classroom-assignment"
            className="app-input"
            value={assignmentId}
            onChange={(event) => setAssignmentId(event.target.value)}
            required
          >
            <option value="">Select an assignment…</option>
            {assignments.map((assignment) => (
              <option key={assignment.id} value={assignment.id}>
                {assignment.name}
              </option>
            ))}
          </select>

          <label className="app-form__label" htmlFor="classroom-title">
            Classroom title (defaults to the assignment name)
          </label>
          <input
            id="classroom-title"
            className="app-input"
            value={title}
            maxLength={300}
            onChange={(event) => setTitle(event.target.value)}
          />

          <label className="app-form__label" htmlFor="classroom-due">
            Due date and time
          </label>
          <input
            id="classroom-due"
            className="app-input"
            type="datetime-local"
            value={dueAt}
            onChange={(event) => setDueAt(event.target.value)}
          />

          <label className="app-form__label" htmlFor="classroom-points">
            Maximum points
          </label>
          <input
            id="classroom-points"
            className="app-input"
            type="number"
            min={0}
            step="0.5"
            value={maxPoints}
            onChange={(event) => setMaxPoints(event.target.value)}
          />

          <div className="app-inline-actions">
            <button
              type="submit"
              className="btn btn--small btn--primary"
              disabled={busy !== null || !assignmentId}
            >
              {busy === 'create' ? 'Drafting…' : 'Draft coursework'}
            </button>
          </div>
        </form>
      ) : (
        <p className="panel-copy">Select an allocated course to draft coursework for it.</p>
      )}
      {assignments.length === 0 ? (
        <p className="panel-copy">
          This workspace has no assignment yet. Create the assignment, its approved blueprint and
          its approved mark scheme first; a coursework cannot exist without them.
        </p>
      ) : null}
    </Panel>
  )
}

function SubmissionsPanel({
  tenantId,
  token,
  coursework,
  submissions,
  submissionsState,
  submissionsReason,
  busy,
  onRun,
  onRefresh,
}: {
  tenantId: string
  token: string
  coursework: Coursework
  submissions: Submission[]
  submissionsState: string
  submissionsReason: string | null
  busy: string | null
  onRun: RunAction
  onRefresh: () => void
}) {
  const [openId, setOpenId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [returnToStudent, setReturnToStudent] = useState(true)
  const [overwrite, setOverwrite] = useState(false)
  const [review, setReview] = useState<Record<string, string>>({})

  const loadReview = async (id: string) => {
    const result = await submissionReview(tenantId, id, { token })
    setReview((current) => ({
      ...current,
      [id]: result.status === 'ok' ? result.data.reason : result.reason,
    }))
  }

  return (
    <Panel
      title={`Submissions · ${coursework.title}`}
      note={coursework.state === 'PUBLISHED' ? 'Retrieved from Classroom' : 'Publish the coursework first'}
    >
      <div className="app-inline-actions">
        <button
          type="button"
          className="btn btn--small btn--primary"
          disabled={busy !== null || coursework.state !== 'PUBLISHED'}
          onClick={() =>
            void onRun('submissions', async () => {
              const result = await syncCourseworkSubmissions(tenantId, coursework.id, { token })
              if (result.status !== 'ok') return { ok: false, message: result.reason }
              const counts = result.data.counts
              return {
                ok: true,
                message:
                  `${counts.discovered ?? 0} submission(s) found, ${counts.ingested ?? 0} ingested, ` +
                  `${counts.ingest_failed ?? 0} refused, ${counts.without_student ?? 0} without a ` +
                  `matched student` +
                  (result.data.problems.length ? `. ${result.data.problems[0]}` : '.'),
              }
            })
          }
        >
          {busy === 'submissions' ? 'Retrieving…' : 'Retrieve submissions'}
        </button>
      </div>

      {submissionsState === 'loading' ? (
        <p className="panel-copy">Reading stored submissions…</p>
      ) : submissionsState === 'unavailable' || submissionsState === 'error' ? (
        <p className="panel-copy">{submissionsReason}</p>
      ) : submissions.length === 0 ? (
        <p className="panel-copy">
          No submission has been retrieved for this coursework. Students must turn work in on
          Google Classroom; this page never invents a submission.
        </p>
      ) : (
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Student submissions and their progress</caption>
            <thead>
              <tr>
                <th scope="col">Student</th>
                <th scope="col">Ingestion</th>
                <th scope="col">Marking</th>
                <th scope="col">Approved</th>
                <th scope="col">Published</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {submissions.map((row) => (
                <tr key={row.id}>
                  <td>
                    <span className="data-table__strong">
                      {row.student_name ?? row.student_ref}
                    </span>
                    <span className="gem-footnote">
                      {row.late ? 'Late · ' : ''}
                      {row.submission_state ?? 'state unknown'}
                    </span>
                  </td>
                  <td>
                    <StatusChip tone={stateTone(row.state)}>{row.state}</StatusChip>
                    {row.ingest_error ? (
                      <span className="gem-footnote">{row.ingest_error}</span>
                    ) : null}
                  </td>
                  <td>{row.correction_state ?? 'not started'}</td>
                  <td>{row.approved_total != null ? `${row.approved_total}` : '—'}</td>
                  <td>
                    {row.last_publication_state ? (
                      <StatusChip tone={stateTone(row.last_publication_state)}>
                        {row.last_publication_state}
                      </StatusChip>
                    ) : (
                      'not published'
                    )}
                  </td>
                  <td>
                    <div className="app-inline-actions">
                      {row.state === 'DISCOVERED' || row.state === 'INGEST_FAILED' ? (
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={busy !== null}
                          onClick={() =>
                            void onRun(`ingest:${row.id}`, async () => {
                              const result = await ingestSubmission(tenantId, row.id, { token })
                              if (result.status !== 'ok') return { ok: false, message: result.reason }
                              return {
                                ok: true,
                                message:
                                  result.data.state === 'INGESTED'
                                    ? 'The attachment entered the ingestion pipeline.'
                                    : (result.data.ingest_error ??
                                      'The attachment was not ingested.'),
                              }
                            })
                          }
                        >
                          {busy === `ingest:${row.id}` ? 'Ingesting…' : 'Retry ingestion'}
                        </button>
                      ) : null}
                      {row.state === 'INGESTED' || row.state === 'CORRECTING' ? (
                        <button
                          type="button"
                          className="btn btn--small"
                          disabled={busy !== null}
                          onClick={() =>
                            void onRun(`correct:${row.id}`, async () => {
                              const result = await startSubmissionCorrection(tenantId, row.id, {
                                token,
                              })
                              if (result.status !== 'ok') return { ok: false, message: result.reason }
                              return {
                                ok: true,
                                message: result.data.created
                                  ? `Correction job ${result.data.job_state}.`
                                  : `This submission already has correction job ${result.data.job_state}.`,
                              }
                            })
                          }
                        >
                          {busy === `correct:${row.id}` ? 'Starting…' : 'Start marking'}
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="btn btn--small"
                        onClick={() => {
                          setOpenId(openId === row.id ? null : row.id)
                          void loadReview(row.id)
                        }}
                      >
                        {openId === row.id ? 'Close' : 'Review'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {openId ? (
        <div className="app-stack">
          <p className="panel-copy">{review[openId] ?? 'Reading the review state…'}</p>
          <div className="app-inline-actions">
            <button
              type="button"
              className="btn btn--small btn--primary"
              disabled={busy !== null}
              onClick={() =>
                void onRun(`approve:${openId}`, async () => {
                  const result = await approveSubmission(tenantId, openId, undefined, { token })
                  if (result.status !== 'ok') return { ok: false, message: result.reason }
                  void loadReview(openId)
                  return {
                    ok: true,
                    message: `Approved ${result.data.total} of ${result.data.maximum}.`,
                  }
                })
              }
            >
              {busy === `approve:${openId}` ? 'Approving…' : 'Approve final result'}
            </button>
          </div>

          <label className="app-form__label" htmlFor="publish-reason">
            Reason for publishing (recorded in the audit trail)
          </label>
          <input
            id="publish-reason"
            className="app-input"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
          />
          <label className="panel-copy">
            <input
              type="checkbox"
              checked={returnToStudent}
              onChange={(event) => setReturnToStudent(event.target.checked)}
            />{' '}
            Return the work to the student after writing the grade
          </label>
          <label className="panel-copy">
            <input
              type="checkbox"
              checked={overwrite}
              onChange={(event) => setOverwrite(event.target.checked)}
            />{' '}
            Replace an assigned grade Classroom already holds
          </label>
          <div className="app-inline-actions">
            <button
              type="button"
              className="btn btn--small btn--danger"
              disabled={busy !== null || reason.trim().length < 5}
              onClick={() =>
                void onRun(`publish-grade:${openId}`, async () => {
                  const result = await publishSubmissionGrade(
                    tenantId,
                    openId,
                    {
                      confirm: true,
                      reason: reason.trim(),
                      grade_field: 'assignedGrade',
                      return_to_student: returnToStudent,
                      allow_overwrite_external: overwrite,
                    },
                    { token },
                  )
                  if (result.status !== 'ok') return { ok: false, message: result.reason }
                  onRefresh()
                  const detail = result.data.response_detail as {
                    returned_to_student?: boolean
                    return_error?: string | null
                  }
                  return {
                    ok: true,
                    message:
                      `Grade ${result.data.assigned_grade ?? result.data.draft_grade} written to Classroom.` +
                      (detail.returned_to_student
                        ? ' The work was returned to the student.'
                        : detail.return_error
                          ? ` The grade was written but the work was not returned: ${detail.return_error}`
                          : ''),
                  }
                })
              }
            >
              {busy === `publish-grade:${openId}` ? 'Publishing…' : 'Publish approved grade'}
            </button>
          </div>
        </div>
      ) : null}
    </Panel>
  )
}

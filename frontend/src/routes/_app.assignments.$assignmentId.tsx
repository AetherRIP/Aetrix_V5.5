import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Assignment, Blueprint, Job, SchemeVersion, Submission } from '../lib/api/types'
import {
  assignmentService,
  examService,
  queueService,
  sha256File,
  submissionService,
} from '../lib/services'

export const Route = createFileRoute('/_app/assignments/$assignmentId')({
  component: AssignmentDetail,
})

type Tab = 'overview' | 'scheme' | 'submissions'
type UploadOutcome = { file: string; ok: boolean; message: string }

function AssignmentDetail() {
  const { assignmentId } = Route.useParams()
  const session = useEngineSession()
  const [tab, setTab] = useState<Tab>('overview')
  const [message, setMessage] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [assignmentState, reloadAssignment] = useResource<Assignment>(
    assignmentId,
    session.token
      ? (signal) => assignmentService.get(assignmentId, { token: session.token, signal })
      : null,
  )
  const assignment = assignmentState.state === 'ok' ? assignmentState.data : null
  const examId = assignment?.exam_id ?? null

  const [blueprintState, reloadBlueprint] = useResource<Blueprint>(
    examId ?? 'none',
    examId && session.token
      ? (signal) => examService.blueprint(examId, { token: session.token, signal })
      : null,
  )
  const [schemesState, reloadSchemes] = useResource<SchemeVersion[]>(
    examId ?? 'none',
    examId && session.token
      ? (signal) => examService.schemeVersions(examId, { token: session.token, signal })
      : null,
  )
  const [submissionsState, reloadSubmissions] = useResource<Submission[]>(
    assignmentId,
    session.token
      ? (signal) => assignmentService.submissions(assignmentId, { token: session.token, signal })
      : null,
  )
  const [jobsState, reloadJobs] = useResource<Job[]>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => queueService.list(session.tenantId!, { token: session.token, signal })
      : null,
  )

  const [schemeTitle, setSchemeTitle] = useState('')
  const [schemeFile, setSchemeFile] = useState<File | null>(null)
  const [approvalReason, setApprovalReason] = useState('')
  const [uploads, setUploads] = useState<UploadOutcome[]>([])

  const approvedScheme =
    schemesState.state === 'ok'
      ? schemesState.data.find((version) => version.status === 'APPROVED')
      : undefined
  const draftScheme =
    schemesState.state === 'ok'
      ? schemesState.data.find((version) => version.status === 'DRAFT')
      : undefined
  const blueprint = blueprintState.state === 'ok' ? blueprintState.data : null
  const jobs = jobsState.state === 'ok' ? jobsState.data : []
  const jobsBySubmission = new Map(
    jobs
      .filter((job) => job.assignment_id === assignmentId)
      .map((job) => [job.submission_id, job]),
  )

  async function uploadScheme(event: React.FormEvent) {
    event.preventDefault()
    if (!examId || !session.token || !schemeFile) return
    setBusy(true)
    setMessage(null)
    const result = await examService.uploadScheme(
      examId,
      schemeTitle.trim() || schemeFile.name,
      schemeFile,
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setSchemeFile(null)
      setSchemeTitle('')
      setMessage('Scheme uploaded as a draft. Review it, approve it, then extract the blueprint.')
      reloadSchemes()
    } else {
      setMessage(result.reason)
    }
  }

  async function approveScheme(versionId: string) {
    if (!session.token || !approvalReason.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await examService.approveScheme(versionId, approvalReason.trim(), {
      token: session.token,
    })
    setBusy(false)
    if (result.status === 'ok') {
      setMessage('Mark scheme approved. It can now be used by an assignment.')
      reloadSchemes()
    } else {
      setMessage(result.reason)
    }
  }

  async function extractBlueprint() {
    if (!examId || !session.token || !approvedScheme) return
    setBusy(true)
    setMessage(null)
    const result = await examService.extract(examId, approvedScheme.id, { token: session.token })
    setBusy(false)
    if (result.status === 'ok') {
      setMessage('Blueprint extracted as a draft. Check the question marks, then approve it.')
      reloadBlueprint()
    } else {
      setMessage(result.reason)
    }
  }

  async function approveBlueprint() {
    if (!examId || !session.token || !blueprint || !approvalReason.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await examService.putBlueprint(
      examId,
      { structure: blueprint.structure, approve: true, reason: approvalReason.trim() },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setMessage('Blueprint approved. Marking can now use this question structure.')
      reloadBlueprint()
      reloadAssignment()
    } else {
      setMessage(result.reason)
    }
  }

  async function uploadSubmissions(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''
    if (!files.length || !session.token) return
    setBusy(true)
    setMessage(null)
    const outcomes: UploadOutcome[] = []
    for (const file of files) {
      const studentRef = file.name.replace(/\.[^.]+$/, '').slice(0, 120)
      try {
        const hash = await sha256File(file)
        const registered = await submissionService.register(
          { assignment_id: assignmentId, student_ref: studentRef, content_hash: hash },
          { token: session.token },
        )
        if (registered.status !== 'ok') {
          outcomes.push({ file: file.name, ok: false, message: registered.reason })
          continue
        }
        const document = await submissionService.uploadDocument(registered.data.id, file, {
          token: session.token,
        })
        if (document.status !== 'ok') {
          outcomes.push({ file: file.name, ok: false, message: document.reason })
          continue
        }
        const job = await queueService.create(
          { assignment_id: assignmentId, submission_id: registered.data.id },
          { token: session.token },
        )
        outcomes.push({
          file: file.name,
          ok: job.status === 'ok',
          message:
            job.status === 'ok'
              ? `Stored ${document.data.page_count} page(s); correction job queued (${job.data.state}).`
              : `Stored, but the correction job was refused: ${job.reason}`,
        })
      } catch {
        outcomes.push({ file: file.name, ok: false, message: 'The file could not be read.' })
      }
    }
    setBusy(false)
    setUploads(outcomes)
    reloadSubmissions()
    reloadJobs()
  }

  return (
    <div className="app-stack">
      <section className="record-head" aria-label="Assignment record">
        <div>
          <p className="record-head__kicker mono">Assignment</p>
          <p className="record-head__id mono">{assignment ? assignment.name : assignmentId}</p>
        </div>
        <div className="record-head__meta">
          <span className="chip app-chip" data-tone={blueprint?.status === 'APPROVED' ? 'ok' : 'attention'}>
            {blueprint ? `Blueprint ${blueprint.status}` : 'No blueprint'}
          </span>
          <Link className="btn btn--small btn--outline" to="/assignments">
            Back to assignments
          </Link>
        </div>
      </section>

      <DataState state={assignmentState} capability="GET /api/v1/assignments/{id}">
        {message ? <p className="app-message">{message}</p> : null}

        <div className="app-tabs" role="tablist" aria-label="Assignment sections">
          {([
            ['overview', 'Overview'],
            ['scheme', 'Scheme & blueprint'],
            ['submissions', 'Submissions'],
          ] as const).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={tab === id}
              className={tab === id ? 'app-tab is-active' : 'app-tab'}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>

        {tab === 'overview' ? (
          <div className="app-split">
            <Panel title="Marking contract" note="What the engine will mark against">
              <dl className="app-definitions">
                <div>
                  <dt>Review mode</dt>
                  <dd className="mono">{assignment?.review_mode ?? '—'}</dd>
                </div>
                <div>
                  <dt>Completion threshold</dt>
                  <dd className="mono">
                    {assignment ? `${Math.round(assignment.completion_threshold * 100)}%` : '—'}
                  </dd>
                </div>
                <div>
                  <dt>Blueprint</dt>
                  <dd>
                    {blueprint
                      ? `${blueprint.status} v${blueprint.version} · ${blueprint.total_marks} marks`
                      : 'Not extracted'}
                  </dd>
                </div>
                <div>
                  <dt>Mark scheme</dt>
                  <dd>
                    {approvedScheme
                      ? `Approved v${approvedScheme.version}`
                      : draftScheme
                        ? `Draft v${draftScheme.version} — not approved`
                        : 'Not uploaded'}
                  </dd>
                </div>
              </dl>
              <div className="app-inline-actions">
                <button type="button" className="btn btn--small btn--outline" onClick={() => setTab('scheme')}>
                  Set up the paper
                </button>
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  onClick={() => setTab('submissions')}
                >
                  Upload submissions
                </button>
              </div>
            </Panel>

            <Panel title="Question structure" note={blueprint ? `${blueprint.structure.questions.length} question(s)` : 'Awaits extraction'}>
              <div className="table-scroll">
                <table className="data-table">
                  <caption className="visually-hidden">Blueprint questions</caption>
                  <thead>
                    <tr>
                      <th scope="col">Question</th>
                      <th scope="col">Marks</th>
                      <th scope="col">Answer type</th>
                    </tr>
                  </thead>
                  <tbody>
                    {blueprint && blueprint.structure.questions.length > 0 ? (
                      blueprint.structure.questions.flatMap((question) =>
                        question.subquestions.length > 0
                          ? question.subquestions.map((sub) => (
                              <tr key={sub.question_id}>
                                <td className="mono">{sub.question_id}</td>
                                <td className="mono">{sub.max_marks}</td>
                                <td>{sub.answer_type ?? '—'}</td>
                              </tr>
                            ))
                          : [
                              <tr key={question.question_id}>
                                <td className="mono">{question.question_id}</td>
                                <td className="mono">{question.max_marks}</td>
                                <td>{question.answer_type ?? '—'}</td>
                              </tr>,
                            ],
                      )
                    ) : (
                      <tr>
                        <td colSpan={3} className="data-table__empty">
                          No approved question structure yet. Extract and approve a blueprint.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        ) : null}

        {tab === 'scheme' ? (
          <div className="app-stack">
            <Panel title="Upload a mark scheme" note="Stored, rendered and versioned by the engine">
              <form className="app-form" onSubmit={uploadScheme}>
                <div className="app-form__row">
                  <label className="app-form__label" htmlFor="scheme-title">
                    Scheme title
                  </label>
                  <input
                    id="scheme-title"
                    className="app-input"
                    value={schemeTitle}
                    onChange={(event) => setSchemeTitle(event.target.value)}
                    maxLength={300}
                  />
                </div>
                <div className="app-form__row">
                  <label className="app-form__label" htmlFor="scheme-file">
                    PDF
                  </label>
                  <input
                    id="scheme-file"
                    className="app-input"
                    type="file"
                    accept="application/pdf,image/png,image/jpeg"
                    onChange={(event) => setSchemeFile(event.target.files?.[0] ?? null)}
                  />
                </div>
                <button
                  type="submit"
                  className="btn btn--small btn--primary"
                  disabled={busy || !schemeFile}
                >
                  {busy ? 'Uploading…' : 'Upload scheme'}
                </button>
              </form>
            </Panel>

            <Panel title="Scheme versions" note="Approval is separate from upload">
              <div className="table-scroll">
                <table className="data-table">
                  <caption className="visually-hidden">Mark-scheme versions for this exam</caption>
                  <thead>
                    <tr>
                      <th scope="col">Version</th>
                      <th scope="col">Status</th>
                      <th scope="col">Source</th>
                      <th scope="col">Created</th>
                      <th scope="col">Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {schemesState.state === 'ok' && schemesState.data.length > 0 ? (
                      schemesState.data.map((version) => (
                        <tr key={version.id}>
                          <td className="mono">v{version.version}</td>
                          <td>
                            <span className="chip app-chip" data-tone={version.status === 'APPROVED' ? 'ok' : 'attention'}>
                              {version.status}
                            </span>
                          </td>
                          <td className="mono">{version.source}</td>
                          <td className="mono">{new Date(version.created_at).toLocaleDateString()}</td>
                          <td>
                            {version.status === 'DRAFT' ? (
                              <button
                                type="button"
                                className="btn btn--small btn--outline"
                                disabled={busy || !approvalReason.trim()}
                                onClick={() => void approveScheme(version.id)}
                                title="Enter an approval reason below first"
                              >
                                Approve
                              </button>
                            ) : (
                              '—'
                            )}
                          </td>
                        </tr>
                      ))
                    ) : (
                      <tr>
                        <td colSpan={5} className="data-table__empty">
                          No scheme versions yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <div className="app-form__row">
                <label className="app-form__label" htmlFor="approval-reason">
                  Approval reason (required to approve a scheme or blueprint)
                </label>
                <input
                  id="approval-reason"
                  className="app-input"
                  value={approvalReason}
                  onChange={(event) => setApprovalReason(event.target.value)}
                  maxLength={2000}
                />
              </div>
              <div className="app-inline-actions">
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={busy || !approvedScheme}
                  onClick={() => void extractBlueprint()}
                >
                  Extract blueprint
                </button>
                <button
                  type="button"
                  className="btn btn--small btn--outline"
                  disabled={busy || !blueprint || blueprint.status === 'APPROVED' || !approvalReason.trim()}
                  onClick={() => void approveBlueprint()}
                >
                  Approve blueprint
                </button>
                <span className="mono app-hint">
                  {blueprint ? `Current: ${blueprint.status} v${blueprint.version}` : 'No blueprint yet'}
                </span>
              </div>
            </Panel>
          </div>
        ) : null}

        {tab === 'submissions' ? (
          <div className="app-stack">
            <Panel title="Upload submissions" note="One file per student">
              <p className="app-card__body">
                Each file is hashed, registered against this assignment, rendered to pages and
                queued for marking. The student reference is the file name without its extension.
              </p>
              <input
                className="app-input"
                type="file"
                accept="application/pdf,image/png,image/jpeg"
                multiple
                disabled={busy}
                onChange={(event) => void uploadSubmissions(event)}
                aria-label="Upload student submissions"
              />
              {uploads.length ? (
                <ul className="app-upload-list">
                  {uploads.map((outcome) => (
                    <li key={outcome.file} className="app-upload-list__row">
                      <span className="mono">{outcome.file}</span>
                      <span className="chip app-chip" data-tone={outcome.ok ? 'ok' : 'attention'}>
                        {outcome.ok ? 'Queued' : 'Rejected'}
                      </span>
                      <span className="app-upload-list__detail">{outcome.message}</span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </Panel>

            <Panel title="Submissions" note="State is the engine's, not the browser's">
              <div className="table-scroll">
                <table className="data-table">
                  <caption className="visually-hidden">Submissions for this assignment</caption>
                  <thead>
                    <tr>
                      <th scope="col">Student</th>
                      <th scope="col">Submission</th>
                      <th scope="col">Job</th>
                      <th scope="col">Open</th>
                    </tr>
                  </thead>
                  <tbody>
                    {submissionsState.state === 'ok' && submissionsState.data.length > 0 ? (
                      submissionsState.data.map((submission) => {
                        const job = jobsBySubmission.get(submission.id)
                        return (
                          <tr key={submission.id}>
                            <td>{submission.student_ref}</td>
                            <td className="mono">{submission.status}</td>
                            <td>
                              <span className="chip app-chip" data-tone={job?.error_code ? 'attention' : 'neutral'}>
                                {job ? job.state : 'No job'}
                              </span>
                            </td>
                            <td>
                              <Link
                                className="btn btn--small btn--outline"
                                to="/submissions/$submissionId"
                                params={{ submissionId: submission.id }}
                              >
                                Review
                              </Link>
                            </td>
                          </tr>
                        )
                      })
                    ) : (
                      <tr>
                        <td colSpan={4} className="data-table__empty">
                          No submissions yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </Panel>
          </div>
        ) : null}
      </DataState>

      {assignmentState.state === 'ok' && !blueprint && !approvedScheme ? (
        <StatePanel
          tone="empty"
          title="This assignment has no paper attached yet"
          capability="PUT /api/v1/exams/{id}/blueprint"
        >
          <p>
            Upload and approve the mark scheme, extract the blueprint, review the question marks
            and approve it. Marking is refused until both are approved.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

import { useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { Assignment, Blueprint, Exam, SchemeVersion } from '../lib/api/types'
import { assignmentService, examService } from '../lib/services'

export const Route = createFileRoute('/_app/assignments')({
  component: Assignments,
})

function Assignments() {
  const session = useEngineSession()
  const [list, reloadList] = useResource<Assignment[]>(
    session.tenantId ?? 'none',
    session.tenantId
      ? (signal) => assignmentService.list(session.tenantId!, { token: session.token, signal })
      : null,
  )
  const [exams, reloadExams] = useResource<Exam[]>(
    'exams',
    session.token ? (signal) => examService.list({ token: session.token, signal }) : null,
  )

  const [examTitle, setExamTitle] = useState('')
  const [examId, setExamId] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  const [blueprint] = useResource<Blueprint>(
    examId,
    examId && session.token
      ? (signal) => examService.blueprint(examId, { token: session.token, signal })
      : null,
  )
  const [schemes] = useResource<SchemeVersion[]>(
    examId,
    examId && session.token
      ? (signal) => examService.schemeVersions(examId, { token: session.token, signal })
      : null,
  )

  const approvedScheme =
    schemes.state === 'ok' ? schemes.data.find((version) => version.status === 'APPROVED') : undefined
  const approvedBlueprint = blueprint.state === 'ok' && blueprint.data.status === 'APPROVED'

  async function createExam(event: React.FormEvent) {
    event.preventDefault()
    if (!examTitle.trim() || !session.token) return
    setBusy(true)
    setMessage(null)
    const result = await examService.create({ title: examTitle.trim() }, { token: session.token })
    setBusy(false)
    if (result.status === 'ok') {
      setExamTitle('')
      setExamId(result.data.id)
      reloadExams()
    } else {
      setMessage(result.reason)
    }
  }

  async function createAssignment(event: React.FormEvent) {
    event.preventDefault()
    if (!session.token || !examId || !name.trim()) return
    if (blueprint.state !== 'ok' || !approvedBlueprint || !approvedScheme) {
      setMessage('An approved blueprint and an approved mark scheme are both required.')
      return
    }
    setBusy(true)
    setMessage(null)
    const result = await assignmentService.create(
      {
        exam_id: examId,
        blueprint_version_id: blueprint.data.id,
        scheme_version_id: approvedScheme.id,
        name: name.trim(),
      },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setName('')
      reloadList()
    } else {
      setMessage(result.reason)
    }
  }

  return (
    <div className="app-stack">
      <Panel title="New assignment" note="Needs an approved blueprint and scheme">
        <form className="app-form" onSubmit={createAssignment}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="assignment-exam">
              Exam
            </label>
            <select
              id="assignment-exam"
              className="app-input"
              value={examId}
              onChange={(event) => setExamId(event.target.value)}
              required
            >
              <option value="">Select an exam…</option>
              {exams.state === 'ok'
                ? exams.data.map((exam) => (
                    <option key={exam.id} value={exam.id}>
                      {exam.title}
                    </option>
                  ))
                : null}
            </select>
            {exams.state === 'ok' && exams.data.length === 0 ? (
              <p className="app-hint">
                No exams yet. Create one below, then upload its scheme and extract a blueprint
                from the assignment record.
              </p>
            ) : null}
          </div>

          {examId ? (
            <p className="app-hint mono">
              Blueprint:{' '}
              {blueprint.state === 'ok'
                ? `${blueprint.data.status} v${blueprint.data.version}`
                : 'not extracted'}{' '}
              · Scheme:{' '}
              {schemes.state === 'ok'
                ? schemes.data.length
                  ? `${schemes.data.length} version(s), ${approvedScheme ? 'approved' : 'none approved'}`
                  : 'none uploaded'
                : 'not loaded'}
            </p>
          ) : null}

          <div className="app-form__row">
            <label className="app-form__label" htmlFor="assignment-name">
              Assignment name
            </label>
            <input
              id="assignment-name"
              className="app-input"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={300}
              required
            />
          </div>

          {message ? <p className="app-form__error">{message}</p> : null}

          <div className="app-inline-actions">
            <button
              type="submit"
              className="btn btn--small btn--primary"
              disabled={busy || !approvedBlueprint || !approvedScheme || !name.trim()}
            >
              {busy ? 'Creating…' : 'Create assignment'}
            </button>
            <button
              type="button"
              className="btn btn--small btn--outline"
              onClick={reloadList}
            >
              Refresh list
            </button>
          </div>
        </form>

        <form className="app-form app-form--inline" onSubmit={createExam}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="exam-title">
              Create an exam
            </label>
            <input
              id="exam-title"
              className="app-input"
              value={examTitle}
              onChange={(event) => setExamTitle(event.target.value)}
              placeholder="e.g. Year 11 Mathematics Paper 1"
              maxLength={300}
            />
          </div>
          <button
            type="submit"
            className="btn btn--small btn--outline"
            disabled={busy || !examTitle.trim()}
          >
            Create exam
          </button>
        </form>
      </Panel>

      <DataState state={list} capability="GET /api/v1/workspaces/{id}/assignments">
        <Panel title="Assignment list" note="One row per cohort assignment">
          <div className="table-scroll">
            <table className="data-table">
              <caption className="visually-hidden">Assignments in this workspace</caption>
              <thead>
                <tr>
                  <th scope="col">Assignment</th>
                  <th scope="col">Review mode</th>
                  <th scope="col">Threshold</th>
                  <th scope="col">Created</th>
                  <th scope="col">Open</th>
                </tr>
              </thead>
              <tbody>
                {list.state === 'ok' && list.data.length > 0 ? (
                  list.data.map((assignment) => (
                    <tr key={assignment.id}>
                      <td>{assignment.name}</td>
                      <td className="mono">{assignment.review_mode}</td>
                      <td className="mono">{Math.round(assignment.completion_threshold * 100)}%</td>
                      <td className="mono">{new Date(assignment.created_at).toLocaleDateString()}</td>
                      <td>
                        <Link
                          className="btn btn--small btn--outline"
                          to="/assignments/$assignmentId"
                          params={{ assignmentId: assignment.id }}
                        >
                          Open
                        </Link>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan={5} className="data-table__empty">
                      No assignments yet. Create an exam, upload and approve its scheme, extract a
                      blueprint, then create the assignment above.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>
      </DataState>
    </div>
  )
}

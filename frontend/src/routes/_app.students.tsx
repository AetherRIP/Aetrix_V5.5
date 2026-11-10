import { useRef, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { DataState } from '../components/app/DataState'
import { Panel } from '../components/app/PageBlocks'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import type { SchoolClass, Student, StudentImportResult } from '../lib/api/types'
import { rosterService } from '../lib/services'

export const Route = createFileRoute('/_app/students')({
  component: Students,
})

function Students() {
  const session = useEngineSession()
  const workspace = session.tenantId

  const [classes, reloadClasses] = useResource<SchoolClass[]>(
    `classes:${workspace ?? 'none'}`,
    workspace
      ? (signal) => rosterService.classes(workspace, { token: session.token, signal })
      : null,
  )
  const [students, reloadStudents] = useResource<Student[]>(
    `students:${workspace ?? 'none'}`,
    workspace
      ? (signal) => rosterService.students(workspace, undefined, {
          token: session.token,
          signal,
        })
      : null,
  )

  const [className, setClassName] = useState('')
  const [yearGroup, setYearGroup] = useState('')
  const [studentRef, setStudentRef] = useState('')
  const [studentName, setStudentName] = useState('')
  const [studentClass, setStudentClass] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [pasted, setPasted] = useState('')
  const [importResult, setImportResult] = useState<StudentImportResult | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  const classRows = classes.state === 'ok' ? classes.data : []
  const studentRows = students.state === 'ok' ? students.data : []
  const classNames = new Map(classRows.map((row) => [row.id, row.name]))

  async function importRoster(event: React.FormEvent) {
    event.preventDefault()
    if (!workspace) return
    const chosen = fileInput.current?.files?.[0]
    const file =
      chosen ??
      (pasted.trim()
        ? new File([pasted], 'pasted-roster.csv', { type: 'text/csv' })
        : null)
    if (!file) {
      setMessage('Choose a CSV file or paste rows before importing.')
      return
    }
    setBusy(true)
    setMessage(null)
    setImportResult(null)
    const result = await rosterService.importStudents(workspace, file, {
      token: session.token,
    })
    setBusy(false)
    if (result.status === 'ok') {
      setImportResult(result.data)
      setPasted('')
      if (fileInput.current) fileInput.current.value = ''
      reloadStudents()
      reloadClasses()
    } else {
      setMessage(result.reason)
    }
  }

  async function createClass(event: React.FormEvent) {
    event.preventDefault()
    if (!workspace || !className.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await rosterService.createClass(
      workspace,
      { name: className.trim(), year_group: yearGroup.trim() || null },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setClassName('')
      setYearGroup('')
      reloadClasses()
    } else {
      setMessage(result.reason)
    }
  }

  async function createStudent(event: React.FormEvent) {
    event.preventDefault()
    if (!workspace || !studentRef.trim()) return
    setBusy(true)
    setMessage(null)
    const result = await rosterService.createStudent(
      workspace,
      {
        student_ref: studentRef.trim(),
        display_name: studentName.trim() || null,
        class_id: studentClass || null,
      },
      { token: session.token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setStudentRef('')
      setStudentName('')
      reloadStudents()
      reloadClasses()
    } else {
      setMessage(result.reason)
    }
  }

  return (
    <div className="app-stack">
      <Panel title="Import roster (CSV)" note="Up to 500 rows · 1 MB">
        <form className="app-form" onSubmit={importRoster}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="roster-file">
              CSV file
            </label>
            <input
              ref={fileInput}
              id="roster-file"
              type="file"
              className="app-input"
              accept=".csv,text/csv"
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="roster-paste">
              Or paste CSV
            </label>
            <textarea
              id="roster-paste"
              className="app-input"
              rows={5}
              value={pasted}
              onChange={(event) => setPasted(event.target.value)}
              placeholder={'student_ref,display_name,class\nS-001,Ada Lovelace,10A'}
            />
          </div>
          <p className="app-hint">
            Required column: student_ref. Optional: display_name and class. A class name that does
            not exist yet is created in this workspace. Every skipped or rejected row is reported
            with its CSV line number.
          </p>
          <div className="app-inline-actions">
            <button type="submit" className="btn btn--small btn--primary" disabled={busy}>
              Import roster
            </button>
          </div>
        </form>

        {importResult ? (
          <div data-testid="import-summary">
            <p className="app-hint">
              {importResult.created} created · {importResult.skipped} skipped ·{' '}
              {importResult.failed} failed · {importResult.classes_created} class(es) created (of{' '}
              {importResult.total_rows} data row(s)).
            </p>
            {importResult.issues.length > 0 ? (
              <div className="table-scroll">
                <table className="data-table">
                  <caption className="visually-hidden">Rows the import did not create</caption>
                  <thead>
                    <tr>
                      <th scope="col">CSV line</th>
                      <th scope="col">Reference</th>
                      <th scope="col">Outcome</th>
                      <th scope="col">Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {importResult.issues.map((issue, index) => (
                      <tr key={`${issue.row}-${index}`}>
                        <td className="mono">{issue.row}</td>
                        <td className="mono">{issue.student_ref ?? '—'}</td>
                        <td>
                          <span
                            className="chip app-chip"
                            data-tone={issue.kind === 'ERROR' ? 'attention' : 'neutral'}
                          >
                            {issue.kind}
                          </span>
                        </td>
                        <td>{issue.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="app-hint">Every data row was created.</p>
            )}
          </div>
        ) : null}
      </Panel>

      <Panel title="New class" note="Workspace-owned teaching group">
        <form className="app-form" onSubmit={createClass}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="class-name">
              Class name
            </label>
            <input
              id="class-name"
              className="app-input"
              value={className}
              onChange={(event) => setClassName(event.target.value)}
              maxLength={200}
              required
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="class-year">
              Year group
            </label>
            <input
              id="class-year"
              className="app-input"
              value={yearGroup}
              onChange={(event) => setYearGroup(event.target.value)}
              maxLength={40}
              placeholder="e.g. Year 10"
            />
          </div>
          <div className="app-inline-actions">
            <button type="submit" className="btn btn--small btn--primary" disabled={busy}>
              Create class
            </button>
          </div>
        </form>
      </Panel>

      <Panel title="Classes" note="Allocated to this workspace">
        <DataState state={classes} capability="GET /api/v1/workspaces/{id}/classes">
          {classRows.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Classes in this workspace</caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Year group</th>
                    <th scope="col">Students</th>
                  </tr>
                </thead>
                <tbody>
                  {classRows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row">{row.name}</th>
                      <td>{row.year_group ?? '—'}</td>
                      <td className="mono">{row.student_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="app-hint">
              No classes yet. A class is a workspace record, not a synced Google Classroom
              course: a Classroom sync lists courses, it does not create workspace classes.
            </p>
          )}
        </DataState>
      </Panel>

      <Panel title="New student" note="Roster entry">
        <form className="app-form" onSubmit={createStudent}>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="student-ref">
              Student reference
            </label>
            <input
              id="student-ref"
              className="app-input"
              value={studentRef}
              onChange={(event) => setStudentRef(event.target.value)}
              maxLength={120}
              required
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="student-name">
              Name (optional)
            </label>
            <input
              id="student-name"
              className="app-input"
              value={studentName}
              onChange={(event) => setStudentName(event.target.value)}
              maxLength={200}
            />
          </div>
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="student-class">
              Class
            </label>
            <select
              id="student-class"
              className="app-input"
              value={studentClass}
              onChange={(event) => setStudentClass(event.target.value)}
            >
              <option value="">Unassigned</option>
              {classRows.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
          <div className="app-inline-actions">
            <button type="submit" className="btn btn--small btn--primary" disabled={busy}>
              Add student
            </button>
          </div>
        </form>
      </Panel>

      <Panel title="Students" note="From the workspace roster">
        <DataState state={students} capability="GET /api/v1/workspaces/{id}/students">
          {studentRows.length > 0 ? (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Students in this workspace</caption>
                <thead>
                  <tr>
                    <th scope="col">Student</th>
                    <th scope="col">Reference</th>
                    <th scope="col">Class</th>
                  </tr>
                </thead>
                <tbody>
                  {studentRows.map((row) => (
                    <tr key={row.id}>
                      <th scope="row">{row.display_name ?? '—'}</th>
                      <td className="mono">{row.student_ref}</td>
                      <td>{row.class_id ? (classNames.get(row.class_id) ?? '—') : 'Unassigned'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="app-hint">
              No students yet. Rosters are added here by the workspace; a Google Classroom
              course sync does not import students.
            </p>
          )}
        </DataState>
      </Panel>

      {message ? <p className="app-form__error">{message}</p> : null}
    </div>
  )
}

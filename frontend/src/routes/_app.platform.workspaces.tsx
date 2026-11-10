import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { EmptyTable, Panel } from '../components/app/PageBlocks'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { useAuth } from '../lib/auth/AuthProvider'
import type { ApiResult, RequestOptions } from '../lib/api/client'
import { announcePlatformOverviewChanged } from '../lib/api/overview'
import {
  allocateClass,
  classroomCapability,
  listAllocations,
  listAvailableClasses,
  listWorkspaceTargets,
  reassignAllocation,
  registerClassroomClass,
  releaseAllocation,
  type Allocation,
  type AllocationPage,
  type AllocationStatus,
  type ClassroomCapability,
  type ClassroomClass,
  type WorkspaceTarget,
} from '../lib/api/allocations'

export const Route = createFileRoute('/_app/platform/workspaces')({
  head: () => ({ meta: [{ title: 'Workspace allocation · Aetrix' }] }),
  component: WorkspaceAllocation,
})

type Read<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

function useRead<T>(
  key: string,
  load: ((options: RequestOptions) => Promise<ApiResult<T>>) | null,
  token: string | null,
): [Read<T>, () => void] {
  const [state, setState] = useState<Read<T>>({ state: 'loading' })
  const [tick, setTick] = useState(0)
  const loadRef = useRef(load)
  loadRef.current = load

  useEffect(() => {
    const current = loadRef.current
    if (!current) {
      setState({ state: 'unavailable', reason: 'Sign in to the engine to read allocations.' })
      return
    }
    const controller = new AbortController()
    let live = true
    setState({ state: 'loading' })
    void current({ token, signal: controller.signal }).then((result) => {
      if (!live) return
      if (result.status === 'ok') setState({ state: 'ok', data: result.data })
      else if (result.status === 'unavailable') setState({ state: 'unavailable', reason: result.reason })
      else setState({ state: 'error', reason: result.reason, code: result.code })
    })
    return () => {
      live = false
      controller.abort()
    }
  }, [key, tick, token])

  return [state, useCallback(() => setTick((value) => value + 1), [])]
}

function stamp(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function noticeFor(label: string, result: ApiResult<unknown>): { tone: 'ok' | 'error'; message: string } {
  if (result.status === 'ok') return { tone: 'ok', message: `${label} succeeded.` }
  return {
    tone: 'error',
    message: `${label} failed: ${result.reason}`,
  }
}

type Action =
  | { kind: 'allocate'; classroom: ClassroomClass }
  | { kind: 'release'; allocation: Allocation }
  | { kind: 'reassign'; allocation: Allocation }

function WorkspaceAllocation() {
  const { session } = useAuth()
  const token = session?.access_token ?? null
  const [status, setStatus] = useState<'ALL' | AllocationStatus>('ALL')
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; message: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [action, setAction] = useState<Action | null>(null)

  const [capability, reloadCapability] = useRead<ClassroomCapability>(
    `classroom-capability:${token ?? 'anonymous'}`,
    token ? (options) => classroomCapability(options) : null,
    token,
  )
  const [workspaces, reloadWorkspaces] = useRead<WorkspaceTarget[]>(
    `classroom-workspaces:${token ?? 'anonymous'}`,
    token ? (options) => listWorkspaceTargets(options) : null,
    token,
  )
  const [available, reloadAvailable] = useRead<ClassroomClass[]>(
    `classroom-available:${token ?? 'anonymous'}:${search}`,
    token ? (options) => listAvailableClasses(search, options) : null,
    token,
  )
  const [allocations, reloadAllocations] = useRead<AllocationPage>(
    `classroom-allocations:${token ?? 'anonymous'}:${status}:${search}`,
    token ? (options) => listAllocations({ status, q: search }, options) : null,
    token,
  )

  const reloadAll = useCallback(() => {
    reloadCapability()
    reloadWorkspaces()
    reloadAvailable()
    reloadAllocations()
  }, [reloadCapability, reloadWorkspaces, reloadAvailable, reloadAllocations])

  const run = async (label: string, operation: () => Promise<ApiResult<unknown>>) => {
    setBusy(label)
    const result = await operation()
    setBusy(null)
    setNotice(noticeFor(label, result))
    if (result.status === 'ok') {
      announcePlatformOverviewChanged()
      setAction(null)
      reloadAll()
    }
    return result.status === 'ok'
  }

  const workspaceRows = workspaces.state === 'ok' ? workspaces.data : []
  const availableRows = available.state === 'ok' ? available.data : []
  const allocationRows = allocations.state === 'ok' ? allocations.data.items : []

  return (
    <div className="app-stack">
      {notice ? (
        <div className="gem-notice" data-tone={notice.tone} role="status">
          {notice.message}
        </div>
      ) : null}

      {capability.state === 'ok' ? (
        <StatePanel
          tone="wip"
          title={
            capability.data.discovery_configured
              ? 'Google Classroom discovery is configured'
              : 'Google Classroom discovery is not configured'
          }
          capability="Google Classroom OAuth and course discovery"
        >
          <p>{capability.data.reason}</p>
          <p>
            Classes below are recorded by an administrator or discovered by a workspace’s
            Classroom sync. Only a synced row is <strong>VERIFIED</strong>; an
            operator-recorded row stays <strong>UNVERIFIED</strong> until Google lists it.
          </p>
        </StatePanel>
      ) : capability.state === 'error' ? (
        <StatePanel tone="error" title={capability.reason} capability="GET /api/v1/admin/allocations/capability">
          <p>Platform authority is required to read or change allocations.</p>
        </StatePanel>
      ) : null}

      <Panel title="Teacher workspaces" note={`${workspaceRows.length} active`}>
        {workspaces.state === 'ok' ? (
          workspaceRows.length === 0 ? (
            <EmptyTable
              columns={['Workspace', 'Teacher', 'Active allocations']}
              caption="Active teacher workspaces"
              note="No active, non-demo workspace exists."
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Active teacher workspaces</caption>
                <thead>
                  <tr>
                    <th scope="col">Workspace</th>
                    <th scope="col">Teacher</th>
                    <th scope="col">Active allocations</th>
                  </tr>
                </thead>
                <tbody>
                  {workspaceRows.map((workspace) => (
                    <tr key={workspace.id}>
                      <td>
                        <span className="data-table__strong">{workspace.name}</span>
                        <span className="gem-footnote mono">{workspace.slug}</span>
                      </td>
                      <td>
                        {workspace.owner_label ?? 'No workspace owner recorded'}
                        {workspace.owner_email ? (
                          <span className="gem-footnote">{workspace.owner_email}</span>
                        ) : null}
                      </td>
                      <td className="mono">{workspace.active_allocations}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <p className="panel-copy">
            {workspaces.state === 'loading' ? 'Reading workspaces…' : workspaces.reason}
          </p>
        )}
      </Panel>

      <Panel title="Available classes" note="Unallocated Classroom courses">
        {available.state === 'ok' ? (
          availableRows.length === 0 ? (
            <EmptyTable
              columns={['Class', 'Course ID', 'Verification', 'Action']}
              caption="Unallocated Google Classroom classes"
              note="No unallocated course is recorded. Use the form below for a course an operator read from Classroom, or ask a workspace owner to run a Classroom sync. Operator-recorded courses stay unverified until Google lists them."
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Unallocated Google Classroom classes</caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Course ID</th>
                    <th scope="col">Verification</th>
                    <th scope="col">Sync</th>
                    <th scope="col">
                      <span className="visually-hidden">Action</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {availableRows.map((classroom) => (
                    <tr key={classroom.id}>
                      <td>
                        <span className="data-table__strong">{classroom.name}</span>
                        {classroom.section ? (
                          <span className="gem-footnote">{classroom.section}</span>
                        ) : null}
                      </td>
                      <td className="mono">{classroom.course_id}</td>
                      <td>
                        <StatusChip tone={classroom.verification === 'VERIFIED' ? 'ok' : 'attention'}>
                          {classroom.verification}
                        </StatusChip>
                      </td>
                      <td className="gem-footnote">
                        {classroom.synced_at ? stamp(classroom.synced_at) : 'Not synced'}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn btn--outline btn--small"
                          onClick={() => setAction({ kind: 'allocate', classroom })}
                          disabled={workspaceRows.length === 0}
                        >
                          Allocate
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <p className="panel-copy">
            {available.state === 'loading' ? 'Reading available classes…' : available.reason}
          </p>
        )}

        <RegisterClassForm
          token={token}
          busy={busy}
          onRegistered={(result) => {
            setNotice(noticeFor('Class record', result))
            if (result.status === 'ok') reloadAll()
          }}
        />
      </Panel>

      <Panel title="Allocation history" note="Released rows are retained">
        <div className="gem-filters">
          <label className="gem-field">
            <span>Status</span>
            <select value={status} onChange={(event) => setStatus(event.target.value as 'ALL' | AllocationStatus)}>
              <option value="ALL">All allocations</option>
              <option value="ACTIVE">Active only</option>
              <option value="RELEASED">Released only</option>
            </select>
          </label>
          <label className="gem-field gem-field--wide">
            <span>Search class, course or workspace</span>
            <input
              value={search}
              maxLength={200}
              placeholder="course id, class or workspace"
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
        </div>

        {allocations.state === 'ok' ? (
          allocationRows.length === 0 ? (
            <EmptyTable
              columns={['Class', 'Workspace', 'Status', 'Allocated', 'Released']}
              caption="Allocation history"
              note="No allocation matches this filter."
            />
          ) : (
            <div className="table-scroll">
              <table className="data-table">
                <caption className="visually-hidden">Classroom allocation history</caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Workspace</th>
                    <th scope="col">Status</th>
                    <th scope="col">Allocated</th>
                    <th scope="col">Released</th>
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {allocationRows.map((allocation) => (
                    <tr key={allocation.id}>
                      <td>
                        <span className="data-table__strong">{allocation.class_name}</span>
                        <span className="gem-footnote mono">{allocation.course_id}</span>
                        <StatusChip tone={allocation.verification === 'VERIFIED' ? 'ok' : 'attention'}>
                          {allocation.verification}
                        </StatusChip>
                      </td>
                      <td>{allocation.workspace_name}</td>
                      <td>
                        <StatusChip tone={allocation.status === 'ACTIVE' ? 'ok' : 'neutral'}>
                          {allocation.status}
                        </StatusChip>
                        {allocation.origin === 'REASSIGN' ? (
                          <span className="gem-footnote">reassigned</span>
                        ) : null}
                      </td>
                      <td>
                        {stamp(allocation.allocated_at)}
                        <span className="gem-footnote">
                          {allocation.allocated_by_label ?? allocation.allocated_by_subject}
                        </span>
                      </td>
                      <td>
                        {allocation.released_at ? stamp(allocation.released_at) : '—'}
                        {allocation.release_reason ? (
                          <span className="gem-footnote">{allocation.release_reason}</span>
                        ) : null}
                      </td>
                      <td>
                        {allocation.status === 'ACTIVE' ? (
                          <div className="gem-actions">
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              onClick={() => setAction({ kind: 'release', allocation })}
                            >
                              Release
                            </button>
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              onClick={() => setAction({ kind: 'reassign', allocation })}
                              disabled={workspaceRows.length < 2}
                              title={
                                workspaceRows.length < 2
                                  ? 'Reassignment needs another active workspace.'
                                  : undefined
                              }
                            >
                              Reassign
                            </button>
                          </div>
                        ) : (
                          <span className="gem-footnote">History only</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <p className="panel-copy">
            {allocations.state === 'loading' ? 'Reading allocation history…' : allocations.reason}
          </p>
        )}
      </Panel>

      {action ? (
        <AllocationActionPanel
          action={action}
          workspaces={workspaceRows}
          busy={busy}
          onCancel={() => setAction(null)}
          onSubmit={async (workspaceId, reason) => {
            if (action.kind === 'allocate') {
              return run('Allocation', () =>
                allocateClass(
                  {
                    classroom_class_id: action.classroom.id,
                    workspace_id: workspaceId,
                    reason,
                  },
                  { token },
                ),
              )
            }
            if (action.kind === 'release') {
              return run('Release', () =>
                releaseAllocation(action.allocation.id, reason, { token }),
              )
            }
            return run('Reassignment', () =>
              reassignAllocation(
                action.allocation.id,
                { workspace_id: workspaceId, reason },
                { token },
              ),
            )
          }}
        />
      ) : null}

      <Panel title="Allocation rules" note="Enforced by the engine">
        <ul className="rule-list">
          <li>A Google Classroom course has at most one ACTIVE allocation.</li>
          <li>The database enforces this with a partial unique index, not the form.</li>
          <li>Reassignment releases the old allocation and creates the new one in one transaction.</li>
          <li>Released rows are retained as history and are never rewritten.</li>
          <li>Only the platform owner or an administrator may allocate, release or reassign.</li>
          <li>Teachers can view their workspace allocations but cannot change them.</li>
          <li>Google Classroom discovery is not configured; recorded classes stay UNVERIFIED.</li>
        </ul>
      </Panel>
    </div>
  )
}

function RegisterClassForm({
  token,
  busy,
  onRegistered,
}: {
  token: string | null
  busy: string | null
  onRegistered: (result: ApiResult<unknown>) => void
}) {
  const [courseId, setCourseId] = useState('')
  const [name, setName] = useState('')
  const [section, setSection] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [attested, setAttested] = useState(false)
  const [localBusy, setLocalBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setLocalBusy(true)
    const result = await registerClassroomClass(
      {
        course_id: courseId.trim(),
        name: name.trim(),
        section: section.trim() || undefined,
        owner_email: ownerEmail.trim() || undefined,
        attested: true,
      },
      { token },
    )
    setLocalBusy(false)
    onRegistered(result)
    if (result.status === 'ok') {
      setCourseId('')
      setName('')
      setSection('')
      setOwnerEmail('')
      setAttested(false)
    }
  }

  return (
    <form className="app-form" onSubmit={submit}>
      <h3 className="gem-add__title">Record a class read from Classroom</h3>
      <p className="panel-copy">
        This does not discover or verify anything. Enter a course you have opened in Google
        Classroom; the record is marked UNVERIFIED until a Classroom sync exists.
      </p>
      <div className="app-form__row">
        <label className="app-form__label" htmlFor="classroom-course-id">
          Google Classroom course ID
        </label>
        <input
          id="classroom-course-id"
          className="app-input"
          value={courseId}
          required
          minLength={3}
          maxLength={200}
          onChange={(event) => setCourseId(event.target.value)}
        />
      </div>
      <div className="app-form__row">
        <label className="app-form__label" htmlFor="classroom-name">
          Class name
        </label>
        <input
          id="classroom-name"
          className="app-input"
          value={name}
          required
          maxLength={300}
          onChange={(event) => setName(event.target.value)}
        />
      </div>
      <div className="app-form__row">
        <label className="app-form__label" htmlFor="classroom-section">
          Section (optional)
        </label>
        <input
          id="classroom-section"
          className="app-input"
          value={section}
          maxLength={200}
          onChange={(event) => setSection(event.target.value)}
        />
      </div>
      <div className="app-form__row">
        <label className="app-form__label" htmlFor="classroom-owner">
          Classroom owner email (optional)
        </label>
        <input
          id="classroom-owner"
          className="app-input"
          type="email"
          value={ownerEmail}
          maxLength={320}
          onChange={(event) => setOwnerEmail(event.target.value)}
        />
      </div>
      <label className="gem-field">
        <span>
          <input
            type="checkbox"
            checked={attested}
            onChange={(event) => setAttested(event.target.checked)}
          />{' '}
          I have read this course from Google Classroom; I am not inventing it.
        </span>
      </label>
      <button
        type="submit"
        className="btn btn--primary"
        disabled={!attested || localBusy || busy === 'Allocation'}
      >
        {localBusy ? 'Recording…' : 'Record class'}
      </button>
    </form>
  )
}

function AllocationActionPanel({
  action,
  workspaces,
  busy,
  onCancel,
  onSubmit,
}: {
  action: Action
  workspaces: WorkspaceTarget[]
  busy: string | null
  onCancel: () => void
  onSubmit: (workspaceId: string, reason: string) => Promise<boolean>
}) {
  const [workspaceId, setWorkspaceId] = useState(
    action.kind === 'reassign'
      ? workspaces.find((row) => row.id !== action.allocation.workspace_id)?.id ?? ''
      : workspaces[0]?.id ?? '',
  )
  const [reason, setReason] = useState('')

  const title =
    action.kind === 'allocate'
      ? `Allocate ${action.classroom.name}`
      : action.kind === 'release'
        ? `Release ${action.allocation.class_name}`
        : `Reassign ${action.allocation.class_name}`

  const options =
    action.kind === 'reassign'
      ? workspaces.filter((row) => row.id !== action.allocation.workspace_id)
      : workspaces

  return (
    <Panel title={title} note="Recorded in the platform audit">
      <form
        className="app-form"
        onSubmit={(event) => {
          event.preventDefault()
          void onSubmit(workspaceId, reason.trim())
        }}
      >
        {action.kind !== 'release' ? (
          <div className="app-form__row">
            <label className="app-form__label" htmlFor="allocation-workspace">
              Teacher workspace
            </label>
            <select
              id="allocation-workspace"
              className="app-input"
              value={workspaceId}
              required
              onChange={(event) => setWorkspaceId(event.target.value)}
            >
              <option value="">Choose a workspace</option>
              {options.map((workspace) => (
                <option key={workspace.id} value={workspace.id}>
                  {workspace.name}
                  {workspace.owner_label ? ` — ${workspace.owner_label}` : ''}
                </option>
              ))}
            </select>
          </div>
        ) : null}
        <div className="app-form__row">
          <label className="app-form__label" htmlFor="allocation-reason">
            {action.kind === 'reassign' ? 'Reason (required)' : 'Reason (optional)'}
          </label>
          <input
            id="allocation-reason"
            className="app-input"
            value={reason}
            maxLength={500}
            required={action.kind === 'reassign'}
            minLength={action.kind === 'reassign' ? 3 : undefined}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
        <div className="gem-actions">
          <button
            type="submit"
            className="btn btn--primary"
            disabled={
              busy !== null ||
              (action.kind !== 'release' && !workspaceId) ||
              (action.kind === 'reassign' && reason.trim().length < 3)
            }
          >
            {busy ?? (action.kind === 'release' ? 'Release allocation' : 'Confirm')}
          </button>
          <button type="button" className="btn btn--outline" onClick={onCancel} disabled={busy !== null}>
            Cancel
          </button>
        </div>
      </form>
    </Panel>
  )
}

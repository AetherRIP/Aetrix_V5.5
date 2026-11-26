import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { StepList } from '../components/app/PageBlocks'
import { ClassStaff } from '../components/app/ClassStaff'
import { useAuth } from '../lib/auth/AuthProvider'
import { can, readRole, ROLE_META } from '../lib/auth/roles'
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
  head: () => ({ meta: [{ title: 'Workspaces · Aetrix' }] }),
  component: Workspaces,
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

function classCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'class' : 'classes'}`
}

type Notice = { tone: 'ok' | 'error'; message: string }
type Outcome = {
  title: string
  body: string
  workspaceId?: string
}
type WizardState = { classroom: ClassroomClass | null; workspaceId: string | null }

/**
 * Workspaces are the unit an administrator actually manages: every Classroom
 * class belongs to exactly one, and that workspace's members are the people who
 * can work in it. The screen is ordered by that task, not by database table:
 * orientation, workspaces, classes waiting for a workspace, then history.
 */
function Workspaces() {
  const { session, user } = useAuth()
  const token = session?.access_token ?? null
  const accountRole = readRole(user)
  const canAllocate = accountRole ? can(accountRole, 'platform.allocations.manage') : true

  const [historyStatus, setHistoryStatus] = useState<'ALL' | AllocationStatus>('ALL')
  const [historySearch, setHistorySearch] = useState('')
  const [notice, setNotice] = useState<Notice | null>(null)
  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [dialogError, setDialogError] = useState<string | null>(null)
  const [wizard, setWizard] = useState<WizardState | null>(null)
  const [releaseTarget, setReleaseTarget] = useState<Allocation | null>(null)
  const [moveTarget, setMoveTarget] = useState<Allocation | null>(null)

  const [capability, reloadCapability] = useRead<ClassroomCapability>(
    `ws-capability:${token ?? 'anonymous'}`,
    token ? (options) => classroomCapability(options) : null,
    token,
  )
  const [workspaces, reloadWorkspaces] = useRead<WorkspaceTarget[]>(
    `ws-workspaces:${token ?? 'anonymous'}`,
    token ? (options) => listWorkspaceTargets(options) : null,
    token,
  )
  const [available, reloadAvailable] = useRead<ClassroomClass[]>(
    `ws-available:${token ?? 'anonymous'}`,
    token ? (options) => listAvailableClasses('', options) : null,
    token,
  )
  const [active, reloadActive] = useRead<AllocationPage>(
    `ws-active:${token ?? 'anonymous'}`,
    token ? (options) => listAllocations({ status: 'ACTIVE', limit: 200 }, options) : null,
    token,
  )
  const [history, reloadHistory] = useRead<AllocationPage>(
    `ws-history:${token ?? 'anonymous'}:${historyStatus}:${historySearch}`,
    token
      ? (options) =>
          listAllocations({ status: historyStatus, q: historySearch, limit: 50 }, options)
      : null,
    token,
  )

  const permissionDenied =
    (workspaces.state === 'error' && workspaces.code === 403) ||
    (capability.state === 'error' && capability.code === 403)
  const allowAllocation = canAllocate && !permissionDenied

  const reloadAll = useCallback(() => {
    reloadCapability()
    reloadWorkspaces()
    reloadAvailable()
    reloadActive()
    reloadHistory()
  }, [reloadCapability, reloadWorkspaces, reloadAvailable, reloadActive, reloadHistory])

  const workspaceRows = workspaces.state === 'ok' ? workspaces.data : []
  const classRows = available.state === 'ok' ? available.data : []
  const activeRows = active.state === 'ok' ? active.data.items : []
  const historyRows = history.state === 'ok' ? history.data.items : []
  const discoveryConfigured =
    capability.state === 'ok' ? capability.data.discovery_configured : null

  const classesByWorkspace = new Map<string, Allocation[]>()
  for (const allocation of activeRows) {
    const current = classesByWorkspace.get(allocation.workspace_id) ?? []
    current.push(allocation)
    classesByWorkspace.set(allocation.workspace_id, current)
  }

  const workspaceFor = (id: string) => workspaceRows.find((row) => row.id === id) ?? null

  function openWizard(seed?: Partial<WizardState>) {
    setDialogError(null)
    setOutcome(null)
    setWizard({ classroom: seed?.classroom ?? null, workspaceId: seed?.workspaceId ?? null })
  }

  async function run(
    label: string,
    operation: () => Promise<ApiResult<unknown>>,
  ): Promise<ApiResult<unknown>> {
    setBusy(label)
    setDialogError(null)
    const result = await operation()
    setBusy(null)
    if (result.status === 'ok') {
      setNotice(null)
      announcePlatformOverviewChanged()
      setWizard(null)
      setReleaseTarget(null)
      setMoveTarget(null)
      reloadAll()
    } else {
      setDialogError(result.reason)
      setNotice({ tone: 'error', message: `${label} failed: ${result.reason}` })
    }
    return result
  }

  async function allocate(workspaceId: string, reason: string) {
    const classroom = wizard?.classroom
    if (!classroom) {
      setDialogError('Choose a Google Classroom class before allocating.')
      return
    }
    // The workspace list can be refreshed while the dialog is open; the id is what
    // the engine validates, so a stale list must not swallow the request silently.
    const workspace = workspaceFor(workspaceId)
    const result = await run('Allocation', () =>
      allocateClass(
        {
          classroom_class_id: classroom.id,
          workspace_id: workspaceId,
          reason: reason.trim() || undefined,
        },
        { token },
      ),
    )
    if (result.status === 'ok') {
      setOutcome({
        title: 'Class allocated',
        body: workspace
          ? `“${classroom.name}” now belongs to ${workspace.name}. ` +
            (workspace.owner_label
              ? `${workspace.owner_label} can open it from Google Classroom and start creating assignments.`
              : 'Its workspace members can open it from Google Classroom.')
          : `“${classroom.name}” is now attached to the chosen workspace.`,
        workspaceId,
      })
    }
  }

  async function release(reason: string) {
    const allocation = releaseTarget
    if (!allocation) return
    const result = await run('Release', () =>
      releaseAllocation(allocation.id, reason.trim(), { token }),
    )
    if (result.status === 'ok') {
      setOutcome({
        title: 'Allocation released',
        body:
          `“${allocation.class_name}” is no longer part of ${allocation.workspace_name}. ` +
          'Its teachers lose access in Aetrix, and the class is ready to allocate again. The released row stays in the history.',
      })
    }
  }

  async function move(workspaceId: string, reason: string) {
    const allocation = moveTarget
    if (!allocation) return
    const workspace = workspaceFor(workspaceId)
    const result = await run('Reassignment', () =>
      reassignAllocation(allocation.id, { workspace_id: workspaceId, reason: reason.trim() }, { token }),
    )
    if (result.status === 'ok') {
      setOutcome({
        title: 'Class moved',
        body:
          `“${allocation.class_name}” now belongs to ${workspace?.name ?? 'the new workspace'}. ` +
          `${allocation.workspace_name} no longer has access. Both rows stay in the history.`,
        workspaceId,
      })
    }
  }

  const roleLabel = accountRole ? ROLE_META[accountRole].label : 'Platform administration'

  return (
    <div className="app-stack ws-page">
      {notice ? (
        <div
          className="gem-notice"
          data-tone={notice.tone}
          role={notice.tone === 'error' ? 'alert' : 'status'}
        >
          {notice.message}
        </div>
      ) : null}

      {outcome ? (
        <section className="ws-outcome" role="status" aria-live="polite" aria-label={outcome.title}>
          <div className="ws-outcome__copy">
            <p className="ws-kicker mono">Done</p>
            <h2 className="ws-outcome__title">{outcome.title}</h2>
            <p className="ws-outcome__body">{outcome.body}</p>
          </div>
          <div className="ws-outcome__actions">
            {allowAllocation ? (
              <button type="button" className="btn btn--small btn--primary" onClick={() => openWizard()}>
                Allocate another class
              </button>
            ) : null}
            {outcome.workspaceId ? (
              <a className="btn btn--small btn--outline" href={`#workspace-${outcome.workspaceId}`}>
                View the workspace
              </a>
            ) : null}
            <Link className="btn btn--small btn--outline" to="/platform/classroom">
              All Classroom courses
            </Link>
            <button type="button" className="btn btn--small" onClick={() => setOutcome(null)}>
              Dismiss
            </button>
          </div>
        </section>
      ) : null}

      <section className="ws-orient" aria-labelledby="ws-orient-title">
        <div className="ws-orient__copy">
          <p className="ws-kicker mono">Start here</p>
          <h2 className="ws-orient__title" id="ws-orient-title">
            A workspace is one teacher team’s area in Aetrix
          </h2>
          <p>
            Workspaces organise your classes, teachers and assignments. A Google Classroom class
            is not visible to a teacher until an administrator allocates it to a workspace.
          </p>
          <p className="ws-orient__access">
            <strong>Your access:</strong> {roleLabel}.{' '}
            {allowAllocation
              ? 'You can allocate a class, release it, or move it to another workspace.'
              : canAllocate
                ? 'The engine did not grant allocation authority, so the actions are withheld.'
                : 'You can see how classes are allocated, but this account cannot change them.'}
          </p>
        </div>
        <StepList
          steps={[
            {
              title: 'A class exists in Google Classroom',
              body: 'Aetrix can see it through the central Google account, but no teacher has it yet.',
            },
            {
              title: 'You allocate it to a workspace',
              body: 'The class becomes available to that workspace’s members. One class belongs to one workspace at a time.',
            },
            {
              title: 'The teacher works in Aetrix',
              body: 'Assignments are created here and published to Classroom; submissions come back here.',
            },
          ]}
        />
      </section>

      <section className="app-card ws-section" aria-labelledby="ws-list-title">
        <div className="ws-section__head">
          <div>
            <h2 className="app-card__title" id="ws-list-title">
              Workspaces
            </h2>
            <p className="ws-section__lede">
              Every workspace below already exists. Opening one shows its classes; allocation adds
              another class to it.
            </p>
          </div>
          <span className="app-card__note mono">
            {workspaces.state === 'ok'
              ? `${workspaceRows.length} active`
              : workspaces.state === 'loading'
                ? 'Reading…'
                : 'Not reported'}
          </span>
        </div>

        <div className="ws-toolbar">
          <p>
            {canAllocate
              ? 'Choose a class that is not assigned yet, then choose the workspace whose teacher should have it.'
              : 'Allocation is managed by a platform owner or administrator.'}
          </p>
          <div className="ws-toolbar__actions">
            <button
              type="button"
              className="btn btn--small btn--outline"
              onClick={reloadAll}
              disabled={busy !== null}
            >
              Refresh
            </button>
            {allowAllocation ? (
              <button
                type="button"
                className="btn btn--small btn--primary"
                onClick={() => openWizard()}
                disabled={workspaces.state !== 'ok' || workspaceRows.length === 0}
                title={
                  workspaces.state !== 'ok'
                    ? 'Wait for the workspace list to load.'
                    : workspaceRows.length === 0
                      ? 'A workspace must exist before a class can be allocated to it.'
                      : undefined
                }
              >
                Allocate a Classroom class
              </button>
            ) : null}
          </div>
        </div>

        {workspaces.state === 'loading' ? (
          <div className="ws-grid" aria-busy="true" aria-live="polite">
            <p className="ws-section__loading">Reading workspaces…</p>
          </div>
        ) : workspaces.state === 'ok' ? (
          workspaceRows.length === 0 ? (
            <div className="ws-empty ws-empty--page">
              <strong>No workspace exists yet</strong>
              <p>
                A workspace is created during platform provisioning, not by allocating a class.
                This build has no screen that creates one. Once a workspace exists, return here to
                attach its first Google Classroom class.
              </p>
            </div>
          ) : (
            <div className="ws-grid">
              {workspaceRows.map((workspace) => {
                const classes = classesByWorkspace.get(workspace.id) ?? []
                return (
                  <article
                    className="ws-card"
                    id={`workspace-${workspace.id}`}
                    key={workspace.id}
                    aria-labelledby={`workspace-${workspace.id}-name`}
                  >
                    <header className="ws-card__head">
                      <div className="ws-card__identity">
                        <p className="ws-kicker mono">Workspace</p>
                        <h3 className="ws-card__name" id={`workspace-${workspace.id}-name`}>
                          {workspace.name}
                        </h3>
                      </div>
                      <StatusChip tone={workspace.active_allocations > 0 ? 'ok' : 'neutral'}>
                        {classCountLabel(workspace.active_allocations)}
                      </StatusChip>
                    </header>

                    <dl className="ws-card__facts">
                      <div>
                        <dt>Teacher</dt>
                        <dd>
                          {workspace.owner_label ?? 'No workspace owner recorded'}
                          {workspace.owner_email ? <small>{workspace.owner_email}</small> : null}
                        </dd>
                      </div>
                      <div>
                        <dt>Workspace reference</dt>
                        <dd className="mono">{workspace.slug}</dd>
                      </div>
                    </dl>

                    <div className="ws-card__classes">
                      <p className="ws-kicker mono">Allocated classes</p>
                      {classes.length === 0 ? (
                        <p className="ws-card__none">
                          No class is allocated yet. This workspace’s teacher has no class to work
                          in until you allocate one.
                        </p>
                      ) : (
                        <ul className="ws-classes">
                          {classes.map((allocation) => (
                            <li key={allocation.id}>
                              <div className="ws-classes__copy">
                                <span className="ws-classes__name">{allocation.class_name}</span>
                                <span className="ws-classes__meta mono">
                                  {allocation.course_id}
                                  {allocation.class_section ? ` · ${allocation.class_section}` : ''}
                                </span>
                                <StatusChip
                                  tone={allocation.verification === 'VERIFIED' ? 'ok' : 'attention'}
                                >
                                  {allocation.verification}
                                </StatusChip>
                              </div>
                              <ClassStaff
                                allocation={allocation}
                                workspace={workspace}
                                token={token}
                                notify={(tone, message) => setNotice({ tone, message })}
                              />
                              {allowAllocation ? (
                                <div className="ws-classes__actions">
                                  <button
                                    type="button"
                                    className="btn btn--small btn--outline"
                                    onClick={() => {
                                      setDialogError(null)
                                      setReleaseTarget(allocation)
                                    }}
                                    aria-label={`Release ${allocation.class_name} from ${workspace.name}`}
                                    disabled={busy !== null}
                                  >
                                    Release…
                                  </button>
                                </div>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <footer className="ws-card__actions">
                      {allowAllocation ? (
                        <button
                          type="button"
                          className="btn btn--small btn--primary"
                          onClick={() => openWizard({ workspaceId: workspace.id })}
                        >
                          Allocate a class here
                        </button>
                      ) : null}
                      <Link className="btn btn--small btn--outline" to="/platform/classroom">
                        All Classroom courses
                      </Link>
                    </footer>
                  </article>
                )
              })}
            </div>
          )
        ) : (
          <StatePanel
            tone={workspaces.state === 'unavailable' ? 'wip' : 'error'}
            title={
              workspaces.state === 'error' && workspaces.code === 403
                ? 'Platform authority is required to read workspaces'
                : workspaces.reason
            }
            capability="GET /api/v1/admin/allocations/workspaces"
          >
            <p>
              No workspace rows are shown until the engine answers. Nothing on this page is
              inferred from earlier loads.
            </p>
            <button type="button" className="btn btn--small btn--outline" onClick={reloadWorkspaces}>
              Try again
            </button>
          </StatePanel>
        )}
      </section>

      <section className="app-card ws-section" aria-labelledby="ws-ready-title">
        <div className="ws-section__head">
          <div>
            <h2 className="app-card__title" id="ws-ready-title">
              Classes ready to allocate
            </h2>
            <p className="ws-section__lede">
              These Google Classroom classes are not attached to a workspace. Allocating one gives
              its teachers access immediately.
            </p>
          </div>
          <span className="app-card__note mono">
            {available.state === 'ok' ? `${classRows.length} available` : 'Not reported'}
          </span>
        </div>

        {capability.state === 'ok' ? (
          <p
            className="ws-connection"
            data-tone={capability.data.discovery_configured ? 'ok' : 'attention'}
          >
            <span className="ws-connection__dot" aria-hidden="true" />
            <span>
              <strong>Google Classroom discovery</strong>{' '}
              {capability.data.discovery_configured
                ? 'is configured. A sync lists the courses the central account can see.'
                : 'is not configured. Classes recorded by hand stay UNVERIFIED until a Classroom sync lists them.'}
            </span>
            <Link to="/platform/classroom">Classroom setup</Link>
          </p>
        ) : capability.state === 'error' ? (
          <p className="ws-connection" data-tone="attention">
            <span className="ws-connection__dot" aria-hidden="true" />
            <span>
              Google Classroom status could not be read: {capability.reason}
            </span>
            <button type="button" className="ws-linkish" onClick={reloadCapability}>
              Try again
            </button>
          </p>
        ) : null}

        {available.state === 'loading' ? (
          <p className="ws-section__loading">Reading Classroom classes…</p>
        ) : available.state === 'ok' ? (
          classRows.length === 0 ? (
            <div className="ws-empty">
              <strong>No unallocated class is recorded</strong>
              <p>
                Every recorded class is already in a workspace, or none has been read from
                Classroom yet. Open Google Classroom to run a course sync, or use the manual record
                below for a course you have opened yourself.
              </p>
              <Link className="btn btn--small btn--outline" to="/platform/classroom">
                Open Google Classroom
              </Link>
            </div>
          ) : (
            <ul className="ws-ready">
              {classRows.map((classroom) => (
                <li className="ws-ready__row" key={classroom.id}>
                  <div className="ws-ready__copy">
                    <span className="ws-ready__name">{classroom.name}</span>
                    <span className="ws-ready__meta">
                      {classroom.section ? `${classroom.section} · ` : ''}
                      Course <span className="mono">{classroom.course_id}</span> ·{' '}
                      {classroom.synced_at
                        ? `synced ${stamp(classroom.synced_at)}`
                        : 'not synced from Google'}
                    </span>
                  </div>
                  <StatusChip tone={classroom.verification === 'VERIFIED' ? 'ok' : 'attention'}>
                    {classroom.verification}
                  </StatusChip>
                  {allowAllocation ? (
                    <button
                      type="button"
                      className="btn btn--small btn--primary"
                      onClick={() => openWizard({ classroom })}
                      disabled={workspaceRows.length === 0}
                      title={
                        workspaceRows.length === 0
                          ? 'A workspace must exist before this class can be allocated.'
                          : undefined
                      }
                    >
                      Allocate…
                    </button>
                  ) : null}
                </li>
              ))}
            </ul>
          )
        ) : (
          <div className="ws-empty">
            <strong>Classroom classes are unavailable</strong>
            <p>
              {available.state === 'unavailable'
                ? available.reason
                : available.state === 'error'
                  ? available.reason
                  : 'The engine has not answered.'}
            </p>
            <button type="button" className="btn btn--small btn--outline" onClick={reloadAvailable}>
              Try again
            </button>
          </div>
        )}

        {allowAllocation ? (
          <details className="ws-manual">
            <summary>Record a class that is not in this list</summary>
            <p className="ws-manual__note">
              This records the course; it does not discover or verify it. Use it only for a course
              you have opened in Google Classroom yourself.
            </p>
            <RegisterClassForm
              token={token}
              busy={busy}
              onRegistered={(result) => {
                setNotice(noticeFor('Class record', result))
                if (result.status === 'ok') reloadAvailable()
              }}
            />
          </details>
        ) : null}
      </section>

      <section className="app-card ws-section" aria-labelledby="ws-history-title">
        <div className="ws-section__head">
          <div>
            <h2 className="app-card__title" id="ws-history-title">
              Allocation history
            </h2>
            <p className="ws-section__lede">
              Every allocation is recorded. Releasing or moving a class never deletes the earlier
              row.
            </p>
          </div>
          <span className="app-card__note mono">Released rows are kept</span>
        </div>

        <div className="gem-filters ws-filters">
          <label className="gem-field">
            <span>Status</span>
            <select
              value={historyStatus}
              onChange={(event) => setHistoryStatus(event.target.value as 'ALL' | AllocationStatus)}
            >
              <option value="ALL">All allocations</option>
              <option value="ACTIVE">Active only</option>
              <option value="RELEASED">Released only</option>
            </select>
          </label>
          <label className="gem-field gem-field--wide">
            <span>Search history</span>
            <input
              value={historySearch}
              maxLength={200}
              placeholder="class, course id or workspace"
              onChange={(event) => setHistorySearch(event.target.value)}
            />
          </label>
        </div>

        {history.state === 'ok' ? (
          historyRows.length === 0 ? (
            <div className="ws-empty">
              <strong>No allocation matches this filter</strong>
              <p>
                Clear the search or choose “All allocations”. This table only shows rows the engine
                returned.
              </p>
            </div>
          ) : (
            <div className="table-scroll">
              <table className="data-table ws-history-table">
                <caption className="visually-hidden">Classroom allocation history</caption>
                <thead>
                  <tr>
                    <th scope="col">Class</th>
                    <th scope="col">Workspace</th>
                    <th scope="col">Status</th>
                    <th scope="col">When</th>
                    <th scope="col">
                      <span className="visually-hidden">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {historyRows.map((allocation) => (
                    <tr key={allocation.id}>
                      <td data-label="Class">
                        <span className="data-table__strong">{allocation.class_name}</span>
                        <span className="gem-footnote mono">
                          {allocation.course_id}
                          {allocation.class_section ? ` · ${allocation.class_section}` : ''}
                        </span>
                        <StatusChip
                          tone={allocation.verification === 'VERIFIED' ? 'ok' : 'attention'}
                        >
                          {allocation.verification}
                        </StatusChip>
                      </td>
                      <td data-label="Workspace">{allocation.workspace_name}</td>
                      <td data-label="Status">
                        <StatusChip tone={allocation.status === 'ACTIVE' ? 'ok' : 'neutral'}>
                          {allocation.status}
                        </StatusChip>
                        {allocation.origin === 'REASSIGN' ? (
                          <span className="gem-footnote">moved here</span>
                        ) : null}
                      </td>
                      <td data-label="When">
                        <span className="ws-history__stamp">
                          Allocated {stamp(allocation.allocated_at)}
                        </span>
                        <span className="gem-footnote">
                          {allocation.allocated_by_label ?? allocation.allocated_by_subject}
                        </span>
                        {allocation.released_at ? (
                          <span className="gem-footnote">
                            Released {stamp(allocation.released_at)}
                            {allocation.release_reason ? ` · ${allocation.release_reason}` : ''}
                          </span>
                        ) : null}
                      </td>
                      <td data-label="Actions">
                        {allocation.status === 'ACTIVE' && allowAllocation ? (
                          <div className="gem-actions">
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              onClick={() => {
                                setDialogError(null)
                                setReleaseTarget(allocation)
                              }}
                            >
                              Release…
                            </button>
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              onClick={() => {
                                setDialogError(null)
                                setMoveTarget(allocation)
                              }}
                              disabled={workspaceRows.length < 2}
                              title={
                                workspaceRows.length < 2
                                  ? 'Moving a class needs another workspace to move it to.'
                                  : undefined
                              }
                            >
                              Move…
                            </button>
                          </div>
                        ) : (
                          <span className="gem-footnote">
                            {allocation.status === 'ACTIVE' ? 'Read-only' : 'History'}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : (
          <div className="ws-empty">
            <strong>
              {history.state === 'loading' ? 'Reading allocation history…' : 'History unavailable'}
            </strong>
            {history.state !== 'loading' ? (
              <>
                <p>{history.reason}</p>
                <button type="button" className="btn btn--small btn--outline" onClick={reloadHistory}>
                  Try again
                </button>
              </>
            ) : null}
          </div>
        )}
      </section>

      <section className="app-card ws-section" aria-labelledby="ws-how-title">
        <h2 className="app-card__title" id="ws-how-title">
          What allocation does — and does not do
        </h2>
        <ul className="ws-rules">
          <li>
            It attaches the class to one workspace. Every member of that workspace can then open
            the class in Aetrix.
          </li>
          <li>
            A class has at most one active workspace. Moving it releases the old allocation and
            creates the new one together.
          </li>
          <li>
            Releasing returns the class to “ready to allocate” and keeps both rows in the history.
          </li>
          <li>
            It does not invite anyone to Google Classroom or change its teachers. Those stay with
            the central Google account and Classroom itself.
          </li>
        </ul>
      </section>

      {wizard ? (
        <AllocationDialog
          classes={classRows}
          classesState={available.state}
          classesReason={
            available.state === 'unavailable' || available.state === 'error'
              ? available.reason
              : null
          }
          workspaces={workspaceRows}
          workspacesState={workspaces.state}
          discoveryConfigured={discoveryConfigured}
          initialClass={wizard.classroom}
          initialWorkspaceId={wizard.workspaceId}
          busy={busy === 'Allocation'}
          error={dialogError}
          onClose={() => {
            if (busy) return
            setWizard(null)
            setDialogError(null)
          }}
          onSubmit={(workspaceId, reason) => void allocate(workspaceId, reason)}
        />
      ) : null}

      {releaseTarget ? (
        <ReleaseDialog
          allocation={releaseTarget}
          busy={busy === 'Release'}
          error={dialogError}
          onClose={() => {
            if (busy) return
            setReleaseTarget(null)
            setDialogError(null)
          }}
          onSubmit={(reason) => void release(reason)}
        />
      ) : null}

      {moveTarget ? (
        <MoveDialog
          allocation={moveTarget}
          workspaces={workspaceRows.filter((row) => row.id !== moveTarget.workspace_id)}
          busy={busy === 'Reassignment'}
          error={dialogError}
          onClose={() => {
            if (busy) return
            setMoveTarget(null)
            setDialogError(null)
          }}
          onSubmit={(workspaceId, reason) => void move(workspaceId, reason)}
        />
      ) : null}
    </div>
  )
}

function useDialogFocus() {
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const panel = panelRef.current
    const focusable = () =>
      Array.from(
        panel?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      )
    panel?.querySelector<HTMLElement>('[data-autofocus]')?.focus()

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault()
        panel?.querySelector<HTMLElement>('[data-dialog-close]')?.click()
        return
      }
      if (event.key !== 'Tab') return
      const items = focusable()
      if (items.length === 0) return
      const first = items[0]
      const last = items[items.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [])

  return panelRef
}

function DialogShell({
  kicker,
  title,
  children,
  role = 'dialog',
  onClose,
  closeDisabled = false,
}: {
  kicker: string
  title: string
  children: ReactNode
  role?: 'dialog' | 'alertdialog'
  onClose: () => void
  closeDisabled?: boolean
}) {
  const panelRef = useDialogFocus()
  const titleId = `ws-dialog-${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`

  return createPortal(
    <div
      className="app-modal"
      onMouseDown={(event) => {
        if (event.currentTarget === event.target && !closeDisabled) onClose()
      }}
    >
      <div
        className="app-modal__panel ws-dialog"
        role={role}
        aria-modal="true"
        aria-labelledby={titleId}
        ref={panelRef}
      >
        <div className="app-modal__head">
          <div>
            <p className="app-modal__kicker">{kicker}</p>
            <h2 className="app-modal__title" id={titleId}>
              {title}
            </h2>
          </div>
          <button
            type="button"
            className="btn btn--small btn--outline"
            onClick={onClose}
            disabled={closeDisabled}
            data-autofocus
            data-dialog-close
          >
            Close
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

function AllocationDialog({
  classes,
  classesState,
  classesReason,
  workspaces,
  workspacesState,
  discoveryConfigured,
  initialClass,
  initialWorkspaceId,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  classes: ClassroomClass[]
  classesState: Read<ClassroomClass[]>['state']
  classesReason: string | null
  workspaces: WorkspaceTarget[]
  workspacesState: Read<WorkspaceTarget[]>['state']
  discoveryConfigured: boolean | null
  initialClass: ClassroomClass | null
  initialWorkspaceId: string | null
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (workspaceId: string, reason: string) => void
}) {
  const [step, setStep] = useState(initialClass ? 1 : 0)
  const [classId, setClassId] = useState(initialClass?.id ?? '')
  const [workspaceId, setWorkspaceId] = useState(initialWorkspaceId ?? '')
  const [reason, setReason] = useState('')
  const [query, setQuery] = useState('')
  const [submitError, setSubmitError] = useState<string | null>(null)

  // The class that opened the wizard may leave the “ready to allocate” list while the
  // dialog is open (allocated in another tab, or by a sync). Falling back to the seed
  // keeps the review step truthful and lets the engine answer with the real conflict,
  // instead of the submit silently doing nothing.
  const selectedClass =
    classes.find((row) => row.id === classId) ??
    (initialClass && initialClass.id === classId ? initialClass : null)
  const selectedWorkspace = workspaces.find((row) => row.id === workspaceId) ?? null
  const needle = query.trim().toLowerCase()
  const visibleClasses = needle
    ? classes.filter(
        (row) =>
          row.name.toLowerCase().includes(needle) ||
          row.course_id.toLowerCase().includes(needle) ||
          (row.section ?? '').toLowerCase().includes(needle),
      )
    : classes

  const canContinue = step === 0 ? Boolean(selectedClass) : step === 1 ? Boolean(selectedWorkspace) : true

  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (step < 2 || busy) return
    if (!classId || !workspaceId) {
      setSubmitError('Choose a class and a workspace before allocating.')
      return
    }
    setSubmitError(null)
    onSubmit(workspaceId, reason)
  }

  return (
    <DialogShell
      kicker="Allocate a Classroom class"
      title={step === 2 ? 'Review the allocation' : 'Attach a class to a workspace'}
      onClose={onClose}
      closeDisabled={busy}
    >
      <ol className="ws-steps" aria-label="Allocation steps">
        {['Choose a class', 'Choose a workspace', 'Review and confirm'].map((label, index) => (
          <li
            key={label}
            data-active={step === index ? '' : undefined}
            data-done={step > index ? '' : undefined}
            aria-current={step === index ? 'step' : undefined}
          >
            <span className="ws-steps__index mono" aria-hidden="true">
              {index + 1}
            </span>
            <span>{label}</span>
          </li>
        ))}
      </ol>

      <form className="ws-dialog__form" onSubmit={submit}>
        {step === 0 ? (
          <>
            <p className="ws-dialog__hint">
              These are classes Google or an administrator recorded, with no active workspace.
              Allocating one does not change anything in Google Classroom.
            </p>
            {classesState === 'loading' ? (
              <p className="ws-section__loading">Reading Classroom classes…</p>
            ) : classesState !== 'ok' ? (
              <div className="ws-empty">
                <strong>Classroom classes are unavailable</strong>
                <p>{classesReason ?? 'The engine did not answer this request.'}</p>
                <Link className="btn btn--small btn--outline" to="/platform/classroom" onClick={onClose}>
                  Open Google Classroom
                </Link>
              </div>
            ) : classes.length === 0 ? (
              <div className="ws-empty">
                <strong>No Classroom class is ready to allocate</strong>
                <p>
                  Every recorded class already belongs to a workspace, or no class has been read
                  from Classroom yet.
                </p>
                <p>
                  {discoveryConfigured === false
                    ? 'Discovery is not configured. Record a class manually from the Workspaces page if you can see it in Google Classroom.'
                    : 'Open Google Classroom to run a course sync, then return here.'}
                </p>
                <Link className="btn btn--small btn--outline" to="/platform/classroom" onClick={onClose}>
                  Open Google Classroom
                </Link>
              </div>
            ) : (
              <>
                {classes.length > 4 ? (
                  <label className="app-form__row">
                    <span className="app-form__label">Find a class</span>
                    <input
                      className="app-input"
                      value={query}
                      onChange={(event) => setQuery(event.target.value)}
                      placeholder="name, section or course id"
                    />
                  </label>
                ) : null}
                <fieldset className="ws-choice">
                  <legend className="visually-hidden">Classes ready to allocate</legend>
                  {visibleClasses.length === 0 ? (
                    <p className="ws-dialog__hint">No class matches “{query}”.</p>
                  ) : null}
                  {visibleClasses.map((classroom) => (
                    <label className="ws-choice__row" key={classroom.id}>
                      <input
                        type="radio"
                        name="classroom-class"
                        value={classroom.id}
                        checked={classId === classroom.id}
                        onChange={() => setClassId(classroom.id)}
                      />
                      <span className="ws-choice__copy">
                        <span className="ws-choice__name">{classroom.name}</span>
                        <span className="ws-choice__meta">
                          {classroom.section ? `${classroom.section} · ` : ''}
                          Course {classroom.course_id}
                          {classroom.synced_at ? ` · synced ${stamp(classroom.synced_at)}` : ' · not synced'}
                        </span>
                      </span>
                      <StatusChip
                        tone={classroom.verification === 'VERIFIED' ? 'ok' : 'attention'}
                      >
                        {classroom.verification}
                      </StatusChip>
                    </label>
                  ))}
                </fieldset>
              </>
            )}
          </>
        ) : null}

        {step === 1 ? (
          <>
            <p className="ws-dialog__hint">
              The workspace’s members will be able to open this class. Choose the teacher team that
              should own it.
            </p>
            {workspacesState !== 'ok' ? (
              <p className="ws-section__loading">Reading workspaces…</p>
            ) : workspaces.length === 0 ? (
              <div className="ws-empty">
                <strong>No workspace exists to receive this class</strong>
                <p>
                  A workspace is created during platform provisioning, not by this screen. Allocate
                  the class once a workspace exists.
                </p>
              </div>
            ) : (
              <fieldset className="ws-choice">
                <legend className="visually-hidden">Workspaces</legend>
                {workspaces.map((workspace) => (
                  <label className="ws-choice__row" key={workspace.id}>
                    <input
                      type="radio"
                      name="workspace"
                      value={workspace.id}
                      checked={workspaceId === workspace.id}
                      onChange={() => setWorkspaceId(workspace.id)}
                    />
                    <span className="ws-choice__copy">
                      <span className="ws-choice__name">{workspace.name}</span>
                      <span className="ws-choice__meta">
                        {workspace.owner_label ?? 'No workspace owner recorded'}
                        {workspace.owner_email ? ` · ${workspace.owner_email}` : ''} ·{' '}
                        {classCountLabel(workspace.active_allocations)} allocated
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
          </>
        ) : null}

        {step === 2 && selectedClass && selectedWorkspace ? (
          <>
            <dl className="ws-review">
              <div>
                <dt>Class</dt>
                <dd>
                  {selectedClass.name}
                  <small className="mono">
                    Course {selectedClass.course_id}
                    {selectedClass.section ? ` · ${selectedClass.section}` : ''}
                  </small>
                </dd>
              </div>
              <div>
                <dt>Verification</dt>
                <dd>
                  <StatusChip
                    tone={selectedClass.verification === 'VERIFIED' ? 'ok' : 'attention'}
                  >
                    {selectedClass.verification}
                  </StatusChip>
                </dd>
              </div>
              <div>
                <dt>Workspace</dt>
                <dd>{selectedWorkspace.name}</dd>
              </div>
              <div>
                <dt>Teacher with access</dt>
                <dd>
                  {selectedWorkspace.owner_label ?? 'No workspace owner recorded'}
                  {selectedWorkspace.owner_email ? (
                    <small>{selectedWorkspace.owner_email}</small>
                  ) : null}
                </dd>
              </div>
            </dl>

            <ul className="ws-consequences">
              <li>
                The class appears for every member of {selectedWorkspace.name}; the workspace owner
                is its teacher.
              </li>
              <li>
                The teacher creates assignments in Aetrix and publishes them to this class.
              </li>
              <li>
                Allocation does not invite or remove Google Classroom teachers, and does not change
                Classroom itself.
              </li>
              <li>The action is written to the platform audit log.</li>
            </ul>

            <label className="app-form__row">
              <span className="app-form__label">Reason (optional)</span>
              <input
                className="app-input"
                value={reason}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
                placeholder="e.g. class moved to this teacher for term 2"
              />
            </label>
          </>
        ) : null}

        {error || submitError ? (
          <p className="app-form__error" role="alert">
            {error ?? submitError}
          </p>
        ) : null}

        <div className="ws-dialog__actions">
          {step > 0 ? (
            <button
              key="back"
              type="button"
              className="btn btn--outline"
              onClick={() => setStep((value) => value - 1)}
              disabled={busy}
            >
              Back
            </button>
          ) : (
            <button
              key="cancel"
              type="button"
              className="btn btn--outline"
              onClick={onClose}
              disabled={busy}
            >
              Cancel
            </button>
          )}
          {/*
           * These two branches must not share a DOM node. React reuses a button
           * at the same position, and changing its type to "submit" during the
           * Continue click lets the browser's default action submit the form a
           * step early, skipping the review. Distinct keys force a new element.
           */}
          {step < 2 ? (
            <button
              key="continue"
              type="button"
              className="btn btn--primary"
              onClick={() => setStep((value) => value + 1)}
              disabled={!canContinue || busy}
            >
              Continue
            </button>
          ) : (
            <button key="allocate" type="submit" className="btn btn--primary" disabled={busy}>
              {busy ? 'Allocating…' : 'Allocate class'}
            </button>
          )}
        </div>
      </form>
    </DialogShell>
  )
}

function ReleaseDialog({
  allocation,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  allocation: Allocation
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (reason: string) => void
}) {
  const [reason, setReason] = useState('')

  return (
    <DialogShell
      kicker="Release allocation"
      title={`Release ${allocation.class_name}?`}
      role="alertdialog"
      onClose={onClose}
      closeDisabled={busy}
    >
      <form
        className="ws-dialog__form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy) onSubmit(reason)
        }}
      >
        <p className="ws-dialog__hint">
          The class will no longer be part of {allocation.workspace_name}. Its teachers lose access
          in Aetrix, and the class becomes available to allocate again.
        </p>
        <ul className="ws-consequences">
          <li>The released allocation stays in the history and is never rewritten.</li>
          <li>Student records already stored in Aetrix are not deleted.</li>
          <li>Nothing changes in Google Classroom.</li>
        </ul>
        <label className="app-form__row">
          <span className="app-form__label">Reason (optional)</span>
          <input
            className="app-input"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder="e.g. timetable change"
          />
        </label>
        {error ? (
          <p className="app-form__error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="ws-dialog__actions">
          <button type="button" className="btn btn--outline" onClick={onClose} disabled={busy}>
            Keep allocation
          </button>
          <button type="submit" className="btn btn--danger" disabled={busy}>
            {busy ? 'Releasing…' : 'Release allocation'}
          </button>
        </div>
      </form>
    </DialogShell>
  )
}

function MoveDialog({
  allocation,
  workspaces,
  busy,
  error,
  onClose,
  onSubmit,
}: {
  allocation: Allocation
  workspaces: WorkspaceTarget[]
  busy: boolean
  error: string | null
  onClose: () => void
  onSubmit: (workspaceId: string, reason: string) => void
}) {
  const [workspaceId, setWorkspaceId] = useState(workspaces[0]?.id ?? '')
  const [reason, setReason] = useState('')
  const destination = workspaces.find((row) => row.id === workspaceId) ?? null

  return (
    <DialogShell
      kicker="Move allocation"
      title={`Move ${allocation.class_name}`}
      onClose={onClose}
      closeDisabled={busy}
    >
      <form
        className="ws-dialog__form"
        onSubmit={(event) => {
          event.preventDefault()
          if (!busy && workspaceId && reason.trim().length >= 3) {
            onSubmit(workspaceId, reason)
          }
        }}
      >
        <p className="ws-dialog__hint">
          Moving releases {allocation.workspace_name} and allocates the class to another workspace
          in one transaction. The old workspace loses access immediately.
        </p>
        <label className="app-form__row">
          <span className="app-form__label">Move to workspace</span>
          <select
            className="app-input"
            value={workspaceId}
            required
            onChange={(event) => setWorkspaceId(event.target.value)}
          >
            <option value="">Choose a workspace</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
                {workspace.owner_label ? ` — ${workspace.owner_label}` : ''}
              </option>
            ))}
          </select>
        </label>
        {destination ? (
          <p className="ws-dialog__hint">
            {destination.name} will own the class; its teacher becomes{' '}
            {destination.owner_label ?? 'the workspace owner'}.
          </p>
        ) : null}
        <label className="app-form__row">
          <span className="app-form__label">Reason (required)</span>
          <input
            className="app-input"
            value={reason}
            required
            minLength={3}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Why is this class moving?"
          />
        </label>
        {error ? (
          <p className="app-form__error" role="alert">
            {error}
          </p>
        ) : null}
        <div className="ws-dialog__actions">
          <button type="button" className="btn btn--outline" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button
            type="submit"
            className="btn btn--primary"
            disabled={busy || !workspaceId || reason.trim().length < 3}
          >
            {busy ? 'Moving…' : 'Move class'}
          </button>
        </div>
      </form>
    </DialogShell>
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

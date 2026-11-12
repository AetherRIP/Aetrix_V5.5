import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { CapabilityList, Panel } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { useAuth } from '../lib/auth/AuthProvider'
import type { ApiResult, RequestOptions } from '../lib/api/client'
import { announcePlatformOverviewChanged } from '../lib/api/overview'
import {
  accountCapability,
  deleteAccount,
  getAccount,
  listAccounts,
  requestAccountRecovery,
  resendAccountInvitation,
  updateAccountRole,
  updateAccountStatus,
  type AccountCapability,
  type AccountPage,
  type AccountRoleChange,
  type AccountStatus,
  type ManageableRole,
  type MembershipEffect,
  type PlatformAccountDetail,
  type PlatformRole,
} from '../lib/api/accounts'

export const Route = createFileRoute('/_app/platform/users')({
  head: () => ({ meta: [{ title: 'Account management · Aetrix' }] }),
  component: PlatformAccountManagement,
})

type Read<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

/** One bounded read per section; nothing polls. */
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
      setState({ state: 'unavailable', reason: 'Sign in to the engine to read accounts.' })
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

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return [state, reload]
}

const ROLE_LABEL: Record<PlatformRole, string> = {
  owner: 'Platform owner',
  platform_operator: 'Administrator',
  supervisor: 'Teacher',
  assistant: 'Assistant',
  viewer: 'Viewer',
  unassigned: 'Unassigned',
}

const ROLE_TONE: Record<PlatformRole, 'ok' | 'attention' | 'neutral'> = {
  owner: 'ok',
  platform_operator: 'ok',
  supervisor: 'neutral',
  assistant: 'neutral',
  viewer: 'neutral',
  unassigned: 'attention',
}

const STATUS_TONE: Record<AccountStatus, 'ok' | 'attention' | 'neutral'> = {
  ACTIVE: 'ok',
  SUSPENDED: 'attention',
  UNCONFIRMED: 'neutral',
}

function stamp(value: string | null): string {
  if (!value) return 'Never'
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
  if (result.status === 'ok') {
    const payload = result.data as { message?: unknown } | undefined
    return {
      tone: 'ok',
      message:
        typeof payload?.message === 'string' ? payload.message : `${label} succeeded.`,
    }
  }
  if (result.status === 'unavailable') {
    return { tone: 'error', message: `${label} is unavailable: ${result.reason}` }
  }
  return { tone: 'error', message: `${label} failed: ${result.reason}` }
}

function PlatformAccountManagement() {
  const { session } = useAuth()
  const token = session?.access_token ?? null
  const actorId = session?.user?.id ?? null
  const claim = session?.user?.app_metadata as Record<string, unknown> | undefined
  const claimRole = claim?.aetrix_role
  const isOwner = claimRole === 'owner' || claimRole === 'PLATFORM_OWNER'

  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [role, setRole] = useState<PlatformRole | ''>('')
  const [status, setStatus] = useState<AccountStatus | ''>('')
  const [joined, setJoined] = useState<'' | 'yes' | 'no'>('')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [notice, setNotice] = useState<{ tone: 'ok' | 'error'; message: string } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const [capability, reloadCapability] = useRead<AccountCapability>(
    `accounts-capability:${token ?? 'anonymous'}`,
    token ? (options) => accountCapability(options) : null,
    token,
  )
  const configured = capability.state === 'ok' && capability.data.configured

  const [listState, reloadList] = useRead<AccountPage>(
    // The capability decides whether the list may be read at all, so its
    // readiness is part of the key: without it the first effect would fix the
    // list in its "not available" state before the credential is known.
    [
      'accounts',
      configured ? 'configured' : 'waiting',
      token ?? 'anonymous',
      search,
      role,
      status,
      joined,
      page,
    ].join('|'),
    configured && token
      ? (options) =>
          listAccounts(
            {
              q: search || undefined,
              role: role || undefined,
              status: status || undefined,
              joined: joined || undefined,
              page,
              pageSize: 50,
            },
            options,
          )
      : null,
    token,
  )

  const [detailState, reloadDetail] = useRead<PlatformAccountDetail>(
    `account:${selectedId ?? 'none'}:${token ?? 'anonymous'}`,
    selectedId && token ? (options) => getAccount(selectedId, options) : null,
    token,
  )

  const run = useCallback(
    async (
      label: string,
      action: () => Promise<ApiResult<unknown>>,
      options: { refreshDetail?: boolean } = {},
    ): Promise<boolean> => {
      setBusy(label)
      const result = await action()
      setBusy(null)
      setNotice(noticeFor(label, result))
      if (result.status !== 'ok') return false
      announcePlatformOverviewChanged()
      reloadList()
      if (options.refreshDetail !== false) reloadDetail()
      return true
    },
    [reloadDetail, reloadList],
  )

  // A role change answers with its membership effect, so this handler does not
  // reuse `run`: a success notice must say whether any workspace row moved.
  const changeRole = useCallback(
    async (accountId: string, nextRole: ManageableRole, reason: string) => {
      setBusy('Role change')
      const result = await updateAccountRole(accountId, nextRole, reason, { token })
      setBusy(null)
      if (result.status === 'ok') {
        const effects = Array.isArray(result.data.memberships) ? result.data.memberships : []
        const moved = effects.filter((effect) => effect.state === 'changed').length
        setNotice({
          tone: 'ok',
          message:
            moved > 0
              ? `Platform role saved; ${moved} workspace membership ${
                  moved === 1 ? 'row' : 'rows'
                } moved.`
              : 'Platform role saved, but no workspace membership row moved, so the account’s shell role did not change.',
        })
        announcePlatformOverviewChanged()
        reloadList()
        reloadDetail()
      } else {
        setNotice(noticeFor('Role change', result))
      }
      return result
    },
    [reloadDetail, reloadList, token],
  )

  const resetPage = useCallback(() => {
    setPage(1)
    setSelectedId(null)
  }, [])

  const refreshAll = useCallback(() => {
    reloadCapability()
    reloadList()
  }, [reloadCapability, reloadList])

  const summary =
    listState.state === 'ok'
      ? {
          total: listState.data.total,
          shown: listState.data.items.length,
          page: listState.data.page,
          pages: Math.max(1, Math.ceil(listState.data.total / listState.data.page_size)),
          limit: listState.data.page_size,
        }
      : null

  const providerState =
    capability.state === 'loading'
      ? { label: 'Checking engine', tone: 'neutral' as const }
      : capability.state !== 'ok'
        ? { label: 'Engine unavailable', tone: 'attention' as const }
        : capability.data.configured
          ? { label: 'Configured', tone: 'ok' as const }
          : { label: 'Not configured', tone: 'attention' as const }

  let body
  if (capability.state === 'loading') {
    body = (
      <Panel title="Accounts" note="Reading capability">
        <TableLoading label="Reading the engine’s account-management capability…" />
      </Panel>
    )
  } else if (capability.state !== 'ok') {
    body = (
      <div className="app-stack">
        <StatePanel
          tone={capability.state === 'error' ? 'error' : 'wip'}
          title={
            capability.state === 'error'
              ? capability.reason
              : 'The account API is not reachable from this build'
          }
          capability="GET /api/v1/admin/accounts/capability"
        >
          <p>
            {capability.state === 'error'
              ? capability.code === 403
                ? 'Only a platform owner or administrator may read platform accounts. A workspace role is not platform authority.'
                : 'The engine answered with an error, so no account figures are being guessed.'
              : capability.reason}
          </p>
        </StatePanel>
      </div>
    )
  } else if (!capability.data.configured) {
    body = (
      <div className="app-stack">
        <StatePanel
          tone="wip"
          title="Platform-wide accounts need a Supabase service-role key"
          capability="AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY"
        >
          <p>{capability.data.reason}</p>
          <p>
            Set <code>AETRIX_PLATFORM_ADMIN__SUPABASE_URL</code> and{' '}
            <code>AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY</code> in the engine&rsquo;s server-side
            secret environment, then restart it. The key can administer every account, so it is
            never placed in this browser, in a <code>VITE_</code> variable or in the repository.
            Workspace functions keep working without it — and this screen will not show one
            workspace&rsquo;s members as if they were every platform account.
          </p>
        </StatePanel>
        <Panel title="Capabilities and limits" note="Reported by the engine">
          <ul className="cap-list">
            {capability.data.operations.map((operation) => (
              <li className="cap-list__row" key={operation.name}>
                <span className="cap-list__copy">
                  <span className="cap-list__label">{operation.name}</span>
                  <span className="cap-list__detail">{operation.note}</span>
                </span>
                <span className="chip app-chip" data-tone={operation.supported ? 'attention' : 'neutral'}>
                  {operation.supported ? 'Requires credential' : 'Not supported'}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    )
  } else {
    body = (
      <div className="app-stack">
        <Panel title="Accounts" note="Supabase Auth directory" className="account-directory">
          <div className="account-summary" aria-label="Account directory summary">
            <div className="account-summary__fact">
              <span className="account-summary__label">Matching accounts</span>
              <strong className="account-summary__value">
                {summary ? summary.total : '—'}
              </strong>
              <small className="account-summary__note">
                {summary ? 'under the current filters' : 'not available'}
              </small>
            </div>
            <div className="account-summary__fact">
              <span className="account-summary__label">On this page</span>
              <strong className="account-summary__value">
                {summary ? summary.shown : '—'}
              </strong>
              <small className="account-summary__note">
                {summary ? `page ${summary.page} of ${summary.pages}` : 'not available'}
              </small>
            </div>
            <div className="account-summary__fact">
              <span className="account-summary__label">Read limit</span>
              <strong className="account-summary__value">
                {summary ? summary.limit : '—'}
              </strong>
              <small className="account-summary__note">rows per engine read</small>
            </div>
          </div>

          <form
            className="gem-filters account-filters"
            aria-label="Filter accounts"
            onSubmit={(event) => {
              event.preventDefault()
              setSearch(searchInput.trim())
              resetPage()
            }}
          >
              <label className="gem-field account-filters__search">
                <span>Search</span>
                <input
                  type="search"
                  value={searchInput}
                  placeholder="name, email or account id"
                  maxLength={200}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </label>
              <label className="gem-field">
                <span>Role</span>
                <select
                  value={role}
                  onChange={(event) => {
                    setRole(event.target.value as PlatformRole | '')
                    resetPage()
                  }}
                >
                  <option value="">Any role</option>
                  {(Object.keys(ROLE_LABEL) as PlatformRole[]).map((value) => (
                    <option key={value} value={value}>
                      {ROLE_LABEL[value]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="gem-field">
                <span>Status</span>
                <select
                  value={status}
                  onChange={(event) => {
                    setStatus(event.target.value as AccountStatus | '')
                    resetPage()
                  }}
                >
                  <option value="">Any status</option>
                  <option value="ACTIVE">Active</option>
                  <option value="SUSPENDED">Suspended</option>
                  <option value="UNCONFIRMED">Unconfirmed</option>
                </select>
              </label>
              <label className="gem-field">
                <span>Workspace</span>
                <select
                  value={joined}
                  onChange={(event) => {
                    setJoined(event.target.value as '' | 'yes' | 'no')
                    resetPage()
                  }}
                >
                  <option value="">Any membership</option>
                  <option value="yes">In a workspace</option>
                  <option value="no">Not in any workspace</option>
                </select>
              </label>
              <button type="submit" className="btn btn--primary account-filters__submit">
                Search
              </button>
          </form>

          {listState.state === 'ok' ? (
            <>
              {listState.data.truncated ? (
                <p className="gem-footnote">
                  The account ceiling configured on the engine was reached, so this list is
                  incomplete. Narrow the search or raise AETRIX_PLATFORM_ADMIN__MAX_ACCOUNTS.
                </p>
              ) : null}
              <AccountTable
                data={listState.data}
                selectedId={selectedId}
                onInspect={setSelectedId}
              />
              <nav className="account-pager" aria-label="Account pages">
                <span className="account-pager__status">
                  Page {summary?.page ?? 1} of {summary?.pages ?? 1}
                  <span aria-hidden="true"> · </span>
                  {summary?.total ?? 0} matching
                </span>
                <div className="account-pager__actions">
                  <button
                    type="button"
                    className="btn btn--outline btn--small"
                    disabled={page <= 1}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                  >
                    Previous
                  </button>
                  <button
                    type="button"
                    className="btn btn--outline btn--small"
                    disabled={page * listState.data.page_size >= listState.data.total}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    Next
                  </button>
                </div>
              </nav>
            </>
          ) : listState.state === 'loading' ? (
            <TableLoading label="The engine is listing Supabase accounts…" />
          ) : (
            <div className="account-table-error">
              <StatePanel
                tone="error"
                title={listState.reason}
                capability="GET /api/v1/admin/accounts"
              >
                <p>No account rows are rendered when the engine cannot answer.</p>
              </StatePanel>
            </div>
          )}
        </Panel>

        {selectedId ? (
          <AccountDetailPanel
            state={detailState}
            isOwner={isOwner}
            actorId={actorId}
            token={token}
            busy={busy}
            run={run}
            changeRole={changeRole}
            onClose={() => setSelectedId(null)}
          />
        ) : null}
      </div>
    )
  }

  return (
    <div className="app-stack account-page">
      <header className="account-page-head" aria-labelledby="account-page-title">
        <div className="account-page-head__copy">
          <h1 className="account-page-head__title" id="account-page-title">
            Account management
          </h1>
          <p className="account-page-head__lede">
            Every Supabase account registered with the platform&rsquo;s identity provider — its
            role, status and workspace memberships. Platform roles live in{' '}
            <code>app_metadata.aetrix_role</code>; ownership is assigned only by the identity
            provider.
          </p>
        </div>
        <div className="account-page-head__actions">
          <div className="account-page-head__chips" aria-label="Account directory state">
            <StatusChip tone="neutral">Supabase Auth</StatusChip>
            <StatusChip tone={providerState.tone}>{providerState.label}</StatusChip>
          </div>
          <button
            type="button"
            className="btn btn--outline btn--small"
            onClick={refreshAll}
            disabled={capability.state === 'loading'}
          >
            Refresh accounts
          </button>
        </div>
      </header>

      {notice ? (
        <p className="gem-notice" data-tone={notice.tone} role="status">
          {notice.message}
        </p>
      ) : null}

      {body}

      <Panel title="Role assignment" note="Identity provider only">
        <CapabilityList
          items={[
            {
              label: 'owner',
              detail:
                'Platform ownership. Assigned only in the identity provider; no API route can grant, change or remove it.',
              state: 'available',
              icon: 'shield',
            },
            {
              label: 'platform_operator',
              detail:
                'Platform administrator. May inspect accounts and manage teacher, assistant and viewer roles; only the owner may create or change another administrator.',
              state: 'available',
              icon: 'shield',
            },
            {
              label: 'supervisor · assistant · viewer',
              detail:
                'Workspace-facing roles. A change also rewrites the workspace membership role the shell reads; neither role confers platform administration.',
              state: 'available',
              icon: 'eye',
            },
            {
              label: 'Self-service role change',
              detail:
                'Never offered. The account writes its own user_metadata; nothing here reads a role from it.',
              state: 'blocked',
              icon: 'lock',
            },
            {
              label: 'Revoke another account’s sessions',
              detail:
                'Supabase Auth exposes no service-role session-revocation endpoint. Suspend the account instead; its current access token expires on its own.',
              state: 'blocked',
              icon: 'lock',
            },
          ]}
        />
      </Panel>
    </div>
  )
}

function AccountTable({
  data,
  selectedId,
  onInspect,
}: {
  data: AccountPage
  selectedId: string | null
  onInspect: (id: string | null) => void
}) {
  if (data.items.length === 0) {
    return (
      <div className="account-table-empty" role="status">
        <span className="account-table-empty__glyph" aria-hidden="true">
          <Icon name="records" size={18} />
        </span>
        <div className="account-table-empty__copy">
          <p className="account-table-empty__title">No account matches these filters</p>
          <p className="account-table-empty__note">
            The engine returned an empty directory for this search. Adjust the filters above;
            this screen does not invent rows to fill the table.
          </p>
        </div>
      </div>
    )
  }
  return (
    <div className="table-scroll account-table-scroll">
      <table className="data-table gem-table account-table">
        <caption className="visually-hidden">Accounts registered with Supabase Auth</caption>
        <thead>
          <tr>
            <th scope="col">Account</th>
            <th scope="col">Email</th>
            <th scope="col">Role</th>
            <th scope="col">Status</th>
            <th scope="col">Workspaces</th>
            <th scope="col">Last sign-in</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((account) => (
            <tr
              key={account.id}
              data-selected={selectedId === account.id ? 'true' : undefined}
            >
              <td>
                <span className="gem-key__label" title={account.display_name ?? undefined}>
                  {account.display_name ?? 'No display name'}
                </span>
                <span className="gem-key__fp mono" title={account.id}>
                  {account.id}
                </span>
              </td>
              <td className="account-table__email" title={account.email ?? undefined}>
                {account.email ?? '—'}
              </td>
              <td>
                <StatusChip tone={ROLE_TONE[account.role]}>{ROLE_LABEL[account.role]}</StatusChip>
              </td>
              <td>
                <StatusChip tone={STATUS_TONE[account.status]}>{account.status}</StatusChip>
              </td>
              <td>
                {account.has_workspace ? (
                  <span className="mono account-table__count">{account.workspace_count}</span>
                ) : (
                  <StatusChip tone="attention">None</StatusChip>
                )}
              </td>
              <td>{stamp(account.last_sign_in_at)}</td>
              <td>
                <button
                  type="button"
                  className="btn btn--outline btn--small account-table__action"
                  aria-pressed={selectedId === account.id}
                  onClick={() => onInspect(selectedId === account.id ? null : account.id)}
                >
                  {selectedId === account.id ? 'Close' : 'Inspect'}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function TableLoading({ label }: { label: string }) {
  return (
    <div className="account-table-loading" role="status" aria-busy="true" aria-live="polite">
      <div className="account-table-loading__head">
        <span className="account-table-loading__badge mono">
          <Icon name="pulse" size={14} />
          Reading directory
        </span>
        <span className="account-table-loading__label">{label}</span>
      </div>
      <div className="account-table-loading__rows" aria-hidden="true">
        {[0, 1, 2, 3].map((row) => (
          <div className="account-table-loading__row" key={row}>
            <span className="hub-skel" />
            <span className="hub-skel" />
            <span className="hub-skel" />
            <span className="hub-skel" />
          </div>
        ))}
      </div>
    </div>
  )
}

function AccountDetailPanel({
  state,
  isOwner,
  actorId,
  token,
  busy,
  run,
  changeRole,
  onClose,
}: {
  state: Read<PlatformAccountDetail>
  isOwner: boolean
  actorId: string | null
  token: string | null
  busy: string | null
  run: (
    label: string,
    action: () => Promise<ApiResult<unknown>>,
    options?: { refreshDetail?: boolean },
  ) => Promise<boolean>
  changeRole: (
    accountId: string,
    role: ManageableRole,
    reason: string,
  ) => Promise<ApiResult<AccountRoleChange>>
  onClose: () => void
}) {
  const [nextRole, setNextRole] = useState<ManageableRole | ''>('')
  const [reason, setReason] = useState('')
  const [roleEffect, setRoleEffect] = useState<MembershipEffect[] | null>(null)
  const [deleteEmail, setDeleteEmail] = useState('')
  const [deleteReason, setDeleteReason] = useState('')
  const panelRef = useRef<HTMLElement | null>(null)
  const scrolledAccount = useRef<string | null>(null)
  const lastAccountId = useRef<string | null>(null)

  const accountId = state.state === 'ok' ? state.data.id : null

  useEffect(() => {
    // A detail reload passes through a null id; that is not a change of account
    // and must not clear the role-change effect the operator just asked for.
    if (!accountId || accountId === lastAccountId.current) return
    lastAccountId.current = accountId
    setNextRole('')
    setReason('')
    setRoleEffect(null)
    setDeleteEmail('')
    setDeleteReason('')
  }, [accountId])

  useEffect(() => {
    if (state.state !== 'ok' || !accountId || scrolledAccount.current === accountId) return
    const node = panelRef.current
    if (!node) return
    scrolledAccount.current = accountId
    const top = node.getBoundingClientRect().top + window.scrollY - 70
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    window.scrollTo({ top: Math.max(0, top), behavior: reduced ? 'auto' : 'smooth' })
  }, [accountId, state.state])

  if (state.state !== 'ok') {
    return (
      <Panel title="Account details" note={state.state === 'loading' ? 'Loading…' : 'Unavailable'}>
        <StatePanel
          tone="error"
          title={state.state === 'loading' ? 'Reading account details…' : state.reason}
          capability="GET /api/v1/admin/accounts/{account_id}"
        >
          <p>
            {state.state === 'loading'
              ? 'The engine is reading this account from Supabase Auth.'
              : 'Details are not invented when the engine cannot answer.'}
          </p>
        </StatePanel>
        <button type="button" className="btn btn--outline btn--small" onClick={onClose}>
          Close
        </button>
      </Panel>
    )
  }

  const account = state.data
  const self = actorId === account.id
  const ownershipProtected = account.role === 'owner'
  const grantable: ManageableRole[] = isOwner
    ? ['platform_operator', 'supervisor', 'assistant', 'viewer']
    : ['supervisor', 'assistant', 'viewer']
  const canChangeRole = !self && !ownershipProtected
  const canChangeStatus = !self && !ownershipProtected && (isOwner || account.role !== 'platform_operator')

  return (
    <section
      ref={panelRef}
      className="app-card account-detail"
      aria-labelledby="account-detail-title"
    >
      <header className="account-detail__head">
        <div className="account-detail__identity">
          <p className="account-detail__eyebrow">Supabase Auth account</p>
          <h2 className="account-detail__title" id="account-detail-title">
            {account.display_name ?? account.email ?? 'Unnamed account'}
          </h2>
          <p className="account-detail__email">{account.email ?? account.id}</p>
        </div>
        <div className="account-detail__head-actions">
          <div className="account-detail__badges">
            <StatusChip tone={ROLE_TONE[account.role]}>{ROLE_LABEL[account.role]}</StatusChip>
            <StatusChip tone={STATUS_TONE[account.status]}>{account.status}</StatusChip>
          </div>
          <button
            type="button"
            className="account-detail__close"
            onClick={onClose}
            aria-label="Close details"
          >
            <Icon name="close" size={16} />
          </button>
        </div>
      </header>

      <div className="account-detail__facts">
        <div className="account-detail__fact">
          <span>Created</span>
          <strong>{stamp(account.created_at)}</strong>
          <small>identity provider</small>
        </div>
        <div className="account-detail__fact">
          <span>Last sign-in</span>
          <strong>{stamp(account.last_sign_in_at)}</strong>
          <small>as reported by Supabase</small>
        </div>
        <div className="account-detail__fact">
          <span>Email confirmed</span>
          <strong>{stamp(account.email_confirmed_at)}</strong>
          <small>no local copy is kept</small>
        </div>
      </div>

      <div className="account-detail__id">
        <span>Account ID</span>
        <code>{account.id}</code>
        <small>Supabase Auth user</small>
      </div>

      <div className="account-detail__body">
        <div className="account-detail__main">
          <section className="account-detail__section" aria-labelledby="account-memberships-title">
            <h3 className="gem-add__title" id="account-memberships-title">
              Workspace memberships
            </h3>
      {account.memberships.length === 0 ? (
        <p className="panel-copy">
          This account is not a member of any workspace. That is a platform fact, not a hidden
          membership.
        </p>
      ) : (
        <ul className="gem-projects">
          {account.memberships.map((membership) => (
            <li key={membership.user_row_id} className="gem-projects__row">
              <span className="gem-projects__id">{membership.workspace_name}</span>
              <span className="gem-projects__keys mono">{membership.workspace_slug}</span>
              <span className="gem-projects__keys">workspace role {membership.role}</span>
              {membership.is_demo ? <StatusChip tone="neutral">demo</StatusChip> : null}
              <span className="gem-footnote">joined {stamp(membership.joined_at)}</span>
            </li>
          ))}
        </ul>
      )}
          </section>

      {account.invitations.length > 0 ? (
        <section className="account-detail__section" aria-labelledby="account-invitations-title">
          <h3 className="gem-add__title" id="account-invitations-title">
            Invitations
          </h3>
          <ul className="gem-projects">
            {account.invitations.map((invitation) => (
              <li key={invitation.id} className="gem-projects__row">
                <span className="gem-projects__id">{invitation.workspace_name}</span>
                <span className="gem-projects__keys">role {invitation.role}</span>
                <StatusChip tone={invitation.status === 'PENDING' ? 'attention' : 'neutral'}>
                  {invitation.status}
                </StatusChip>
                <span className="gem-footnote">
                  {invitation.status === 'PENDING' ? 'expires' : 'expired'}{' '}
                  {stamp(invitation.expires_at)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

          <section className="account-detail__section" aria-labelledby="account-activity-title">
            <h3 className="gem-add__title" id="account-activity-title">
              Platform activity
            </h3>
      {account.audit.length === 0 ? (
        <p className="panel-copy">No platform-level action has been recorded for this account yet.</p>
      ) : (
        <ul className="gem-alerts">
          {account.audit.map((entry) => (
            <li key={entry.id} className="gem-alerts__row">
              <StatusChip tone="neutral">{entry.action}</StatusChip>
              <span className="gem-alerts__message">
                by {entry.actor_platform_role || 'unknown role'} · {entry.actor_subject}
              </span>
              <span className="gem-alerts__kind mono">{stamp(entry.created_at)}</span>
            </li>
          ))}
        </ul>
      )}
          </section>
        </div>

        <aside className="account-detail__side" aria-label="Account administration">
          <h3 className="gem-add__title">Administration</h3>
      {self ? (
        <p className="panel-copy">
          This is your own account. An administrator cannot change their own role or suspend
          themselves, so those controls are not offered.
        </p>
      ) : null}
      {ownershipProtected ? (
        <p className="panel-copy">
          Platform ownership is assigned by the identity-provider operator. It cannot be changed,
          suspended or deleted here.
        </p>
      ) : null}

      {canChangeRole ? (
        <form
          className="gem-filters account-detail__form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            if (!nextRole) return
            if (
              !window.confirm(
                `Change ${account.email ?? account.id} from ${ROLE_LABEL[account.role]} to ${ROLE_LABEL[nextRole]}?`,
              )
            ) {
              return
            }
            void changeRole(account.id, nextRole, reason).then((result) => {
              if (result.status !== 'ok') return
              setNextRole('')
              setReason('')
              // An engine that predates the membership report returns no list;
              // an empty list then means the screen must not claim a move.
              setRoleEffect(
                Array.isArray(result.data.memberships) ? result.data.memberships : [],
              )
            })
          }}
        >
          <label className="gem-field">
            <span>New platform role</span>
            <select
              value={nextRole}
              onChange={(event) => setNextRole(event.target.value as ManageableRole | '')}
            >
              <option value="">Choose a role</option>
              {grantable.map((value) => (
                <option key={value} value={value}>
                  {ROLE_LABEL[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field gem-field--wide">
            <span>Reason (recorded in the platform audit)</span>
            <input
              value={reason}
              maxLength={500}
              placeholder="why this role changes"
              onChange={(event) => setReason(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn--primary"
            disabled={!nextRole || busy === 'Role change'}
          >
            {busy === 'Role change' ? 'Saving…' : 'Change role'}
          </button>
        </form>
      ) : null}

      {roleEffect ? (
        <div className="account-detail__action" aria-live="polite">
          <span className="account-detail__action-label">Workspace membership effect</span>
          {roleEffect.length === 0 ? (
            <p className="panel-copy">
              The engine returned no membership rows for this change, so the account’s
              workspace role did not move.
            </p>
          ) : (
            <ul className="gem-alerts">
              {roleEffect.map((effect, index) => (
                <li
                  className="gem-alerts__row"
                  key={effect.user_row_id ?? `membership-effect-${index}`}
                >
                  <StatusChip tone={effect.state === 'changed' ? 'ok' : 'neutral'}>
                    {effect.state}
                  </StatusChip>
                  <span className="gem-alerts__message">
                    {effect.workspace_name ? `${effect.workspace_name}: ` : ''}
                    {effect.state === 'changed'
                      ? `workspace role ${effect.previous_role} → ${effect.role}`
                      : effect.reason}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}

      {canChangeStatus ? (
        <div className="gem-actions account-detail__action">
          <span className="account-detail__action-label">Account status</span>
          <button
            type="button"
            className="btn btn--outline"
            disabled={busy === 'Suspension' || busy === 'Reactivation'}
            onClick={() => {
              const suspending = account.status !== 'SUSPENDED'
              if (
                !window.confirm(
                  suspending
                    ? `Suspend ${account.email ?? account.id}? They will not be able to sign in until reactivated.`
                    : `Reactivate ${account.email ?? account.id}?`,
                )
              ) {
                return
              }
              void run(suspending ? 'Suspension' : 'Reactivation', () =>
                updateAccountStatus(
                  account.id,
                  suspending ? 'SUSPENDED' : 'ACTIVE',
                  reason,
                  { token },
                ),
              )
            }}
          >
            {account.status === 'SUSPENDED' ? 'Reactivate account' : 'Suspend account'}
          </button>
          <span className="gem-footnote">
            Suspension uses Supabase&rsquo;s <code>ban_duration</code>; it blocks new sign-ins.
          </span>
        </div>
      ) : null}

      {account.status === 'UNCONFIRMED' ? (
        <div className="gem-actions account-detail__action">
          <span className="account-detail__action-label">Invitation</span>
          <button
            type="button"
            className="btn btn--outline"
            disabled={busy === 'Invitation resend'}
            onClick={() => {
              if (!window.confirm(`Send a fresh invitation to ${account.email ?? account.id}?`)) return
              void run('Invitation resend', () => resendAccountInvitation(account.id, { token }))
            }}
          >
            Resend invitation
          </button>
          <span className="gem-footnote">Only for an account that has never confirmed its address.</span>
        </div>
      ) : null}

      {isOwner ? (
        <div className="gem-actions account-detail__action">
          <span className="account-detail__action-label">Recovery</span>
          <button
            type="button"
            className="btn btn--outline"
            disabled={busy === 'Recovery email'}
            onClick={() => {
              if (!window.confirm(`Send a recovery email to ${account.email ?? account.id}?`)) return
              void run('Recovery email', () => requestAccountRecovery(account.id, { token }))
            }}
          >
            Send recovery email
          </button>
          <span className="gem-footnote">
            Supabase delivers the link by email; it is never returned to this screen.
          </span>
        </div>
      ) : null}

      <div className="gem-actions account-detail__action">
        <span className="account-detail__action-label">Sessions</span>
        <button
          type="button"
          className="btn btn--outline"
          disabled
          title="Supabase Auth has no service-role endpoint to revoke another account's sessions."
        >
          Revoke sessions
        </button>
        <span className="gem-footnote">
          Not supported by Supabase Auth: only the account&rsquo;s own token can sign it out.
          Suspending blocks new sign-ins and the current token expires on its own.
        </span>
      </div>

      {isOwner ? (
        <form
          className="gem-filters account-detail__form"
          onSubmit={(event: FormEvent) => {
            event.preventDefault()
            if (!window.confirm(`Permanently delete the Supabase account ${account.email ?? account.id}?`)) {
              return
            }
            void run(
              'Deletion',
              () => deleteAccount(account.id, deleteEmail.trim(), deleteReason.trim(), { token }),
              { refreshDetail: false },
            ).then((ok) => {
              if (ok) onClose()
            })
          }}
        >
          <h4 className="account-detail__danger-title">Delete account</h4>
          <label className="gem-field">
            <span>Type the account email to confirm</span>
            <input
              type="email"
              value={deleteEmail}
              maxLength={320}
              placeholder={account.email ?? 'account email'}
              onChange={(event) => setDeleteEmail(event.target.value)}
            />
          </label>
          <label className="gem-field gem-field--wide">
            <span>Reason (required, recorded in the platform audit)</span>
            <input
              value={deleteReason}
              maxLength={500}
              minLength={3}
              placeholder="why this account is deleted"
              onChange={(event) => setDeleteReason(event.target.value)}
            />
          </label>
          <button
            type="submit"
            className="btn btn--outline"
            disabled={
              busy === 'Deletion' ||
              !deleteEmail.trim() ||
              deleteReason.trim().length < 3 ||
              !account.email ||
              deleteEmail.trim().toLowerCase() !== account.email.toLowerCase()
            }
          >
            {busy === 'Deletion' ? 'Deleting…' : 'Delete account'}
          </button>
          <span className="gem-footnote">
            Owner only. Aetrix workspace membership rows are retained as history and no longer
            authenticate after the identity is deleted.
          </span>
        </form>
      ) : null}

        </aside>
      </div>

      <div className="account-detail__footer">
        <button type="button" className="btn btn--outline btn--small" onClick={onClose}>
          Close details
        </button>
      </div>
    </section>
  )
}

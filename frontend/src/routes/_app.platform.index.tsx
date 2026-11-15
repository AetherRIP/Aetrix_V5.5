import { useCallback, useEffect, useRef, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { SystemStatusGrid } from '../components/app/SystemStatus'
import { CapabilityList, Panel } from '../components/app/PageBlocks'
import { HubSection } from '../components/hub/HubSection'
import {
  DashboardFallback,
  DashboardHero,
  DashboardSkeleton,
  QuickAction,
  Timeline,
  dashboardStamp,
  type TimelineItem,
} from '../components/hub/DashboardKit'
import { Icon } from '../components/ui/Icons'
import { useSystemStatus } from '../lib/api/useSystemStatus'
import { useEngineSession } from '../lib/api/session'
import { useResource } from '../lib/api/useResource'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import {
  consumePlatformOverviewStale,
  platformOverview,
  subscribePlatformOverviewChanged,
  type AccountCensus,
  type OverviewMetric,
  type PlatformOverview,
} from '../lib/api/overview'
import {
  accountCapability,
  listAccounts,
  type AccountCapability,
  type AccountPage,
} from '../lib/api/accounts'
import {
  listAllocations,
  listWorkspaceTargets,
  type Allocation,
  type AllocationPage,
  type WorkspaceTarget,
} from '../lib/api/allocations'
import { platformService } from '../lib/services'
import type { AuditEvent } from '../lib/api/types'

export const Route = createFileRoute('/_app/platform/')({
  component: PlatformOverviewPage,
})

type Read =
  | { state: 'loading' }
  | { state: 'ok'; data: PlatformOverview }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

function metricText(metric: OverviewMetric): string {
  if (metric.state === 'unavailable') return 'Unavailable'
  return String(metric.value ?? 0)
}

function metricStateLabel(metric: OverviewMetric): string {
  if (metric.state === 'unavailable') return 'Data unavailable'
  if (metric.state === 'no_records') return 'No records'
  return `Measured · ${metric.source}`
}

function humanise(value: string): string {
  const spaced = value.replace(/[._-]/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function ServiceBeacon({
  status,
  workspaces,
  allocations,
  loading,
}: {
  status: ReturnType<typeof useSystemStatus>[0]
  workspaces: number | null
  allocations: number | null
  loading: boolean
}) {
  const keys = ['api', 'database', 'worker', 'provider'] as const
  return (
    <div className="dash-signal dash-signal--platform">
      <div className="dash-signal__topline">
        <p className="dash-signal__eyebrow mono">Control plane</p>
        <span className="dash-signal__status mono">
          {status.state === 'ok' ? 'status read' : status.state === 'loading' ? 'reading' : 'unknown'}
        </span>
      </div>
      <div className="dash-console__counts">
        <span>
          <strong className="mono">{loading ? '—' : workspaces ?? '—'}</strong>
          <small>workspaces</small>
        </span>
        <span>
          <strong className="mono">{loading ? '—' : allocations ?? '—'}</strong>
          <small>active allocations</small>
        </span>
      </div>
      <div className="dash-beacon" aria-label="Platform service beacon">
        {keys.map((key) => {
          const subsystem = status.state === 'ok' ? status.data[key] : null
          const state = subsystem?.state ?? 'unknown'
          return (
            <span className="dash-beacon__item" key={key} title={subsystem?.summary ?? 'Not observed'}>
              <span className="dash-beacon__dot" data-state={state} aria-hidden="true" />
              <span>{key === 'api' ? 'API' : key === 'database' ? 'DB' : key}</span>
            </span>
          )
        })}
      </div>
      <p className="dash-signal__foot mono">
        {status.state === 'ok'
          ? `Checked ${dashboardStamp(status.data.checked_at)}`
          : status.state === 'error'
            ? 'Status endpoint refused or did not answer.'
            : 'Waiting for a status read.'}
      </p>
    </div>
  )
}

function PlatformFigures({ state, onRetry }: { state: Read; onRetry: () => void }) {
  if (state.state === 'loading') {
    return (
      <div className="dash-platform-loading">
        <p className="dash-loading">Loading…</p>
        <DashboardSkeleton rows={2} />
      </div>
    )
  }
  if (state.state === 'unavailable') {
    return (
      <StatePanel tone="wip" title="Platform figures are unavailable" capability="engine: platform overview">
        <p>{state.reason}</p>
        <button type="button" className="btn btn--outline" onClick={onRetry}>
          Try again
        </button>
      </StatePanel>
    )
  }
  if (state.state === 'error') {
    if (state.code === 403) {
      return (
        <StatePanel tone="error" title="Access denied" capability="platform authority">
          <p>
            This dashboard is restricted to the platform owner and administrators. Your session is
            valid but does not carry platform authority.
          </p>
        </StatePanel>
      )
    }
    return (
      <StatePanel tone="error" title="Platform figures could not be read" capability="engine: platform overview">
        <p>{state.reason}</p>
        <button type="button" className="btn btn--outline" onClick={onRetry}>
          Retry
        </button>
      </StatePanel>
    )
  }

  return <PlatformMetrics data={state.data} />
}

function PlatformMetrics({ data }: { data: PlatformOverview }) {
  return (
    <div className="dash-console">
      <div className="dash-metrics" aria-label="Platform figures">
        {data.metrics.map((metric) => (
          <div
            className="platform-metric dash-metric"
            key={metric.key}
            data-state={metric.state}
            title={metric.definition}
          >
            <span className="platform-metric__label dash-metric__label">{metric.label}</span>
            <strong
              className="platform-metric__value dash-metric__value mono"
              aria-label={`${metric.label}: ${metricText(metric)}`}
            >
              {metricText(metric)}
            </strong>
            <span className="platform-metric__state dash-metric__state mono">
              {metricStateLabel(metric)}
            </span>
            <p className="platform-metric__definition dash-metric__definition">
              {metric.state === 'unavailable' && metric.reason ? metric.reason : metric.definition}
            </p>
          </div>
        ))}
      </div>
      <CensusLine census={data.account_census} />
    </div>
  )
}

function CensusLine({ census }: { census: AccountCensus }) {
  return (
    <p className="dash-census">
      Workspace and allocation counts come from PostgreSQL. Teacher and assistant counts come from
      Supabase Auth and exclude suspended, unconfirmed and non-teaching accounts.{' '}
      {census.available
        ? `Identity census ${census.cached ? 'reused' : 'read'} at ${dashboardStamp(census.captured_at)}.`
        : 'The identity census is unavailable, so those two figures are not reported.'}
    </p>
  )
}

function WorkspaceNetwork({
  rows,
  state,
  reason,
}: {
  rows: readonly WorkspaceTarget[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
  reason: string | null
}) {
  if (state === 'loading') return <DashboardSkeleton rows={4} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="Workspace network is not available"
        reason={reason ?? 'The platform has not returned a workspace census.'}
        capability="GET /api/v1/admin/allocations/workspaces"
      />
    )
  }
  if (rows.length === 0) {
    return <p className="dash-empty">No teacher workspace exists yet.</p>
  }
  const max = Math.max(...rows.map((row) => row.active_allocations), 1)
  return (
    <ul className="dash-network" aria-label="Teacher workspaces">
      {rows.slice(0, 6).map((row) => (
        <li className="dash-network__row" key={row.id}>
          <div className="dash-network__identity">
            <strong>{row.name}</strong>
            <span className="mono">
              {row.slug} · {row.owner_label ?? row.owner_email ?? 'owner not recorded'}
            </span>
          </div>
          <div
            className="dash-network__bar"
            role="img"
            aria-label={`${row.active_allocations} active class allocation${row.active_allocations === 1 ? '' : 's'}`}
          >
            <span style={{ width: `${Math.max(3, (row.active_allocations / max) * 100)}%` }} />
          </div>
          <span className="dash-network__count mono">{row.active_allocations}</span>
        </li>
      ))}
    </ul>
  )
}

function AllocationActivity({
  rows,
  total,
  state,
  reason,
}: {
  rows: readonly Allocation[]
  total: number | null
  state: 'loading' | 'ok' | 'unavailable' | 'error'
  reason: string | null
}) {
  if (state === 'loading') return <DashboardSkeleton rows={3} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="Allocation activity is not available"
        reason={reason ?? 'The platform has not returned the allocation ledger.'}
        capability="GET /api/v1/admin/allocations"
      />
    )
  }
  if (rows.length === 0) {
    return <p className="dash-empty">No active class allocation is recorded.</p>
  }
  return (
    <ul className="dash-allocation-list">
      {rows.slice(0, 5).map((row) => (
        <li className="dash-allocation-list__row" key={row.id}>
          <span className="dash-allocation-list__marker" aria-hidden="true">
            <Icon name="classroom" size={14} />
          </span>
          <div>
            <strong>{row.class_name}</strong>
            <p>
              {row.workspace_name} · {row.allocated_by_label ?? row.allocated_by_subject}
            </p>
          </div>
          <span className="dash-allocation-list__stamp mono">{dashboardStamp(row.allocated_at)}</span>
        </li>
      ))}
      <li className="dash-section-foot">
        <span className="mono">{total ?? rows.length} active</span>
        <Link className="panel-link" to="/platform/workspaces">
          Allocation ledger <Icon name="arrow" size={14} />
        </Link>
      </li>
    </ul>
  )
}

function AccountFloor({
  capability,
  page,
  state,
  reason,
}: {
  capability: AccountCapability | null
  page: AccountPage | null
  state: 'capability-loading' | 'capability-error' | 'unconfigured' | 'loading' | 'ok' | 'error'
  reason: string | null
}) {
  if (state === 'capability-loading' || state === 'loading') return <DashboardSkeleton rows={3} />
  if (state === 'capability-error' || state === 'error') {
    return (
      <DashboardFallback
        title="The account directory is not available"
        reason={reason ?? 'The identity service has not answered.'}
        capability="GET /api/v1/admin/accounts"
      />
    )
  }
  if (state === 'unconfigured') {
    return (
      <div className="dash-empty-state">
        <p className="dash-empty-state__title">Account data needs a service-role key.</p>
        <p className="dash-empty">
          {capability?.reason ??
            'AETRIX_PLATFORM_ADMIN__SERVICE_ROLE_KEY is not set on the engine, so platform-wide accounts cannot be read.'}
        </p>
        <Link className="btn btn--small btn--outline" to="/platform/users">
          Account management
        </Link>
      </div>
    )
  }
  if (!page || page.items.length === 0) {
    return <p className="dash-empty">The identity directory returned no account.</p>
  }
  return (
    <div className="dash-accounts">
      <div className="dash-accounts__summary">
        <span>
          <strong className="mono">{page.total}</strong>
          <small>accounts read</small>
        </span>
        <span className="mono">{page.source}</span>
        <Link className="panel-link" to="/platform/users">
          Directory <Icon name="arrow" size={14} />
        </Link>
      </div>
      <ul className="dash-accounts__list">
        {page.items.slice(0, 5).map((account) => (
          <li className="dash-accounts__row" key={account.id}>
            <span className="dash-accounts__avatar" aria-hidden="true">
              {(account.display_name ?? account.email ?? '?').slice(0, 1).toUpperCase()}
            </span>
            <div className="dash-accounts__identity">
              <strong>{account.display_name ?? account.email ?? 'Unnamed account'}</strong>
              <span>{account.email ?? 'Email not recorded'}</span>
            </div>
            <span className="chip app-chip" data-tone={account.role === 'owner' ? 'ok' : 'neutral'}>
              {account.role}
            </span>
            <StatusChip tone={account.status === 'ACTIVE' ? 'ok' : 'attention'}>
              {account.status}
            </StatusChip>
          </li>
        ))}
      </ul>
    </div>
  )
}

function AuditPanel({
  status,
  events,
  state,
  isOwner,
  reason,
}: {
  status: ReturnType<typeof useEngineSession>['status']
  events: readonly AuditEvent[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
  isOwner: boolean
  reason: string | null
}) {
  if (status === 'loading') return <DashboardSkeleton rows={3} />
  if (status === 'unavailable' || status === 'error') {
    return (
      <DashboardFallback
        title="Audit scope is not confirmed"
        reason={reason ?? 'The engine has not confirmed this account’s platform authority.'}
        capability="GET /api/v1/me"
        compact
      />
    )
  }
  if (!isOwner) {
    return (
      <div className="dash-restricted">
        <span className="dash-restricted__icon" aria-hidden="true">
          <Icon name="lock" size={17} />
        </span>
        <div>
          <strong>Platform audit is owner-only.</strong>
          <p>
            Your administrator session can inspect account-level audit from an account page, but
            the platform-wide trail is reserved for the owner.
          </p>
          <Link className="panel-link" to="/platform/users">
            Account audit <Icon name="arrow" size={14} />
          </Link>
        </div>
      </div>
    )
  }
  if (state === 'loading') return <DashboardSkeleton rows={3} />
  if (state !== 'ok') {
    return (
      <DashboardFallback
        title="Platform activity is not available"
        reason={reason ?? 'The engine has not returned the platform audit trail.'}
        capability="GET /api/v1/admin/audit"
        compact
      />
    )
  }
  const items: TimelineItem[] = events.slice(0, 5).map((event) => ({
    id: event.id,
    title: humanise(event.action),
    detail: `${event.actor_label ?? event.actor_type} · ${event.entity_type}`,
    stamp: dashboardStamp(event.created_at),
  }))
  return <Timeline items={items} />
}

function PlatformOverviewPage() {
  const { user, session } = useAuth()
  const engine = useEngineSession()
  const [status, , checkedAt] = useSystemStatus()
  const token = session?.access_token ?? null
  const firstName = displayName(user).split(/\s+/)[0]
  const isOwner = engine.me?.role === 'PLATFORM_OWNER'

  const [state, setState] = useState<Read>({ state: 'loading' })
  const [tick, setTick] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const forceNext = useRef(false)
  const silentNext = useRef(false)

  useEffect(() => {
    if (!token) {
      setState({ state: 'unavailable', reason: 'Sign in to read platform figures.' })
      return
    }
    const pendingForce = forceNext.current
    const silent = silentNext.current
    forceNext.current = false
    silentNext.current = false
    const force = pendingForce || consumePlatformOverviewStale()
    const controller = new AbortController()
    let live = true
    if (force) setRefreshing(true)
    if (!silent && !force) setState({ state: 'loading' })

    void platformOverview(force, { token, signal: controller.signal })
      .then((result) => {
        if (!live) return
        if (result.status === 'ok') setState({ state: 'ok', data: result.data })
        else if (result.status === 'unavailable') {
          setState({ state: 'unavailable', reason: result.reason })
        } else {
          setState({ state: 'error', reason: result.reason, code: result.code })
        }
      })
      .finally(() => {
        if (live) setRefreshing(false)
      })

    return () => {
      live = false
      controller.abort()
    }
  }, [token, tick])

  const reload = useCallback((force: boolean, silent = false) => {
    forceNext.current = force
    silentNext.current = silent
    setTick((value) => value + 1)
  }, [])

  useEffect(() => subscribePlatformOverviewChanged(() => reload(true, true)), [reload])

  const [workspacesState, reloadWorkspaces] = useResource<WorkspaceTarget[]>(
    `platform-workspaces:${token ?? 'none'}`,
    token ? (signal) => listWorkspaceTargets({ token, signal }) : null,
  )
  const [allocationsState, reloadAllocations] = useResource<AllocationPage>(
    `platform-allocations:${token ?? 'none'}`,
    token ? (signal) => listAllocations({ status: 'ACTIVE', limit: 6 }, { token, signal }) : null,
  )
  const [capabilityState, reloadCapability] = useResource<AccountCapability>(
    `platform-account-capability:${token ?? 'none'}`,
    token ? (signal) => accountCapability({ token, signal }) : null,
  )
  const capability = capabilityState.state === 'ok' ? capabilityState.data : null
  const [accountsState, reloadAccounts] = useResource<AccountPage>(
    `platform-accounts:${token ?? 'none'}:${capability?.configured ? 'configured' : 'pending'}`,
    token && capability?.configured
      ? (signal) => listAccounts({ pageSize: 5 }, { token, signal })
      : null,
  )
  const [auditState, reloadAudit] = useResource<AuditEvent[]>(
    `platform-audit:${token ?? 'none'}:${isOwner ? 'owner' : 'restricted'}`,
    token && isOwner ? (signal) => platformService.audit({ token, signal }) : null,
  )

  const reloadEverything = () => {
    reload(true)
    reloadWorkspaces()
    reloadAllocations()
    reloadCapability()
    reloadAccounts()
    reloadAudit()
  }

  const workspaces = workspacesState.state === 'ok' ? workspacesState.data : []
  const allocationPage = allocationsState.state === 'ok' ? allocationsState.data : null
  const accounts = accountsState.state === 'ok' ? accountsState.data : null

  const note =
    state.state === 'ok'
      ? `Read ${dashboardStamp(state.data.generated_at)}`
      : 'Read from the engine'

  return (
    <div className="hub-main dash-page dash-platform">
      <DashboardHero
        role="platform"
        eyebrow="Platform control"
        title={`Good morning, ${firstName}.`}
        lede="The organisation from the control plane: workspace allocation, account access, service posture and the audit trail. Every read is platform-authorised; nothing below is estimated."
        aside={
          <ServiceBeacon
            status={status}
            workspaces={workspacesState.state === 'ok' ? workspaces.length : null}
            allocations={allocationPage ? allocationPage.total : null}
            loading={workspacesState.state === 'loading' || allocationsState.state === 'loading'}
          />
        }
        actions={
          <>
            <QuickAction
              to="/platform/workspaces"
              icon="blueprint"
              label="Workspace allocation"
              note="Classroom courses and ownership"
              primary
            />
            <QuickAction
              to="/platform/users"
              icon="records"
              label="Accounts & roles"
              note="Directory, status and membership"
            />
            <QuickAction
              to="/platform/health"
              icon="pulse"
              label="System health"
              note="Component readiness and probes"
            />
            <QuickAction
              to="/platform/audit"
              icon="shield"
              label="Audit log"
              note="Platform-level records"
            />
          </>
        }
      />

      <HubSection
        id="platform-figures"
        title={state.state === 'loading' ? 'Reading platform figures' : 'Platform overview'}
        note={note}
        index={1}
        className="hub-section--stats"
        action={
          <button
            type="button"
            className="btn btn--outline"
            onClick={reloadEverything}
            disabled={refreshing || state.state === 'loading'}
          >
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        }
      >
        <PlatformFigures state={state} onRetry={reloadEverything} />
      </HubSection>

      <div className="dash-grid dash-grid--platform">
        <div className="dash-col">
          <HubSection
            id="platform-workspaces"
            title="Workspace network"
            note="Active class allocations"
            index={2}
          >
            <WorkspaceNetwork
              rows={workspaces}
              state={
                workspacesState.state === 'ok'
                  ? 'ok'
                  : workspacesState.state === 'loading'
                    ? 'loading'
                    : workspacesState.state
              }
              reason={
                workspacesState.state === 'error' || workspacesState.state === 'unavailable'
                  ? workspacesState.reason
                  : null
              }
            />
            <div className="dash-section-foot">
              <Link className="panel-link" to="/platform/workspaces">
                Open workspace allocation <Icon name="arrow" size={14} />
              </Link>
            </div>
          </HubSection>

          <HubSection
            id="platform-allocations"
            title="Allocation activity"
            note="Active ledger"
            index={3}
          >
            <AllocationActivity
              rows={allocationPage?.items ?? []}
              total={allocationPage?.total ?? null}
              state={
                allocationsState.state === 'ok'
                  ? 'ok'
                  : allocationsState.state === 'loading'
                    ? 'loading'
                    : allocationsState.state
              }
              reason={
                allocationsState.state === 'error' || allocationsState.state === 'unavailable'
                  ? allocationsState.reason
                  : null
              }
            />
          </HubSection>

          <HubSection id="platform-accounts" title="Account floor" note="Identity directory" index={4}>
            <AccountFloor
              capability={capability}
              page={accounts}
              state={
                capabilityState.state === 'loading'
                  ? 'capability-loading'
                  : capabilityState.state !== 'ok'
                    ? 'capability-error'
                    : !capability?.configured
                      ? 'unconfigured'
                      : accountsState.state === 'loading'
                        ? 'loading'
                        : accountsState.state === 'ok'
                          ? 'ok'
                          : 'error'
              }
              reason={
                capabilityState.state === 'error' || capabilityState.state === 'unavailable'
                  ? capabilityState.reason
                  : accountsState.state === 'error' || accountsState.state === 'unavailable'
                    ? accountsState.reason
                    : null
              }
            />
          </HubSection>
        </div>

        <aside className="dash-col dash-col--rail" aria-label="Platform operations">
          <HubSection
            id="platform-health"
            title="System health"
            note={status.state === 'ok' ? 'Read from /status' : 'Reading /status'}
            index={5}
          >
            <SystemStatusGrid
              value={status}
              checkedAt={checkedAt}
              only={['api', 'database', 'worker', 'provider']}
            />
            <div className="dash-section-foot">
              <Link className="panel-link" to="/platform/health">
                Full component health <Icon name="arrow" size={14} />
              </Link>
            </div>
          </HubSection>

          <HubSection
            id="platform-activity"
            title="Platform activity"
            note={isOwner ? 'Owner audit trail' : 'Owner-only trail'}
            index={6}
          >
            <AuditPanel
              status={engine.status}
              events={auditState.state === 'ok' ? auditState.data : []}
              state={
                auditState.state === 'ok'
                  ? 'ok'
                  : auditState.state === 'loading' && isOwner
                    ? 'loading'
                    : auditState.state === 'loading'
                      ? 'unavailable'
                      : auditState.state
              }
              isOwner={isOwner}
              reason={
                auditState.state === 'error' || auditState.state === 'unavailable'
                  ? auditState.reason
                  : engine.reason
              }
            />
          </HubSection>

          <Panel title="Workspace allocation" index={7} note="Operator-enforced">
            <CapabilityList
              items={[
                {
                  label: 'Allocate a Classroom class',
                  detail:
                    'Operator-only action, one active allocation per class. An operator-recorded course stays unverified until Google lists it.',
                  state: 'available',
                  icon: 'classroom',
                },
                {
                  label: 'Reassign an allocation',
                  detail:
                    'Releases the current allocation and creates the new one in one transaction.',
                  state: 'available',
                  icon: 'pulse',
                },
                {
                  label: 'Teacher-side allocation changes',
                  detail: 'Not permitted by design: teachers cannot move classes.',
                  state: 'blocked',
                  icon: 'lock',
                },
              ]}
            />
            <Link className="panel-link" to="/platform/workspaces">
              <Icon name="blueprint" size={15} /> Open allocation ledger
            </Link>
          </Panel>
        </aside>
      </div>
    </div>
  )
}

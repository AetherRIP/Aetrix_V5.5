import { useCallback, useEffect, useRef, useState } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { SystemStatusGrid } from '../components/app/SystemStatus'
import { CapabilityList, Panel } from '../components/app/PageBlocks'
import { useSystemStatus } from '../lib/api/useSystemStatus'
import { HubHero } from '../components/hub/HubHero'
import { HubSection } from '../components/hub/HubSection'
import { Icon } from '../components/ui/Icons'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import {
  consumePlatformOverviewStale,
  platformOverview,
  subscribePlatformOverviewChanged,
  type OverviewMetric,
  type PlatformOverview,
} from '../lib/api/overview'

export const Route = createFileRoute('/_app/platform/')({
  component: PlatformOverviewPage,
})

type Read =
  | { state: 'loading' }
  | { state: 'ok'; data: PlatformOverview }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

const PLACEHOLDER_LABELS = [
  'Teacher workspaces',
  'Teachers',
  'Assistant accounts',
  'Active class allocations',
] as const

function stamp(value: string | null): string {
  if (!value) return 'not recorded'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return 'not recorded'
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function metricText(metric: OverviewMetric): string {
  if (metric.state === 'unavailable') return 'Unavailable'
  return String(metric.value ?? 0)
}

function metricStateLabel(metric: OverviewMetric): string {
  if (metric.state === 'unavailable') return 'Data unavailable'
  if (metric.state === 'no_records') return 'No records'
  return `Measured · ${metric.source}`
}

/**
 * The operator dashboard. It reads one aggregate endpoint; the figures are
 * counts, never rows, and each one states what it counts. Account and workspace
 * mutations announce a data-change event, which refreshes this view immediately
 * and bypasses the engine's census cache; the Refresh control does the same.
 */
function PlatformOverviewPage() {
  const { user, session } = useAuth()
  const [status, , checkedAt] = useSystemStatus()
  const token = session?.access_token ?? null
  const firstName = displayName(user).split(/\s+/)[0]

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

    void platformOverview(force, { token, signal: controller.signal }).then((result) => {
      if (!live) return
      if (result.status === 'ok') setState({ state: 'ok', data: result.data })
      else if (result.status === 'unavailable') {
        setState({ state: 'unavailable', reason: result.reason })
      } else {
        setState({ state: 'error', reason: result.reason, code: result.code })
      }
    }).finally(() => {
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

  useEffect(
    () => subscribePlatformOverviewChanged(() => reload(true, true)),
    [reload],
  )

  const note =
    state.state === 'ok'
      ? `Read ${stamp(state.data.generated_at)}`
      : 'Read from the engine'

  return (
    <div className="hub-main">
      <HubHero
        name={firstName}
        lede="Platform-level view. Workspace, account and allocation figures are read from the engine; allocation itself remains an operator action."
        actions={
          <>
            <Link to="/platform/workspaces" className="btn btn--primary">
              Workspace allocation
              <Icon name="arrow" size={16} />
            </Link>
            <Link to="/platform/users" className="btn btn--outline">
              Account management
            </Link>
          </>
        }
      />

      <HubSection
        id="platform-figures"
        title="Platform overview"
        note={note}
        index={1}
        className="hub-section--stats"
        action={
          <button
            type="button"
            className="btn btn--outline"
            onClick={() => reload(true)}
            disabled={refreshing || state.state === 'loading'}
          >
            {refreshing ? 'Refreshing…' : 'Refresh'}
          </button>
        }
      >
        <PlatformFigures state={state} onRetry={() => reload(true)} />
      </HubSection>

      <div className="hub-grid">
        <div className="hub-col">
          <Panel title="Workspace allocation" index={2} note="One workspace per class">
            <CapabilityList
              items={[
                {
                  label: 'Allocate a Google Classroom class',
                  detail:
                    'Operator-only action; one active allocation per class. Courses come from an operator record or a workspace’s Classroom sync; operator-recorded courses stay unverified until Google lists them.',
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
                  label: 'Teacher-side changes to allocation',
                  detail: 'Not permitted by design: teachers cannot move classes.',
                  state: 'blocked',
                  icon: 'lock',
                },
              ]}
            />
          </Panel>

          <Panel title="Accounts and roles" index={3} note="Four account types">
            <CapabilityList
              items={[
                {
                  label: 'owner',
                  detail:
                    'Owns the platform and every workspace. Assigned in the identity provider only; no screen grants or removes it.',
                  state: 'available',
                  icon: 'shield',
                },
                {
                  label: 'platform_operator',
                  detail: 'Operates the platform. No access to student records.',
                  state: 'available',
                  icon: 'shield',
                },
                {
                  label: 'supervisor',
                  detail: 'Owns one workspace; cannot see another workspace.',
                  state: 'available',
                  icon: 'eye',
                },
                {
                  label: 'assistant',
                  detail: 'Assigned work only; no workspace administration.',
                  state: 'available',
                  icon: 'pen',
                },
              ]}
            />
          </Panel>
        </div>

        <aside className="hub-col hub-col--aside" aria-label="Service context">
          <Panel
            title="Service status"
            index={4}
            note={status.state === 'ok' ? 'Read from /status' : 'Reading /status'}
          >
            <SystemStatusGrid
              value={status}
              checkedAt={checkedAt}
              only={['api', 'database', 'worker']}
            />
          </Panel>

          <Panel title="AI providers" index={5} note="Configuration only">
            <p className="panel-copy">
              The live provider is <code>UNVERIFIED</code>. Gemini usage and quota
              monitoring are not implemented; the navigation slot exists so the feature can
              arrive without restructuring the platform area.
            </p>
            <Link className="panel-link" to="/platform/integrations">
              <Icon name="blueprint" size={15} />
              Provider configuration
            </Link>
          </Panel>
        </aside>
      </div>
    </div>
  )
}

function PlatformFigures({ state, onRetry }: { state: Read; onRetry: () => void }) {
  if (state.state === 'loading') {
    return (
      <div className="platform-metrics" aria-busy="true" aria-label="Loading platform figures">
        {PLACEHOLDER_LABELS.map((label) => (
          <div className="platform-metric" key={label}>
            <span className="platform-metric__label">{label}</span>
            <span className="platform-metric__value platform-metric__value--text">Loading…</span>
            <span className="platform-metric__state">Reading from the engine</span>
          </div>
        ))}
      </div>
    )
  }

  if (state.state === 'unavailable') {
    return (
      <StatePanel
        tone="wip"
        title="Platform figures are unavailable"
        capability="engine: platform overview"
      >
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
        <StatePanel
          tone="error"
          title="Access denied"
          capability="platform authority"
        >
          <p>
            This dashboard is restricted to the platform owner and administrators.
            Your session is valid but does not carry platform authority.
          </p>
        </StatePanel>
      )
    }
    return (
      <StatePanel
        tone="error"
        title="Platform figures could not be read"
        capability="engine: platform overview"
      >
        <p>{state.reason}</p>
        <button type="button" className="btn btn--outline" onClick={onRetry}>
          Retry
        </button>
      </StatePanel>
    )
  }

  const census = state.data.account_census
  return (
    <>
      <div className="platform-metrics" aria-label="Platform figures">
        {state.data.metrics.map((metric) => (
          <div className="platform-metric" key={metric.key} title={metric.definition}>
            <span className="platform-metric__label">{metric.label}</span>
            <span
              className={
                metric.state === 'available'
                  ? 'platform-metric__value mono'
                  : 'platform-metric__value platform-metric__value--text'
              }
              aria-label={`${metric.label}: ${metricText(metric)}`}
            >
              {metricText(metric)}
            </span>
            <span className="platform-metric__state">{metricStateLabel(metric)}</span>
            <p className="platform-metric__definition">
              {metric.state === 'unavailable' && metric.reason
                ? metric.reason
                : metric.definition}
            </p>
          </div>
        ))}
      </div>
      <div className="platform-overview__meta">
        <p className="platform-overview__stamp">
          Workspace and allocation counts come from PostgreSQL. Teacher and assistant
          counts come from Supabase Auth and exclude suspended, unconfirmed and
          non-teaching accounts.{' '}
          {census.available
            ? `Identity census ${census.cached ? 'reused' : 'read'} at ${stamp(census.captured_at)}.`
            : 'The identity census is unavailable, so those two figures are not reported.'}
        </p>
      </div>
    </>
  )
}

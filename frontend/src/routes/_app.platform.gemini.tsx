import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { useAuth } from '../lib/auth/AuthProvider'
import type { ApiResult, RequestOptions } from '../lib/api/client'
import {
  addContributorKey,
  addKey,
  alerts as fetchAlerts,
  contributionSummary,
  createContributor,
  googleQuota,
  importKeys,
  listKeys,
  listModelInventory,
  listModels,
  overview as fetchOverview,
  removeKey,
  selectModel,
  setKeyEnabled,
  usage as fetchUsage,
  reinstateContributor,
  revokeContributorKey,
  suspendContributor,
  syncGoogleQuota,
  testModel,
  validateKey,
  withdrawContributor,
  type CapacityModel,
  type CatalogueModel,
  type Confidence,
  type ContributionSummary,
  type ContributorRow,
  type FleetAlert,
  type FleetKey,
  type FleetOverview,
  type GoogleQuotaProject,
  type GoogleQuotaReport,
  type GoogleQuotaValue,
  type ImportRow,
  type InventoryAvailability,
  type InventoryCategory,
  type InventoryLifecycle,
  type InventoryModel,
  type InventoryWorkload,
  type KeyPage,
  type ModelCatalogue,
  type ModelInventory,
  type ProjectRow,
  type ProjectVerification,
  type QuotaWindow,
  type SelectionRole,
  type UsageReport,
  type Validation,
} from '../lib/api/gemini'

export const Route = createFileRoute('/_app/platform/gemini')({
  head: () => ({ meta: [{ title: 'Gemini fleet · Aetrix' }] }),
  component: PlatformGemini,
})

const TABS = [
  'Overview',
  'API keys',
  'Models',
  'Model catalogue',
  'Contributors',
  'Projects',
  'Google quota',
  'Usage',
  'Alerts',
] as const
type Tab = (typeof TABS)[number]

type Loaded<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

/**
 * Why a section is empty. "Awaits the engine" used to be shown for every non-ok
 * read — a 401, a build with no origin and a loading spinner all looked the
 * same — so the screen claimed the engine was missing while it was answering.
 */
function loadNote(state: Loaded<unknown>): string {
  if (state.state === 'loading') return 'Loading…'
  if (state.state === 'unavailable') return 'No engine address'
  if (state.state === 'error') return state.code ? `Unavailable (${state.code})` : 'Unavailable'
  return 'Loaded'
}

/**
 * One bounded read per screen section. Nothing here polls: the monitor samples
 * project health on the engine, and an operator refreshes when they look.
 */
function useResource<T>(
  key: string,
  loader: ((options: RequestOptions) => Promise<ApiResult<T>>) | null,
  options: RequestOptions,
): [Loaded<T>, () => void] {
  const [state, setState] = useState<Loaded<T>>({ state: 'loading' })
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader
  const { token, signal } = options
  const tokenValue = token ?? null

  useEffect(() => {
    const current = loaderRef.current
    if (!current) {
      setState({ state: 'unavailable', reason: 'Sign in as a platform administrator.' })
      return
    }
    const controller = new AbortController()
    let live = true
    setState({ state: 'loading' })
    void current({ token: tokenValue, signal: controller.signal }).then((result) => {
      if (!live) return
      if (result.status === 'ok') setState({ state: 'ok', data: result.data })
      else if (result.status === 'unavailable') setState({ state: 'unavailable', reason: result.reason })
      else setState({ state: 'error', reason: result.reason, code: result.code })
    })
    return () => {
      live = false
      controller.abort()
    }
    // `key` encodes every input that should re-run the read.
  }, [key, tick, tokenValue, signal])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return [state, reload]
}

const HEALTH_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  HEALTHY: 'ok',
  UNKNOWN: 'attention',
  INVALID: 'neutral',
  DISABLED: 'neutral',
}

const VERIFICATION_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  VERIFIED: 'ok',
  UNVERIFIED: 'neutral',
  OPERATOR_DECLARED: 'neutral',
  UNVERIFIABLE: 'neutral',
  NOT_FOUND: 'attention',
  PERMISSION_DENIED: 'attention',
  ERROR: 'attention',
}

function verificationLabel(value: ProjectVerification | undefined): string {
  if (!value) return 'not checked'
  return value.replaceAll('_', ' ').toLowerCase()
}

const OPERATIONAL_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  OPERATIONAL: 'ok',
  DEGRADED: 'attention',
  RATE_LIMITED: 'attention',
  PROVIDER_UNAVAILABLE: 'attention',
  NETWORK_FAILURE: 'attention',
  NOT_TESTED: 'neutral',
  DISABLED: 'neutral',
}

function operationalLabel(value: string | null | undefined): string {
  return (value ?? 'NOT_TESTED').replaceAll('_', ' ')
}

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  CONFIRMED: 'Confirmed limit',
  ESTIMATED: 'Estimated limit',
  UNKNOWN: 'Limit unknown',
}

const numberFormat = new Intl.NumberFormat('en-GB')

function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return numberFormat.format(value)
}

function share(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `${Math.round(value * 100)}%`
}

function stamp(value: string | null | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function stampInZone(value: string | null | undefined, zone: string | undefined): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '—'
  return parsed.toLocaleString('en-GB', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: zone || undefined,
    timeZoneName: 'short',
  })
}

function dayLabel(value: string, zone?: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-GB', {
    day: '2-digit',
    month: 'short',
    timeZone: zone || undefined,
  })
}

function PlatformGemini() {
  const { session } = useAuth()
  const token = session?.access_token ?? null
  const [tab, setTab] = useState<Tab>('Overview')
  const [notice, setNotice] = useState<string | null>(null)

  const [overview, reloadOverview] = useResource<FleetOverview>(
    `overview:${token ?? 'anonymous'}`,
    token ? (options) => fetchOverview(options) : null,
    { token },
  )

  return (
    <div className="app-stack">
      <section className="app-card gem-head" aria-label="Gemini fleet">
        <div className="app-card__head">
          <h2 className="app-card__title">Gemini fleet</h2>
          <span className="app-card__note mono">
            {overview.state === 'ok' ? `observed ${stamp(overview.data.observed_at)}` : 'engine'}
          </span>
        </div>
        <p className="panel-copy">
          Keys are grouped by Google Cloud project because Gemini&rsquo;s free tier is metered
          per project, per model: adding a key to a project adds no capacity. Remaining
          allowance is estimated from Aetrix&rsquo;s own ledger and labelled{' '}
          <code>CONFIRMED</code>, <code>ESTIMATED</code> or <code>UNKNOWN</code> — never
          presented as a figure Google reported.
        </p>
        <div className="app-tabs gem-tabs" role="tablist" aria-label="Gemini management sections">
          {TABS.map((label) => (
            <button
              key={label}
              type="button"
              role="tab"
              id={`gem-tab-${label}`}
              aria-selected={tab === label}
              aria-controls={`gem-panel-${label}`}
              className={tab === label ? 'app-tab is-active' : 'app-tab'}
              onClick={() => setTab(label)}
            >
              {label}
            </button>
          ))}
        </div>
      </section>

      {notice ? (
        <p className="gem-notice" role="status">
          {notice}
        </p>
      ) : null}

      <div
        role="tabpanel"
        id={`gem-panel-${tab}`}
        aria-labelledby={`gem-tab-${tab}`}
        className="gem-panel"
      >
        {tab === 'Overview' ? (
          <OverviewTab state={overview} onRefresh={reloadOverview} />
        ) : null}
        {tab === 'API keys' ? (
          <KeysTab token={token} projects={overview.state === 'ok' ? overview.data.projects_detail : []} notify={setNotice} />
        ) : null}
        {tab === 'Models' ? <ModelsTab token={token} notify={setNotice} /> : null}
        {tab === 'Model catalogue' ? (
          <ModelInventoryTab token={token} notify={setNotice} />
        ) : null}
        {tab === 'Contributors' ? (
          <ContributorsTab token={token} notify={setNotice} />
        ) : null}
        {tab === 'Projects' ? (
          <ProjectsTab state={overview} onRefresh={reloadOverview} />
        ) : null}
        {tab === 'Google quota' ? (
          <GoogleQuotaTab token={token} notify={setNotice} />
        ) : null}
        {tab === 'Usage' ? <UsageTab token={token} /> : null}
        {tab === 'Alerts' ? <AlertsTab token={token} /> : null}
      </div>
    </div>
  )
}

function LoadFailure({ state, capability }: { state: Loaded<unknown>; capability: string }) {
  if (state.state === 'error') {
    return (
      <StatePanel tone="error" title={state.reason} capability={capability}>
        <p>
          {state.code === 403
            ? 'Only a platform administrator may read the provider fleet.'
            : 'The engine answered with an error. The figures below are not being guessed.'}
        </p>
      </StatePanel>
    )
  }
  return (
    <StatePanel tone="wip" title="The fleet API is not reachable from this build" capability={capability}>
      <p>{state.state === 'unavailable' ? state.reason : 'Loading…'}</p>
    </StatePanel>
  )
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="gem-stat">
      <span className="gem-stat__label">{label}</span>
      <span className="gem-stat__value mono">{value}</span>
      {note ? <span className="gem-stat__note">{note}</span> : null}
    </div>
  )
}

function capacityNote(data: FleetOverview): string {
  const pools = data.projects_detail.flatMap((project) =>
    project.estimates.map((estimate) => ({
      project: project.project_id,
      model: estimate.model,
      window: estimate.requests_per_day,
    })),
  )
  const known = pools.filter((pool) => pool.window.limit !== null)
  if (known.length === 0) return 'no known limit to subtract from'
  const confirmed = known.every((pool) => pool.window.confidence === 'CONFIRMED')
  // Requests for different models are not interchangeable, so a single total
  // across model pools would overstate usable capacity.
  const detail = known
    .map(
      (pool) =>
        `${pool.project} / ${pool.model}: ${count(pool.window.remaining ?? 0)} left today`,
    )
    .join('; ')
  return `${detail} (${confirmed ? 'configured limit' : 'estimated limit'}, counted from Aetrix generation reservations plus recorded validation probes; per project-model, not additive)`
}

function OverviewTab({ state, onRefresh }: { state: Loaded<FleetOverview>; onRefresh: () => void }) {
  if (state.state !== 'ok') {
    return (
      <Panel title="Overview" note={loadNote(state)}>
        <LoadFailure state={state} capability="GET /api/v1/admin/providers/overview" />
      </Panel>
    )
  }
  const data = state.data
  const health = data.keys_by_health

  return (
    <div className="app-stack">
      <Panel title="Fleet state" note={`day started ${stamp(data.day_started_at)}`}>
        <div className="gem-stats">
          <Stat label="Registered keys" value={count(data.keys_total)} note={`${count(data.declared_projects ?? data.projects)} declared project pool${data.projects === 1 ? '' : 's'}`} />
          <Stat label="Operational status" value={operationalLabel(data.operational_status)} note="recent calls, not credential validity" />
          <Stat label="Healthy keys" value={count(health.HEALTHY ?? 0)} note="last authentication verdict" />
          <Stat label="Unknown" value={count(health.UNKNOWN ?? 0)} note="never proven valid" />
          <Stat label="Disabled" value={count(health.DISABLED ?? 0)} note="withheld by an operator" />
          <Stat label="Invalid" value={count(health.INVALID ?? 0)} note="rejected with 401" />
          <Stat
            label="Attempted today"
            value={count(data.attempted_today ?? data.requests_today)}
            note={`${count(data.successful_today ?? 0)} succeeded · ${count(data.failures_today)} failed`}
          />
          <Stat
            label="Tokens today"
            value={count(data.input_tokens_today + data.output_tokens_today)}
            note={`${count(data.input_tokens_today)} in · ${count(data.output_tokens_today)} out · provider metadata only`}
          />
          <Stat label="Error rate today" value={share(data.error_rate_today)} note={`${count(data.failures_today)} of ${count(data.attempted_today ?? data.requests_today)} attempts`} />
          <Stat
            label="Next daily reset"
            value={stampInZone(data.reset_at, data.reset_timezone)}
            note={`midnight ${data.reset_timezone ?? 'quota zone'}`}
          />
          <Stat label="Last provider success" value={stamp(data.last_success_at)} note="recorded in the ledger" />
          <Stat label="Last failure" value={stamp(data.last_failure_at)} note={data.last_failure_category ?? 'no failure recorded'} />
          <Stat
            label="Verified projects"
            value={count(data.verified_projects ?? 0)}
            note={
              data.project_verification === 'GOOGLE_CLOUD'
                ? 'identity confirmed by Google Resource Manager'
                : 'no Google project check has succeeded'
            }
          />
        </div>
        {data.last_failure_message ? (
          <p className="panel-copy">Last failure: {data.last_failure_message}</p>
        ) : null}
        <p className="gem-footnote">
          Estimated available capacity: {capacityNote(data)}. These are Aetrix policy limits and
          Aetrix-recorded usage, not Google-reported quota.{' '}
          {data.project_verification === 'GOOGLE_CLOUD'
            ? 'Project identities were checked with Google Resource Manager; Google-reported limits and usage are on the Google quota tab.'
            : 'Project IDs are operator-declared and no Google verification has succeeded; keys sharing a declared ID are counted as one pool, which may understate capacity if the declaration is wrong.'}
        </p>
        <button type="button" className="btn btn--outline gem-refresh" onClick={onRefresh}>
          Refresh
        </button>
      </Panel>

      <Panel title="Projects" note={`${count(data.projects)} declared pooled allowance${data.projects === 1 ? '' : 's'}`}>
        {data.projects_detail.length === 0 ? (
          <p className="panel-copy">
            No key is registered yet. Add one under API keys and name its Google Cloud project —
            a key with no project cannot be counted against a real allowance.
          </p>
        ) : (
          <ProjectSummaries projects={data.projects_detail} />
        )}
      </Panel>
    </div>
  )
}

function ProjectSummaries({ projects }: { projects: ProjectRow[] }) {
  return (
    <ul className="gem-projects">
      {projects.map((project) => {
        const worst = project.estimates.find((estimate) => estimate.exhausted)
        return (
          <li key={project.project_id} className="gem-projects__row">
            <span className="gem-projects__id mono">{project.project_id}</span>
            <span className="gem-projects__keys">
              {count(project.keys)} key{project.keys === 1 ? '' : 's'} · {count(project.healthy)} healthy
              {project.unknown ? ` · ${count(project.unknown)} unknown` : ''}
              {project.invalid ? ` · ${count(project.invalid)} invalid` : ''}
              {project.disabled ? ` · ${count(project.disabled)} disabled` : ''}
              {' · '}{verificationLabel(project.verification)}
            </span>
            <StatusChip tone={OPERATIONAL_TONE[project.operational_status ?? 'NOT_TESTED'] ?? 'neutral'}>
              {operationalLabel(project.operational_status)}
            </StatusChip>
            {project.cooldown_until && new Date(project.cooldown_until) > new Date() ? (
              <StatusChip tone="attention">Paused until {stamp(project.cooldown_until)}</StatusChip>
            ) : worst ? (
              <StatusChip tone="attention">Quota exhausted ({worst.model})</StatusChip>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

function QuotaMeter({ label, window }: { label: string; window: QuotaWindow }) {
  const filled = window.used_share ?? 0
  return (
    <div className="gem-quota">
      <span className="gem-quota__label">{label}</span>
      <span className="gem-quota__figures mono">
        {count(window.used)} / {count(window.limit)}
      </span>
      <span
        className="meter gem-quota__meter"
        role="progressbar"
        aria-label={`${label} used`}
        aria-valuemin={0}
        aria-valuemax={window.limit ?? undefined}
        aria-valuenow={window.used}
        aria-valuetext={
          window.limit === null ? 'Limit unknown' : `${count(window.used)} of ${count(window.limit)} used`
        }
      >
        <i style={{ '--w': String(Math.min(Math.max(filled, 0), 1)) } as CSSProperties} />
      </span>
      <span className="gem-quota__remaining">
        {window.remaining === null ? 'remaining unknown' : `${count(window.remaining)} left`}
      </span>
    </div>
  )
}

function ProjectsTab({ state, onRefresh }: { state: Loaded<FleetOverview>; onRefresh: () => void }) {
  if (state.state !== 'ok') {
    return (
      <Panel title="Projects" note={loadNote(state)}>
        <LoadFailure state={state} capability="GET /api/v1/admin/providers/overview" />
      </Panel>
    )
  }
  const projects = state.data.projects_detail
  return (
    <div className="app-stack">
      {projects.length === 0 ? (
        <Panel title="Projects" note="None registered">
          <p className="panel-copy">No Google Cloud project has a key registered yet.</p>
        </Panel>
      ) : null}
      {projects.map((project, index) => (
        <Panel
          key={project.project_id}
          title={project.project_id}
          note={`${count(project.keys)} key${project.keys === 1 ? '' : 's'}`}
          index={index}
        >
          <div className="gem-credential">
            <StatusChip tone={VERIFICATION_TONE[project.verification ?? 'UNVERIFIED'] ?? 'neutral'}>
              {verificationLabel(project.verification)}
            </StatusChip>
            {project.project_number ? (
              <span className="mono">Google project #{project.project_number}</span>
            ) : null}
            <span>
              {project.google_quota_last_synced_at
                ? `Google quota last read ${stamp(project.google_quota_last_synced_at)}`
                : 'Google quota never read'}
            </span>
            {project.google_quota_stale ? (
              <StatusChip tone="attention">Quota data stale</StatusChip>
            ) : null}
          </div>
          <p className="gem-footnote">
            {project.verification === 'VERIFIED'
              ? 'Google Resource Manager confirmed this project identity. Keys are still grouped by the operator-declared id, and a 429 pauses the declared pool.'
              : `Project identity is ${verificationLabel(project.verification)}. Keys here are counted as one allowance because an operator declared the grouping; if that is wrong, capacity is understated. A 429 pauses this declared pool.`}
            {project.cooldown_until && new Date(project.cooldown_until) > new Date()
              ? ` Paused until ${stamp(project.cooldown_until)} after a quota rejection.`
              : ''}
          </p>
          {project.estimates.map((estimate) => (
            <section key={estimate.model} className="gem-model" aria-label={`${project.project_id} ${estimate.model}`}>
              <div className="gem-model__head">
                <h3 className="gem-model__name mono">{estimate.model}</h3>
                <StatusChip tone={estimate.confidence === 'CONFIRMED' ? 'ok' : 'attention'}>
                  {CONFIDENCE_LABEL[estimate.confidence]}
                </StatusChip>
              </div>
              <QuotaMeter label="Requests / minute" window={estimate.requests_per_minute} />
              <QuotaMeter label="Tokens / minute" window={estimate.tokens_per_minute} />
              <QuotaMeter label="Requests / day" window={estimate.requests_per_day} />
              <p className="gem-model__reset">
                Resets {stamp(estimate.reset_at)} · observed {stamp(estimate.observed_at)}
              </p>
              <ul className="gem-model__notes">
                {estimate.notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </section>
          ))}
        </Panel>
      ))}
      <button type="button" className="btn btn--outline gem-refresh" onClick={onRefresh}>
        Refresh
      </button>
    </div>
  )
}

const QUOTA_RUN_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  SUCCEEDED: 'ok',
  PARTIAL: 'attention',
  FAILED: 'attention',
}

function limitLabel(row: GoogleQuotaValue): string {
  if (row.is_unlimited) return 'Unlimited'
  if (row.limit === null) return 'Unavailable'
  return `${count(row.limit)}${row.unit ? ` ${row.unit}` : ''}`
}

function limitSourceLabel(source: GoogleQuotaValue['limit_source']): string {
  if (source === 'CLOUD_QUOTAS') return 'Cloud Quotas'
  if (source === 'CLOUD_MONITORING') return 'Cloud Monitoring'
  return 'No limit returned'
}

function QuotaTable({ quotas }: { quotas: GoogleQuotaValue[] }) {
  return (
    <div className="gem-quota-scroll">
      <table className="gem-quota-table">
        <thead>
          <tr>
            <th scope="col">Quota</th>
            <th scope="col">Dimensions</th>
            <th scope="col">Limit</th>
            <th scope="col">Usage</th>
            <th scope="col">Observed</th>
          </tr>
        </thead>
        <tbody>
          {quotas.map((row) => (
            <tr key={`${row.quota_id}:${JSON.stringify(row.dimensions)}`}>
              <td>
                <span className="gem-quota-table__name">
                  {row.quota_display_name ?? row.quota_id}
                </span>
                <span className="mono gem-quota-table__source">{row.quota_id}</span>
              </td>
              <td>
                {Object.keys(row.dimensions).length === 0
                  ? '—'
                  : Object.entries(row.dimensions)
                      .map(([key, value]) => `${key}=${value}`)
                      .join(' · ')}
              </td>
              <td>
                <span className="gem-quota-table__number">{limitLabel(row)}</span>
                <span className="gem-quota-table__source">
                  {limitSourceLabel(row.limit_source)}
                  {row.is_precise === false ? ' · imprecise' : ''}
                  {row.reset_time ? ` · reset ${row.reset_time}` : ''}
                </span>
              </td>
              <td>
                <span className="gem-quota-table__number">
                  {row.usage === null ? 'Unavailable' : count(row.usage)}
                </span>
                <span className="gem-quota-table__source">
                  {row.usage === null
                    ? 'No consumer-quota metric'
                    : `Cloud Monitoring · ${stamp(row.usage_observed_at)}`}
                  {row.exceeded !== null ? ` · ${count(row.exceeded)} exceeded` : ''}
                </span>
              </td>
              <td>
                <span>{stamp(row.observed_at)}</span>
                <span className="gem-quota-table__source">limit read</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GoogleQuotaProjectPanel({
  project,
  index,
}: {
  project: GoogleQuotaProject
  index: number
}) {
  return (
    <Panel
      title={project.project_id}
      note={`${count(project.quota_count)} quota limit${project.quota_count === 1 ? '' : 's'}`}
      index={index}
    >
      <div className="gem-credential">
        <StatusChip tone={VERIFICATION_TONE[project.verification] ?? 'neutral'}>
          {verificationLabel(project.verification)}
        </StatusChip>
        {project.project_number ? (
          <span className="mono">#{project.project_number}</span>
        ) : null}
        {project.stale ? <StatusChip tone="attention">Stale</StatusChip> : null}
        <span>
          {project.last_success_at
            ? `last quota read ${stamp(project.last_success_at)}`
            : 'never synchronised'}
        </span>
        <span>
          {count(project.usage_observed)} of {count(project.quota_count)} values have Google usage
        </span>
      </div>
      {project.last_error_message ? (
        <p className="panel-copy">
          {project.last_error_code ? `${project.last_error_code}: ` : ''}
          {project.last_error_message}
        </p>
      ) : null}
      {project.quotas.length === 0 ? (
        <p className="panel-copy">
          {project.last_success_at
            ? 'Google returned no quota definitions for this project on the last successful read. That is not the same as zero capacity.'
            : 'No Google quota has been read for this project yet.'}
        </p>
      ) : (
        <QuotaTable quotas={project.quotas} />
      )}
      {project.runs.length === 0 ? null : (
        <ul className="gem-quota-runs" aria-label={`${project.project_id} sync runs`}>
          {project.runs.map((run) => (
            <li key={run.id} className="gem-quota-runs__row" title={run.error_message ?? undefined}>
              <StatusChip tone={QUOTA_RUN_TONE[run.status] ?? 'neutral'}>
                {run.status}
              </StatusChip>
              <span>
                {run.trigger.toLowerCase()} · {stamp(run.started_at)} ·{' '}
                {count(run.api_calls)} Google call{run.api_calls === 1 ? '' : 's'} ·{' '}
                {count(run.snapshots_written)} rows
              </span>
              {run.error_code ? <span className="mono">{run.error_code}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  )
}

function GoogleQuotaTab({
  token,
  notify,
}: {
  token: string | null
  notify: (message: string | null) => void
}) {
  const [state, reload] = useResource<GoogleQuotaReport>(
    `google-quota:${token ?? 'anonymous'}`,
    token ? (options) => googleQuota(options) : null,
    { token },
  )
  const [syncing, setSyncing] = useState(false)

  const runSync = useCallback(async () => {
    if (!token) return
    setSyncing(true)
    const result = await syncGoogleQuota(undefined, { token })
    setSyncing(false)
    if (result.status === 'ok') {
      const outcomes = result.data.sync_results
      notify(
        outcomes.length === 0
          ? 'Google Cloud sync finished; no project is registered.'
          : `Google Cloud sync: ${outcomes
              .map((row) => `${row.project_id} ${row.status.toLowerCase()}`)
              .join('; ')}.`,
      )
      reload()
    } else {
      notify(`Google Cloud sync failed: ${result.reason}`)
    }
  }, [notify, reload, token])

  if (state.state !== 'ok') {
    return (
      <Panel title="Google quota" note={loadNote(state)}>
        <LoadFailure state={state} capability="GET /api/v1/admin/providers/google-quota" />
      </Panel>
    )
  }

  const data = state.data
  const fleet = data.fleet
  return (
    <div className="app-stack">
      <Panel title="Google Cloud quota" note={`observed ${stamp(data.observed_at)}`}>
        <p className="panel-copy">
          Read-only synchronisation of <code>{data.service}</code>. Limits come from Cloud Quotas
          and usage from Cloud Monitoring; each value carries its own source and observation time.
          Aetrix policy estimates stay on the Overview tab, so the two are never mixed.
        </p>
        <div className="gem-stats">
          <Stat
            label="Projects verified"
            value={`${count(fleet.verified_projects)} / ${count(fleet.declared_projects)}`}
            note="confirmed by Resource Manager"
          />
          <Stat
            label="Quota limits"
            value={count(fleet.quotas_total)}
            note="limit rows returned by Cloud Quotas"
          />
          <Stat
            label="Usage values"
            value={count(fleet.usage_observed)}
            note="with a matching consumer-quota metric"
          />
          <Stat
            label="Stale projects"
            value={count(fleet.stale_projects)}
            note={`no successful read in ${Math.round(fleet.stale_after_seconds / 60)} min`}
          />
          <Stat label="Last success" value={stamp(fleet.last_success_at)} note="any project" />
          <Stat
            label="Last failure"
            value={stamp(fleet.last_failure_at)}
            note={fleet.last_failure_message ?? 'no failed or partial run recorded'}
          />
          <Stat
            label="Scheduled sync"
            value={
              fleet.configured && fleet.scheduled_sync_enabled
                ? `every ${Math.round(fleet.sync_interval_seconds / 60)} min`
                : 'off'
            }
            note="the worker runs it beside correction jobs"
          />
        </div>
        <div className="gem-credential">
          <StatusChip tone={fleet.configured ? 'ok' : 'attention'}>
            {fleet.configured ? 'Credential configured' : 'No credential'}
          </StatusChip>
          <span className="mono">{fleet.credential_source}</span>
          {fleet.scheduled_sync_enabled ? null : <span>scheduled sync disabled</span>}
        </div>
        {fleet.configured ? null : (
          <p className="panel-copy">
            Set <code>AETRIX_GOOGLE_CLOUD__SERVICE_ACCOUNT_FILE</code> to a read-only service-account
            JSON file outside the repository, or enable the metadata server. A Gemini API key is not
            a Google Cloud IAM credential and is never used here.
          </p>
        )}
        <button
          type="button"
          className="btn btn--outline gem-refresh"
          onClick={() => void runSync()}
          disabled={!fleet.configured || syncing}
        >
          {syncing ? 'Reading Google Cloud…' : 'Sync now'}
        </button>
      </Panel>

      <Panel title="Required APIs" note="read-only permissions">
        <ul className="gem-projects">
          {data.apis.map((api) => (
            <li key={api.service} className="gem-projects__row">
              <span>
                <span className="gem-projects__id">{api.name}</span>
                <span className="mono gem-projects__keys">{api.permission}</span>
              </span>
              <StatusChip
                tone={
                  api.enabled === true ? 'ok' : api.enabled === false ? 'attention' : 'neutral'
                }
              >
                {api.enabled === true
                  ? 'Enabled'
                  : api.enabled === false
                    ? 'Not enabled'
                    : 'Not checked'}
              </StatusChip>
            </li>
          ))}
        </ul>
        <p className="gem-footnote">
          Aetrix only lists and reads. It never enables an API, changes a quota, grants a role,
          touches billing or creates a key. Enable APIs and grant roles only with operator approval.
        </p>
      </Panel>

      <Panel title="AI Studio usage" note="manually verified only">
        <StatusChip tone="attention">Unavailable programmatically</StatusChip>
        <p className="panel-copy">{data.ai_studio.reason}</p>
        <a href={data.ai_studio.source} target="_blank" rel="noreferrer">
          Google Gemini API rate-limit documentation
        </a>
      </Panel>

      <Panel title="Projects" note={`${count(data.projects.length)} declared`}>
        {data.projects.length === 0 ? (
          <p className="panel-copy">
            No Google Cloud project is declared by a registered key, so there is nothing to verify.
          </p>
        ) : (
          <p className="panel-copy">
            Every project is synced independently; one missing permission does not hide another
            project&rsquo;s data. A failed sync keeps the previous values with their original
            timestamps.
          </p>
        )}
      </Panel>

      {data.projects.map((project, index) => (
        <GoogleQuotaProjectPanel key={project.project_id} project={project} index={index} />
      ))}

      <Panel title="What Google exposes" note="coverage, not a promise">
        <ul className="gem-model__notes">
          {data.coverage.supported.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
        <p className="gem-footnote">Known gaps:</p>
        <ul className="gem-model__notes">
          {data.coverage.unavailable.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </Panel>
    </div>
  )
}

function KeysTab({
  token,
  projects,
  notify,
}: {
  token: string | null
  projects: ProjectRow[]
  notify: (message: string | null) => void
}) {
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [projectFilter, setProjectFilter] = useState('')
  const [healthFilter, setHealthFilter] = useState('')
  const [adding, setAdding] = useState(false)
  const [validation, setValidation] = useState<Validation | null>(null)
  const [validatingId, setValidatingId] = useState<string | null>(null)

  const queryKey = useMemo(
    () =>
      ['keys', token ?? 'anonymous', search, projectFilter, healthFilter].join('|'),
    [token, search, projectFilter, healthFilter],
  )
  const [keys, reloadKeys] = useResource<KeyPage>(
    queryKey,
    token
      ? (options) =>
          listKeys({ q: search || undefined, projectId: projectFilter || undefined, health: healthFilter || undefined }, options)
      : null,
    { token },
  )

  const act = useCallback(
    async (label: string, run: () => Promise<ApiResult<unknown>>) => {
      const result = await run()
      if (result.status === 'ok') {
        notify(`${label} succeeded.`)
        reloadKeys()
      } else {
        notify(`${label} failed: ${result.reason}`)
      }
    },
    [notify, reloadKeys],
  )

  // Validation reports what the probe actually did, so it renders a result card
  // instead of collapsing to "succeeded" / "failed".
  const validate = useCallback(
    async (key: FleetKey) => {
      setValidatingId(key.id)
      const result = await validateKey(key.id, { token })
      setValidatingId(null)
      if (result.status === 'ok') {
        setValidation(result.data)
        notify(null)
        reloadKeys()
      } else {
        setValidation(null)
        notify(`Validation failed: ${result.reason}`)
      }
    },
    [token, notify, reloadKeys],
  )

  return (
    <div className="app-stack">
      {validation ? (
        <ValidationResult result={validation} onDismiss={() => setValidation(null)} />
      ) : null}
      <Panel
        title="API key management"
        note={keys.state === 'ok' ? `${count(keys.data.total)} keys` : loadNote(keys)}
      >
        <div className="gem-toolbar">
          <form
            className="gem-filters"
            onSubmit={(event) => {
              event.preventDefault()
              setSearch(searchInput.trim())
            }}
          >
            <label className="gem-field">
              <span>Search</span>
              <input
                type="search"
                value={searchInput}
                placeholder="label, project or fingerprint"
                maxLength={120}
                onChange={(event) => setSearchInput(event.target.value)}
              />
            </label>
            <label className="gem-field">
              <span>Project</span>
              <select value={projectFilter} onChange={(event) => setProjectFilter(event.target.value)}>
                <option value="">All projects</option>
                {projects.map((project) => (
                  <option key={project.project_id} value={project.project_id}>
                    {project.project_id}
                  </option>
                ))}
              </select>
            </label>
            <label className="gem-field">
              <span>Health</span>
              <select value={healthFilter} onChange={(event) => setHealthFilter(event.target.value)}>
                <option value="">Any health</option>
                {['HEALTHY', 'UNKNOWN', 'INVALID', 'DISABLED'].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className="btn btn--outline">
              Apply
            </button>
          </form>
          <button type="button" className="btn btn--primary" onClick={() => setAdding((value) => !value)}>
            <Icon name="lock" size={15} />
            {adding ? 'Close' : 'Add keys'}
          </button>
        </div>

        {adding ? (
          <AddKeys
            token={token}
            notify={notify}
            onDone={() => {
              reloadKeys()
            }}
          />
        ) : null}

        {keys.state === 'ok' ? (
          <KeyTable
            keys={keys.data.items}
            token={token}
            act={act}
            onValidate={validate}
            validatingId={validatingId}
          />
        ) : (
          <LoadFailure state={keys} capability="GET /api/v1/admin/providers/keys" />
        )}
      </Panel>
    </div>
  )
}

function ValidationResult({
  result,
  onDismiss,
}: {
  result: Validation
  onDismiss: () => void
}) {
  return (
    <Panel
      title={result.valid ? 'Validation passed' : 'Validation failed'}
      note={`${result.account_label} · ${stamp(result.checked_at)}`}
    >
      <div className="gem-stats">
        <Stat
          label="Health"
          value={result.health}
          note={VALIDATION_CATEGORY[result.category]}
        />
        <Stat
          label="Operational"
          value={operationalLabel(result.operational_status)}
          note={VALIDATION_CATEGORY[result.category]}
        />
        <Stat
          label="HTTP status"
          value={result.http_status === null ? '—' : String(result.http_status)}
          note={`model ${result.model}`}
        />
        <Stat label="Credential" value="tested" note={result.key_fingerprint} />
        <Stat
          label="Latency"
          value={result.latency_ms === null ? '—' : `${result.latency_ms} ms`}
          note={result.project_id}
        />
      </div>
      <p className="panel-copy">
        {result.valid
          ? 'Google accepted this credential with a real request.'
          : result.detail ?? 'The provider rejected the probe.'}
      </p>
      {result.provider_message ? (
        <p className="panel-copy">Google said: {result.provider_message}</p>
      ) : null}
      {result.recommendation ? <p className="panel-copy">{result.recommendation}</p> : null}
      <button type="button" className="btn btn--outline btn--small" onClick={onDismiss}>
        Dismiss
      </button>
    </Panel>
  )
}

const VALIDATION_CATEGORY: Record<Validation['category'], string> = {
  ok: 'No problem found',
  authentication: 'Authentication (401)',
  permission: 'Permission or model access (403)',
  quota: 'Quota or rate limit',
  configuration: 'Configuration',
  network: 'Network failure',
  provider_server: 'Provider server error',
  provider_response: 'Provider response unusable',
  invalid_request: 'Invalid request',
  unsupported_model: 'Unsupported model',
  internal: 'Internal Aetrix failure',
}

function KeyTable({
  keys,
  token,
  act,
  onValidate,
  validatingId,
}: {
  keys: FleetKey[]
  token: string | null
  act: (label: string, run: () => Promise<ApiResult<unknown>>) => Promise<void>
  onValidate: (key: FleetKey) => void
  validatingId: string | null
}) {
  if (keys.length === 0) {
    return <p className="panel-copy">No key matches this filter.</p>
  }
  return (
    <div className="table-scroll">
      <table className="data-table gem-table">
        <caption className="visually-hidden">Registered Gemini credentials</caption>
        <thead>
          <tr>
            <th scope="col">Key</th>
            <th scope="col">Project</th>
            <th scope="col">Tier</th>
            <th scope="col">Health</th>
            <th scope="col">Operational</th>
            <th scope="col">Requests</th>
            <th scope="col">Tokens in / out</th>
            <th scope="col">Last success</th>
            <th scope="col">Last failure</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {keys.map((key) => (
            <tr key={key.id}>
              <td>
                <span className="gem-key__label">{key.account_label}</span>
                <span className="gem-key__fp mono">{key.key_fingerprint}</span>
              </td>
              <td className="mono">{key.project_id}</td>
              <td>{key.tier === 'UNKNOWN' ? 'Unverified' : key.tier}</td>
              <td>
                <StatusChip tone={HEALTH_TONE[key.health] ?? 'neutral'}>{key.health}</StatusChip>
                <span className="gem-key__cooldown">validity, not last call</span>
                {key.cooldown_until ? <span className="gem-key__cooldown">cooldown until {stamp(key.cooldown_until)}</span> : null}
              </td>
              <td>
                <StatusChip tone={OPERATIONAL_TONE[key.operational_status ?? 'NOT_TESTED'] ?? 'neutral'}>
                  {operationalLabel(key.operational_status)}
                </StatusChip>
                {key.last_failure_category ? (
                  <span className="gem-key__cooldown">last failure: {key.last_failure_category}</span>
                ) : null}
              </td>
              <td className="mono">{count(key.requests)}</td>
              <td className="mono">
                {count(key.input_tokens)} / {count(key.output_tokens)}
              </td>
              <td>{stamp(key.last_success_at)}</td>
              <td>
                {key.last_failure_at ? (
                  <>
                    {stamp(key.last_failure_at)}
                    {key.last_failure_status ? (
                      <span className="gem-key__status mono">HTTP {key.last_failure_status}</span>
                    ) : null}
                    {key.last_failure_provider_code ? (
                      <span className="gem-key__status mono"> {key.last_failure_provider_code}</span>
                    ) : null}
                    {key.last_failure_message ? (
                      <span className="gem-key__status"> {key.last_failure_message}</span>
                    ) : null}
                  </>
                ) : (
                  '—'
                )}
              </td>
              <td>
                <div className="gem-actions">
                  <button
                    type="button"
                    className="btn btn--outline btn--small"
                    disabled={!token || validatingId === key.id}
                    onClick={() => onValidate(key)}
                  >
                    {validatingId === key.id ? 'Validating…' : 'Validate'}
                  </button>
                  <button
                    type="button"
                    className="btn btn--outline btn--small"
                    disabled={!token}
                    onClick={() =>
                      void act(key.health === 'DISABLED' ? 'Enable' : 'Disable', () =>
                        setKeyEnabled(key.id, key.health === 'DISABLED', { token }),
                      )
                    }
                  >
                    {key.health === 'DISABLED' ? 'Enable' : 'Disable'}
                  </button>
                  <button
                    type="button"
                    className="btn btn--outline btn--small"
                    disabled={!token}
                    onClick={() => {
                      if (!window.confirm(`Remove ${key.account_label}? Its usage rows are kept.`)) return
                      void act('Removal', () => removeKey(key.id, { token }))
                    }}
                  >
                    Remove
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AddKeys({
  token,
  notify,
  onDone,
}: {
  token: string | null
  notify: (message: string | null) => void
  onDone: () => void
}) {
  const [projectId, setProjectId] = useState('')
  const [label, setLabel] = useState('')
  const [apiKeyValue, setApiKeyValue] = useState('')
  const [tier, setTier] = useState<'FREE' | 'PAID' | 'UNKNOWN'>('UNKNOWN')
  const [bulk, setBulk] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcomes, setOutcomes] = useState<ImportRow[] | null>(null)

  async function submitSingle(event: FormEvent) {
    event.preventDefault()
    if (!token) return
    setBusy(true)
    setOutcomes(null)
    const result = await addKey(
      { project_id: projectId.trim(), api_key: apiKeyValue.trim(), label: label.trim() || undefined, tier },
      { token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      setApiKeyValue('')
      notify(`Key ${result.data.account_label} registered in ${result.data.project_id}.`)
      onDone()
    } else {
      notify(`Registration failed: ${result.reason}`)
    }
  }

  async function submitBulk(event: FormEvent) {
    event.preventDefault()
    if (!token) return
    const entries = bulk
      .split('\n')
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [project, key, ...rest] = line.split(/[,\t]/).map((part) => part.trim())
        return { project_id: project ?? '', api_key: key ?? '', label: rest.join(' ') || undefined }
      })
    if (entries.length === 0) {
      notify('Paste one key per line as project-id,key,label.')
      return
    }
    setBusy(true)
    const result = await importKeys(entries, { token })
    setBusy(false)
    if (result.status === 'ok') {
      setOutcomes(result.data)
      const added = result.data.filter((row) => row.outcome === 'added').length
      notify(`${added} of ${result.data.length} keys registered.`)
      onDone()
      setBulk('')
    } else {
      notify(`Import failed: ${result.reason}`)
    }
  }

  return (
    <div className="gem-add">
      <form className="gem-add__form" onSubmit={submitSingle}>
        <h3 className="gem-add__title">Register one key</h3>
        <label className="gem-field">
          <span>Google Cloud project</span>
          <input
            value={projectId}
            required
            maxLength={100}
            placeholder="my-gcp-project"
            onChange={(event) => setProjectId(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>API key</span>
          <input
            type="password"
            value={apiKeyValue}
            required
            minLength={8}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setApiKeyValue(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Label</span>
          <input
            value={label}
            maxLength={120}
            placeholder="optional"
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Tier</span>
          <select value={tier} onChange={(event) => setTier(event.target.value as typeof tier)}>
            <option value="UNKNOWN">Unverified</option>
            <option value="FREE">Free</option>
            <option value="PAID">Paid</option>
          </select>
        </label>
        <button type="submit" className="btn btn--primary" disabled={busy || !token}>
          {busy ? 'Registering…' : 'Register key'}
        </button>
        <p className="gem-add__hint">
          The key is encrypted before it is stored and never returned by the API. Tier is recorded as
          given; nothing verifies a free-tier claim from Google.
        </p>
      </form>

      <form className="gem-add__form" onSubmit={submitBulk}>
        <h3 className="gem-add__title">Import several keys</h3>
        <label className="gem-field gem-field--wide">
          <span>One key per line: project-id, api-key, label</span>
          <textarea
            value={bulk}
            rows={6}
            spellCheck={false}
            placeholder={'proj-a, AIza…, key one\nproj-a, AIza…, key two'}
            onChange={(event) => setBulk(event.target.value)}
          />
        </label>
        <button type="submit" className="btn btn--outline" disabled={busy || !token}>
          Import
        </button>
        <p className="gem-add__hint">
          Each row is checked on its own: a duplicate or an empty row is reported without discarding
          the rows around it.
        </p>
      </form>

      {outcomes ? (
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Import outcomes</caption>
            <thead>
              <tr>
                <th scope="col">Row</th>
                <th scope="col">Project</th>
                <th scope="col">Label</th>
                <th scope="col">Outcome</th>
                <th scope="col">Detail</th>
              </tr>
            </thead>
            <tbody>
              {outcomes.map((row) => (
                <tr key={`${row.index}-${row.outcome}`}>
                  <td className="mono">{row.index + 1}</td>
                  <td className="mono">{row.project_id || '—'}</td>
                  <td>{row.label || '—'}</td>
                  <td>
                    <StatusChip tone={row.outcome === 'added' ? 'ok' : row.outcome === 'duplicate' ? 'attention' : 'neutral'}>
                      {row.outcome}
                    </StatusChip>
                  </td>
                  <td>{row.detail ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}

function UsageTab({ token }: { token: string | null }) {
  const [days, setDays] = useState(14)
  const [report, reload] = useResource<UsageReport>(
    `usage:${days}:${token ?? 'anonymous'}`,
    token ? (options) => fetchUsage(days, options) : null,
    { token },
  )

  if (report.state !== 'ok') {
    return (
      <Panel title="Usage analytics" note={loadNote(report)}>
        <LoadFailure state={report} capability="GET /api/v1/admin/providers/usage" />
      </Panel>
    )
  }
  const data = report.data
  const peak = Math.max(1, ...data.daily.map((row) => row.requests))

  return (
    <div className="app-stack">
      <Panel
        title="Daily requests"
        note={`since ${stamp(data.since)} · days start at midnight ${data.timezone ?? 'quota zone'}`}
      >
        <div className="gem-toolbar">
          <div className="app-toolbar__tabs" role="group" aria-label="Usage window">
            {[7, 14, 30].map((value) => (
              <button
                key={value}
                type="button"
                className={value === days ? 'app-tab is-active' : 'app-tab'}
                aria-pressed={value === days}
                onClick={() => setDays(value)}
              >
                {value} days
              </button>
            ))}
          </div>
          <button type="button" className="btn btn--outline" onClick={reload}>
            Refresh
          </button>
        </div>
        {data.daily.length === 0 ? (
          <p className="panel-copy">No provider call has been recorded in this window.</p>
        ) : (
          <ol className="gem-chart" aria-label="Requests per day">
            {data.daily.map((row) => (
              <li key={row.day} className="gem-chart__col">
                <span
                  className="gem-chart__bar"
                  style={{ '--h': String(row.requests / peak) } as CSSProperties}
                  aria-hidden="true"
                />
                <span className="gem-chart__value mono">{count(row.requests)}</span>
                <span className="gem-chart__day">
                  {dayLabel(row.day, data.timezone)}
                </span>
                <span className="gem-chart__sub">
                  {count(row.input_tokens + row.output_tokens)} tok · {count(row.failures)} fail
                </span>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel title="Recent provider calls" note="most recent 25, including failures">
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Recent provider calls and failures</caption>
            <thead>
              <tr>
                <th scope="col">Time</th>
                <th scope="col">Outcome</th>
                <th scope="col">Key / project</th>
                <th scope="col">Model</th>
                <th scope="col">HTTP / category</th>
                <th scope="col">Diagnostic</th>
                <th scope="col">Tokens in / out</th>
              </tr>
            </thead>
            <tbody>
              {(data.recent_calls ?? []).length === 0 ? (
                <tr>
                  <td colSpan={7} className="data-table__empty">
                    No provider call has been recorded.
                  </td>
                </tr>
              ) : (
                (data.recent_calls ?? []).map((call) => (
                  <tr key={call.id}>
                    <td>{stamp(call.created_at)}</td>
                    <td>
                      <StatusChip tone={call.success ? 'ok' : 'attention'}>
                        {call.success ? 'succeeded' : 'failed'}
                      </StatusChip>
                    </td>
                    <td>
                      <span className="gem-key__label">{call.credential_label ?? 'unattributed'}</span>
                      <span className="gem-key__fp mono">{call.project_id}</span>
                    </td>
                    <td className="mono">{call.model}</td>
                    <td>
                      {call.http_status ?? 'no response'}
                      {call.error_category ? ` · ${call.error_category}` : ''}
                      {call.reached_provider === false ? ' · did not reach Google' : ''}
                    </td>
                    <td>
                      {call.provider_code ? <span className="mono">{call.provider_code}: </span> : null}
                      {call.provider_message ?? call.error_class ?? '—'}
                    </td>
                    <td className="mono">
                      {call.input_tokens ?? '—'} / {call.output_tokens ?? '—'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="By model" note="Recorded usage">
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Usage per model</caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Requests</th>
                <th scope="col">Tokens in</th>
                <th scope="col">Tokens out</th>
                <th scope="col">Failures</th>
              </tr>
            </thead>
            <tbody>
              {data.by_model.length === 0 ? (
                <tr>
                  <td colSpan={5} className="data-table__empty">
                    No model reported usage in this window.
                  </td>
                </tr>
              ) : (
                data.by_model.map((row) => (
                  <tr key={row.model}>
                    <td className="mono">{row.model}</td>
                    <td className="mono">{count(row.requests)}</td>
                    <td className="mono">{count(row.input_tokens)}</td>
                    <td className="mono">{count(row.output_tokens)}</td>
                    <td className="mono">{count(row.failures)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel title="By project" note="The quota pool">
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">Usage per Google Cloud project</caption>
            <thead>
              <tr>
                <th scope="col">Project</th>
                <th scope="col">Requests</th>
                <th scope="col">Tokens in / out</th>
                <th scope="col">Failures</th>
                <th scope="col">Quota failures</th>
              </tr>
            </thead>
            <tbody>
              {data.by_project.length === 0 ? (
                <tr>
                  <td colSpan={5} className="data-table__empty">
                    No project has recorded usage in this window.
                  </td>
                </tr>
              ) : (
                data.by_project.map((row) => (
                  <tr key={row.project_id}>
                    <td className="mono">{row.project_id}</td>
                    <td className="mono">{count(row.requests)}</td>
                    <td className="mono">
                      {count(row.input_tokens)} / {count(row.output_tokens)}
                    </td>
                    <td className="mono">{count(row.failures)}</td>
                    <td className="mono">{count(row.quota_failures)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

const SEVERITY_TONE: Record<FleetAlert['severity'], 'ok' | 'attention' | 'neutral'> = {
  critical: 'neutral',
  warning: 'attention',
  info: 'ok',
}

function AlertsTab({ token }: { token: string | null }) {
  const [state, reload] = useResource<FleetAlert[]>(
    `alerts:${token ?? 'anonymous'}`,
    token ? (options) => fetchAlerts(options) : null,
    { token },
  )

  return (
    <div className="app-stack">
      <Panel
        title="Alerts"
        note={state.state === 'ok' ? `${count(state.data.length)} open` : loadNote(state)}
      >
        {state.state !== 'ok' ? (
          <LoadFailure state={state} capability="GET /api/v1/admin/providers/alerts" />
        ) : state.data.length === 0 ? (
          <p className="panel-copy">
            Nothing needs attention: no exhausted window, no paused project and no invalid credential
            is recorded.
          </p>
        ) : (
          <ul className="gem-alerts">
            {state.data.map((alert) => (
              <li key={`${alert.kind}-${alert.project_id ?? 'fleet'}-${alert.message}`} className="gem-alerts__row">
                <StatusChip tone={SEVERITY_TONE[alert.severity]}>{alert.severity}</StatusChip>
                <span className="gem-alerts__message">{alert.message}</span>
                <span className="gem-alerts__kind mono">{alert.kind}</span>
              </li>
            ))}
          </ul>
        )}
        <button type="button" className="btn btn--outline gem-refresh" onClick={reload}>
          Refresh
        </button>
      </Panel>

      <StatePanel
        tone="wip"
        title="Google-reported quota has its own tab"
        capability="Google quota"
      >
        <p>
          Cloud Monitoring and Cloud Quotas observations are synchronised separately, with their
          own sources and timestamps. That tab reports when no credential is configured; this
          alert list covers only Aetrix-recorded fleet state. Limits shown here as{' '}
          <code>ESTIMATED</code> remain Aetrix policy until Google reports a limit there.
        </p>
      </StatePanel>
    </div>
  )
}
const MODEL_STATUS_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  stable: 'ok',
  preview: 'attention',
  deprecated: 'attention',
  unsupported: 'neutral',
}

const ROLE_LABEL: Record<SelectionRole, string> = {
  primary: 'Primary correction',
  review: 'Secondary review',
  lightweight: 'Lightweight extraction',
}

function modelPrice(model: CatalogueModel): string {
  if (model.input_usd_per_million === null && model.output_usd_per_million === null) {
    return 'not configured'
  }
  const input = model.input_usd_per_million === null ? '—' : `$${model.input_usd_per_million}`
  const output = model.output_usd_per_million === null ? '—' : `$${model.output_usd_per_million}`
  return `${input} in / ${output} out per 1M`
}

/**
 * The model catalogue. Two rules: the list comes from each registered
 * credential's own models.list, and a saved selection is what the engine uses —
 * the dropdown is not a label.
 */
function ModelsTab({
  token,
  notify,
}: {
  token: string | null
  notify: (message: string | null) => void
}) {
  const [nonce, setNonce] = useState(0)
  const [busy, setBusy] = useState<string | null>(null)
  const [tested, setTested] = useState<Validation | null>(null)
  const [state, reload] = useResource<ModelCatalogue>(
    `models:${token ?? 'anonymous'}:${nonce}`,
    token ? (options) => listModels(nonce > 0, options) : null,
    { token },
  )

  const save = useCallback(
    async (role: SelectionRole, model: string) => {
      setBusy(`save:${role}`)
      const result = await selectModel(role, model, { token })
      setBusy(null)
      if (result.status === 'ok') {
        notify(`${ROLE_LABEL[role]} now uses ${result.data.model}. The engine uses it on its next call.`)
        reload()
      } else {
        notify(`Selection refused: ${result.reason}`)
      }
    },
    [token, notify, reload],
  )

  const probe = useCallback(
    async (model: string) => {
      setBusy(`test:${model}`)
      const result = await testModel(model, {}, { token })
      setBusy(null)
      if (result.status === 'ok') {
        setTested(result.data)
        notify(null)
      } else {
        setTested(null)
        notify(`Model test failed: ${result.reason}`)
      }
    },
    [token, notify],
  )

  if (state.state !== 'ok') {
    return (
      <Panel title="Models" note={loadNote(state)}>
        <LoadFailure state={state} capability="GET /api/v1/admin/providers/models" />
      </Panel>
    )
  }

  const catalogue = state.data
  const selectable = catalogue.models.filter((model) => model.status !== 'unsupported')
  const scanned = catalogue.projects.filter((project) => project.ok).length

  return (
    <div className="app-stack">
      <Panel
        title="Correction model roles"
        note="a saved selection overrides AETRIX_PROVIDER__MODEL_*"
      >
        <p className="panel-copy">
          A saved selection is stored in the database and used by the engine on its next call; the
          environment value is only the fallback. Only a model that a registered credential listed
          can be selected.
        </p>
        <div className="gem-roles">
          {(Object.keys(ROLE_LABEL) as SelectionRole[]).map((role) => (
            <label key={role} className="gem-field">
              <span>{ROLE_LABEL[role]}</span>
              <select
                value={catalogue.selections[role] ?? ''}
                disabled={!token || busy === `save:${role}`}
                onChange={(event) => void save(role, event.target.value)}
              >
                {selectable.some((model) => model.id === catalogue.selections[role]) ? null : (
                  <option value={catalogue.selections[role] ?? ''}>
                    {catalogue.selections[role]} (not listed now)
                  </option>
                )}
                {selectable.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.id}
                  </option>
                ))}
              </select>
              <span className="gem-key__fp">
                {catalogue.selection_sources[role] === 'database'
                  ? 'saved selection'
                  : 'environment fallback'}
              </span>
            </label>
          ))}
        </div>
        <p className="gem-footnote">
          The lightweight role is stored for extraction and classification work. Question
          marking runs on the primary role, so nothing here claims the secondary model is used
          for it.
        </p>
      </Panel>

      <Panel
        title="Discovered catalogue"
        note={`${count(catalogue.models.length)} listed · ${catalogue.cached ? 'cached' : 'fresh'}`}
      >
        <div className="gem-stats">
          <Stat
            label="Discovered"
            value={stamp(catalogue.discovered_at)}
            note={`reused for ${count(catalogue.ttl_seconds)}s`}
          />
          <Stat
            label="Correction models"
            value={count(selectable.length)}
            note={`${count(catalogue.models.length - selectable.length)} excluded`}
          />
          <Stat
            label="Projects listed"
            value={count(scanned)}
            note={`${count(catalogue.projects.length - scanned)} failed`}
          />
        </div>
        <ul className="gem-projects">
          {catalogue.projects.map((project) => (
            <li key={project.project_id} className="gem-projects__row">
              <span className="gem-projects__id mono">{project.project_id}</span>
              <span className="gem-projects__keys">
                {project.ok ? `${count(project.models)} models listed` : project.error}
                <span className="gem-key__fp mono"> · key {project.credential_fingerprint}</span>
              </span>
              <StatusChip tone={project.ok ? 'ok' : 'attention'}>
                {project.ok ? 'discovery ok' : 'discovery failed'}
              </StatusChip>
            </li>
          ))}
        </ul>
        <p className="panel-copy">{catalogue.note}</p>
        <button
          type="button"
          className="btn btn--outline gem-refresh"
          disabled={!token}
          onClick={() => setNonce((value) => value + 1)}
        >
          Refresh discovery
        </button>
      </Panel>

      <Panel
        title="Models"
        note="exact identifiers from Google's models.list; blank capabilities mean not verified here"
      >
        <div className="table-scroll">
          <table className="data-table gem-table">
            <caption className="visually-hidden">Discovered Gemini models</caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Status</th>
                <th scope="col">Inputs</th>
                <th scope="col">Tokens in / out</th>
                <th scope="col">List price</th>
                <th scope="col">Available to</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {catalogue.models.map((model) => (
                <tr key={model.id}>
                  <td>
                    <span className="gem-key__label mono">{model.id}</span>
                    <span className="gem-key__fp">{model.display_name ?? '—'}</span>
                  </td>
                  <td>
                    <StatusChip tone={MODEL_STATUS_TONE[model.status] ?? 'neutral'}>
                      {model.status}
                    </StatusChip>
                    {model.status_detail ? (
                      <span className="gem-key__cooldown">{model.status_detail}</span>
                    ) : null}
                  </td>
                  <td>
                    {model.capabilities.documented_inputs
                      ? model.capabilities.documented_inputs.join(', ')
                      : 'not verified'}
                  </td>
                  <td className="mono">
                    {count(model.input_token_limit)} / {count(model.output_token_limit)}
                  </td>
                  <td className="mono">{modelPrice(model)}</td>
                  <td>
                    {model.projects
                      .filter((project) => project.available)
                      .map((project) => project.project_id)
                      .join(', ') || 'no registered project'}
                  </td>
                  <td>
                    <div className="gem-actions">
                      {model.status === 'unsupported' ? (
                        <span className="gem-key__cooldown">excluded from correction</span>
                      ) : (
                        <>
                          <button
                            type="button"
                            className="btn btn--outline btn--small"
                            disabled={!token || busy === `test:${model.id}`}
                            onClick={() => void probe(model.id)}
                          >
                            {busy === `test:${model.id}` ? 'Testing…' : 'Test'}
                          </button>
                          <button
                            type="button"
                            className="btn btn--outline btn--small"
                            disabled={!token || busy !== null}
                            onClick={() => void save('primary', model.id)}
                          >
                            Use as primary
                          </button>
                          <button
                            type="button"
                            className="btn btn--outline btn--small"
                            disabled={!token || busy !== null}
                            onClick={() => void save('review', model.id)}
                          >
                            Use for review
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      {tested ? (
        <ValidationResult result={tested} onDismiss={() => setTested(null)} />
      ) : null}
    </div>
  )
}

const INVENTORY_CATEGORY_LABEL: Record<InventoryCategory, string> = {
  TEXT_OUT: 'Text-out',
  OTHER: 'Other',
  EMBEDDING: 'Embedding',
  AGENT: 'Agent',
  IMAGE_GENERATION: 'Image generation',
  MULTIMODAL: 'Multimodal',
  MUSIC_GENERATION: 'Music generation',
  TEXT_TO_SPEECH: 'Text-to-speech',
  TRANSCRIPTION: 'Transcription',
  LIVE_API: 'Live API',
}

const INVENTORY_WORKLOAD_LABEL: Record<InventoryWorkload, string> = {
  mathematics_marking: 'Mathematics marking',
  document_extraction: 'Document extraction',
  image_generation: 'Image generation',
  audio_processing: 'Audio processing',
  transcription: 'Transcription',
  embeddings: 'Embeddings',
  agent_workflows: 'Agent workflows',
  other: 'Other',
}

const INVENTORY_CATEGORY_ORDER: readonly InventoryCategory[] = [
  'TEXT_OUT',
  'OTHER',
  'EMBEDDING',
  'AGENT',
  'IMAGE_GENERATION',
  'MULTIMODAL',
  'MUSIC_GENERATION',
  'TEXT_TO_SPEECH',
  'TRANSCRIPTION',
  'LIVE_API',
]

const INVENTORY_WORKLOAD_ORDER: readonly InventoryWorkload[] = [
  'mathematics_marking',
  'document_extraction',
  'image_generation',
  'audio_processing',
  'transcription',
  'embeddings',
  'agent_workflows',
  'other',
]

const INVENTORY_LIFECYCLE_ORDER: readonly InventoryLifecycle[] = [
  'STABLE',
  'PREVIEW',
  'EXPERIMENTAL',
  'LEGACY',
  'DEPRECATED',
  'RETIRED',
  'UNKNOWN',
]

const INVENTORY_AVAILABILITY_ORDER: readonly InventoryAvailability[] = [
  'AVAILABLE',
  'UNAVAILABLE',
  'ACCESS_RESTRICTED',
  'QUOTA_EXHAUSTED',
  'NOT_TESTED',
  'UNKNOWN',
]

const INVENTORY_CAPABILITY_LABEL: Record<string, string> = {
  structured_output: 'Structured output',
  function_calling: 'Function calling',
  image_input: 'Image input',
  pdf_input: 'PDF input',
  audio_output: 'Audio output',
  live_api: 'Live API',
  image_generation: 'Image generation',
  thinking: 'Thinking',
}

const INVENTORY_CAPABILITY_ORDER = Object.keys(INVENTORY_CAPABILITY_LABEL)

function inventoryLimit(limit: number | null, used: number, unlimited: boolean): string {
  if (unlimited) return `${count(used)} / unlimited`
  if (limit === null) return `${count(used)} / not supplied`
  return `${count(used)} / ${count(limit)}`
}

function InventoryIdChip({ status }: { status: InventoryModel['id_status'] }) {
  const tone = status === 'VERIFIED' ? 'ok' : status === 'CORRECTED' ? 'attention' : 'neutral'
  return <StatusChip tone={tone}>{status.toLowerCase()}</StatusChip>
}

function InventoryAvailabilityChip({
  availability,
}: {
  availability: InventoryModel['availability']
}) {
  const tone =
    availability === 'AVAILABLE'
      ? 'ok'
      : availability === 'UNAVAILABLE' || availability === 'QUOTA_EXHAUSTED'
        ? 'attention'
        : 'neutral'
  return <StatusChip tone={tone}>{availability.replaceAll('_', ' ').toLowerCase()}</StatusChip>
}

/**
 * The operator's complete inventory. This is deliberately separate from the
 * live Models tab: registration does not mean a project can call the model,
 * and a quota snapshot is not current capacity.
 */
function ModelInventoryTab({
  token,
  notify,
}: {
  token: string | null
  notify: (message: string | null) => void
}) {
  const [workload, setWorkload] = useState<'all' | InventoryWorkload>('all')
  const [category, setCategory] = useState<'all' | InventoryCategory>('all')
  const [lifecycle, setLifecycle] = useState<'all' | InventoryLifecycle>('all')
  const [availability, setAvailability] = useState<'all' | InventoryAvailability>('all')
  const [capability, setCapability] = useState<string>('all')
  const [query, setQuery] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [state, reload] = useResource<ModelInventory>(
    `model-inventory:${token ?? 'anonymous'}`,
    token ? (options) => listModelInventory(options) : null,
    { token },
  )

  const save = useCallback(
    async (role: SelectionRole, model: InventoryModel) => {
      if (!token || !model.api_model_id) return
      setBusy(`${role}:${model.key}`)
      const result = await selectModel(role, model.api_model_id, { token })
      setBusy(null)
      if (result.status === 'ok') {
        notify(`${ROLE_LABEL[role]} now uses ${result.data.model}.`)
        reload()
      } else {
        notify(`Selection refused: ${result.reason}`)
      }
    },
    [notify, reload, token],
  )

  if (state.state !== 'ok') {
    return (
      <Panel title="Model catalogue" note={loadNote(state)}>
        <LoadFailure state={state} capability="GET /api/v1/admin/providers/models/inventory" />
      </Panel>
    )
  }

  const data = state.data
  const counts = data.counts
  const needle = query.trim().toLowerCase()
  const filtered = data.models.filter((model) => {
    if (workload !== 'all' && !model.workloads.includes(workload)) return false
    if (category !== 'all' && model.category !== category) return false
    if (lifecycle !== 'all' && model.lifecycle !== lifecycle) return false
    if (availability !== 'all' && model.availability !== availability) return false
    if (capability !== 'all' && model.capabilities[capability] !== true) return false
    if (!needle) return true
    return [model.display_name, model.api_model_id ?? '', model.family, model.key]
      .join(' ')
      .toLowerCase()
      .includes(needle)
  })

  return (
    <div className="app-stack">
      <Panel
        title="Operator catalogue"
        note={`${count(counts.total)} registered · snapshot imported ${stamp(data.imported_at)}`}
      >
        <div className="gem-stats">
          <Stat label="Registered" value={count(counts.total)} note="configuration-backed" />
          <Stat
            label="Verified IDs"
            value={count(counts.verified_api_ids)}
            note={`${count(counts.corrected_api_ids)} corrected`}
          />
          <Stat
            label="Unverified IDs"
            value={count(counts.unverified_api_ids)}
            note="never called by guesswork"
          />
          <Stat
            label="Available"
            value={count(counts.by_availability.AVAILABLE ?? 0)}
            note={`${count(counts.by_availability.NOT_TESTED ?? 0)} not tested`}
          />
          <Stat
            label="Known unavailable"
            value={count(counts.by_availability.UNAVAILABLE ?? 0)}
            note="retired entries included"
          />
          <Stat
            label="Quota records"
            value={count(counts.quota_records)}
            note={`${count(counts.quota_records_with_usage)} with usage`}
          />
          <Stat
            label="Quota flags"
            value={count(counts.quota_inconsistencies)}
            note="usage above the supplied limit"
          />
        </div>
        <p className="panel-copy">{data.note}</p>
        <div className="gem-roles">
          <label className="gem-field">
            <span>Workload</span>
            <select
              value={workload}
              onChange={(event) =>
                setWorkload(event.target.value as 'all' | InventoryWorkload)
              }
            >
              <option value="all">All registered models</option>
              {INVENTORY_WORKLOAD_ORDER.map((value) => (
                <option key={value} value={value}>
                  {INVENTORY_WORKLOAD_LABEL[value]} ({count(counts.by_workload[value] ?? 0)})
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field">
            <span>Category</span>
            <select
              value={category}
              onChange={(event) =>
                setCategory(event.target.value as 'all' | InventoryCategory)
              }
            >
              <option value="all">All categories</option>
              {INVENTORY_CATEGORY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {INVENTORY_CATEGORY_LABEL[value]} ({count(counts.by_category[value] ?? 0)})
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field">
            <span>Lifecycle</span>
            <select
              value={lifecycle}
              onChange={(event) =>
                setLifecycle(event.target.value as 'all' | InventoryLifecycle)
              }
            >
              <option value="all">All lifecycles</option>
              {INVENTORY_LIFECYCLE_ORDER.map((value) => (
                <option key={value} value={value}>
                  {value.toLowerCase()}
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field">
            <span>Availability</span>
            <select
              value={availability}
              onChange={(event) =>
                setAvailability(event.target.value as 'all' | InventoryAvailability)
              }
            >
              <option value="all">All availability states</option>
              {INVENTORY_AVAILABILITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {value.replaceAll('_', ' ').toLowerCase()}
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field">
            <span>Capability</span>
            <select value={capability} onChange={(event) => setCapability(event.target.value)}>
              <option value="all">All capabilities</option>
              {INVENTORY_CAPABILITY_ORDER.map((value) => (
                <option key={value} value={value}>
                  {INVENTORY_CAPABILITY_LABEL[value]} (verified)
                </option>
              ))}
            </select>
          </label>
          <label className="gem-field">
            <span>Search</span>
            <input
              type="search"
              value={query}
              placeholder="Model, family or API ID"
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        </div>
        <button
          type="button"
          className="btn btn--outline btn--small"
          disabled={!token}
          onClick={() => reload()}
        >
          Refresh inventory
        </button>
        <p className="gem-footnote">
          Showing {count(filtered.length)} of {count(data.models.length)} records. The quota
          columns preserve the supplied snapshot, including usage that exceeds a limit. They are
          not a live AI Studio reading.
        </p>
      </Panel>

      <Panel title="Registered inventory" note={`${count(filtered.length)} matching records`}>
        <div className="table-scroll">
          <table className="data-table gem-table">
            <caption className="visually-hidden">
              Complete registered AI Studio model inventory
            </caption>
            <thead>
              <tr>
                <th scope="col">Model</th>
                <th scope="col">Category</th>
                <th scope="col">Availability</th>
                <th scope="col">Workloads</th>
                <th scope="col">Quota used / limit</th>
                <th scope="col">Notes</th>
                <th scope="col">
                  <span className="visually-hidden">Correction role</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((model) => {
                const math =
                  model.api_model_id !== null &&
                  model.id_status !== 'UNVERIFIED' &&
                  model.workloads.includes('mathematics_marking')
                const extraction =
                  model.api_model_id !== null &&
                  model.id_status !== 'UNVERIFIED' &&
                  model.workloads.includes('document_extraction')
                return (
                  <tr key={model.key}>
                    <td>
                      <span className="gem-key__label">{model.display_name}</span>
                      <span className="gem-key__fp mono">
                        {model.api_model_id ?? 'no verified API ID'}
                      </span>
                      {model.supplied_api_id ? (
                        <span className="gem-key__cooldown">
                          supplied as {model.supplied_api_id}
                        </span>
                      ) : null}
                      <InventoryIdChip status={model.id_status} />
                    </td>
                    <td>
                      {INVENTORY_CATEGORY_LABEL[model.category]}
                      <span className="gem-key__fp">{model.lifecycle.toLowerCase()}</span>
                    </td>
                    <td>
                      <InventoryAvailabilityChip availability={model.availability} />
                      <span className="gem-key__fp">{model.catalogue_state.toLowerCase()}</span>
                    </td>
                    <td>
                      {model.workloads
                        .map((value) => INVENTORY_WORKLOAD_LABEL[value])
                        .join(', ')}
                    </td>
                    <td className="mono">
                      <span>RPM {inventoryLimit(model.quota.rpm_limit, model.quota.rpm_used, model.quota.rpm_unlimited)}</span>
                      <span className="gem-key__fp">
                        TPM {inventoryLimit(model.quota.tpm_limit, model.quota.tpm_used, model.quota.tpm_unlimited)}
                      </span>
                      <span className="gem-key__fp">
                        {model.quota.source} · {stamp(model.quota.imported_at)}
                      </span>
                      <span className="gem-key__fp">
                        RPD {inventoryLimit(model.quota.rpd_limit, model.quota.rpd_used, model.quota.rpd_unlimited)}
                      </span>
                      {model.quota.inconsistencies.length > 0 ? (
                        <span className="gem-key__cooldown">
                          {model.quota.inconsistencies.join(' ')}
                        </span>
                      ) : null}
                    </td>
                    <td>
                      {model.limitations.length > 0 ? (
                        <span className="gem-key__cooldown">{model.limitations.join(' ')}</span>
                      ) : (
                        <span className="gem-key__fp">No additional flags.</span>
                      )}
                    </td>
                    <td>
                      <div className="gem-actions">
                        {math ? (
                          <>
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              disabled={!token || busy !== null}
                              onClick={() => void save('primary', model)}
                            >
                              {busy === `primary:${model.key}` ? 'Saving…' : 'Primary'}
                            </button>
                            <button
                              type="button"
                              className="btn btn--outline btn--small"
                              disabled={!token || busy !== null}
                              onClick={() => void save('review', model)}
                            >
                              {busy === `review:${model.key}` ? 'Saving…' : 'Review'}
                            </button>
                          </>
                        ) : null}
                        {extraction ? (
                          <button
                            type="button"
                            className="btn btn--outline btn--small"
                            disabled={!token || busy !== null}
                            onClick={() => void save('lightweight', model)}
                          >
                            {busy === `lightweight:${model.key}` ? 'Saving…' : 'Extraction'}
                          </button>
                        ) : null}
                        {!math && !extraction ? (
                          <span className="gem-key__cooldown">
                            {model.api_model_id ? 'No correction selector' : 'Needs an ID first'}
                          </span>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}

const CONTRIBUTOR_TONE: Record<string, 'ok' | 'attention' | 'neutral'> = {
  ACTIVE: 'ok',
  SUSPENDED: 'attention',
  WITHDRAWN: 'neutral',
}

/**
 * The contributor pool. Two rules shape this screen: a key belongs to a person,
 * and capacity belongs to a Google Cloud project — never to a key. So the stats
 * count contributors and projects, and the capacity section sums independent
 * projects without ever adding a second key from the same project.
 */
function ContributorsTab({
  token,
  notify,
}: {
  token: string | null
  notify: (message: string | null) => void
}) {
  const [summary, reloadSummary] = useResource<ContributionSummary>(
    `contributions:${token ?? 'anonymous'}`,
    token ? (options) => contributionSummary(14, options) : null,
    { token },
  )
  const [keys, reloadKeys] = useResource<KeyPage>(
    `contributed-keys:${token ?? 'anonymous'}`,
    token ? (options) => listKeys({ limit: 200 }, options) : null,
    { token },
  )

  const act = useCallback(
    async (label: string, run: () => Promise<ApiResult<unknown>>) => {
      const result = await run()
      notify(result.status === 'ok' ? `${label} succeeded.` : `${label} failed: ${result.reason}`)
      reloadSummary()
      reloadKeys()
    },
    [notify, reloadSummary, reloadKeys],
  )

  if (summary.state !== 'ok') {
    return (
      <Panel title="Contributors" note={loadNote(summary)}>
        <LoadFailure state={summary} capability="GET /api/v1/admin/providers/contributions" />
      </Panel>
    )
  }

  const data = summary.data
  const aggregate = data.aggregate
  const contributed = keys.state === 'ok' ? keys.data.items.filter((key) => key.contributor_id) : []
  const active = data.contributors.filter((row) => row.contributor.status === 'ACTIVE')

  return (
    <div className="app-stack">
      <Panel title="Contributor pool" note={`window since ${stamp(data.window_started_at)}`}>
        <div className="gem-stats">
          <Stat
            label="Contributors"
            value={count(aggregate.contributors_total)}
            note={`${count(aggregate.contributors_by_status.ACTIVE ?? 0)} active`}
          />
          <Stat
            label="Suspended"
            value={count(aggregate.contributors_by_status.SUSPENDED ?? 0)}
            note="keys withheld, ciphertext kept"
          />
          <Stat
            label="Withdrawn"
            value={count(aggregate.contributors_by_status.WITHDRAWN ?? 0)}
            note="keys revoked for good"
          />
          <Stat
            label="Contributed keys"
            value={count(aggregate.keys_contributed)}
            note={`${count(aggregate.keys_eligible)} eligible · ${count(aggregate.keys_revoked)} revoked`}
          />
          <Stat
            label="Platform-owned keys"
            value={count(aggregate.platform_keys)}
            note="not attributed to a contributor"
          />
          <Stat
            label="Projects"
            value={count(aggregate.projects)}
            note={`${count(aggregate.shared_projects)} shared by more than one contributor`}
          />
          <Stat
            label="Requests today"
            value={count(aggregate.requests_today)}
            note="attributed ledger entries"
          />
          <Stat
            label="Requests in window"
            value={count(aggregate.requests_in_window)}
            note={`${count(aggregate.failures_in_window)} failures`}
          />
        </div>
        <p className="gem-footnote">{data.capacity.note}</p>
        <button type="button" className="btn btn--outline gem-refresh" onClick={reloadSummary}>
          Refresh
        </button>
      </Panel>

      <Panel title="Capacity across independent projects" note="One allowance per project, per model">
        {data.capacity.models.length === 0 ? (
          <p className="panel-copy">
            No contributed key is eligible, so there is no independent project capacity to count.
          </p>
        ) : (
          data.capacity.models.map((model) => <CapacityCard key={model.model} model={model} />)
        )}
      </Panel>

      <Panel title="Contributors" note={`${count(data.contributors.length)} records`}>
        {data.contributors.length === 0 ? (
          <p className="panel-copy">
            No one has contributed a key yet. Registration records who lent the key and which
            agreement they consented to — it does not validate the key.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table gem-table">
              <caption className="visually-hidden">Contributors and the keys they lent</caption>
              <thead>
                <tr>
                  <th scope="col">Contributor</th>
                  <th scope="col">Status</th>
                  <th scope="col">Consent</th>
                  <th scope="col">Keys eligible / total</th>
                  <th scope="col">Projects</th>
                  <th scope="col">Requests today</th>
                  <th scope="col">Requests in window</th>
                  <th scope="col">Last success</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {data.contributors.map((row) => (
                  <ContributorTableRow key={row.contributor.id} row={row} token={token} act={act} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel title="Register a contributor" note="Consent is recorded before any key">
        <RegisterContributor token={token} notify={notify} onDone={reloadSummary} />
      </Panel>

      <Panel
        title="Add a contributed key"
        note={`${count(active.length)} active contributor${active.length === 1 ? '' : 's'}`}
      >
        {active.length === 0 ? (
          <p className="panel-copy">
            Register an active contributor before adding a key to their record.
          </p>
        ) : (
          <AddContributorKey
            token={token}
            contributors={active}
            notify={notify}
            onDone={() => {
              reloadSummary()
              reloadKeys()
            }}
          />
        )}
      </Panel>

      <Panel
        title="Contributed keys"
        note={keys.state === 'ok' ? `${count(contributed.length)} keys` : loadNote(keys)}
      >
        {keys.state !== 'ok' ? (
          <LoadFailure state={keys} capability="GET /api/v1/admin/providers/keys" />
        ) : contributed.length === 0 ? (
          <p className="panel-copy">No key is attributed to a contributor.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table gem-table">
              <caption className="visually-hidden">Keys attributed to a contributor</caption>
              <thead>
                <tr>
                  <th scope="col">Key</th>
                  <th scope="col">Contributor</th>
                  <th scope="col">Project</th>
                  <th scope="col">Health</th>
                  <th scope="col">Requests</th>
                  <th scope="col">Last success</th>
                  <th scope="col">Revoked</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {contributed.map((key) => {
                  const contributorId = key.contributor_id
                  return (
                    <tr key={key.id}>
                      <td>
                        <span className="gem-key__label">{key.account_label}</span>
                        <span className="gem-key__fp mono">{key.key_fingerprint}</span>
                      </td>
                      <td>{key.contributor_name ?? '—'}</td>
                      <td className="mono">{key.project_id}</td>
                      <td>
                        <StatusChip tone={HEALTH_TONE[key.health] ?? 'neutral'}>{key.health}</StatusChip>
                      </td>
                      <td className="mono">{count(key.requests)}</td>
                      <td>{stamp(key.last_success_at)}</td>
                      <td>{stamp(key.revoked_at)}</td>
                      <td>
                        {contributorId && !key.revoked_at ? (
                          <button
                            type="button"
                            className="btn btn--outline btn--small"
                            disabled={!token}
                            onClick={() => {
                              const question = `Revoke ${key.account_label}? It stops being scheduled immediately and its stored ciphertext is destroyed.`
                              if (!window.confirm(question)) return
                              void act('Revocation', () =>
                                revokeContributorKey(contributorId, key.id, { token }),
                              )
                            }}
                          >
                            Revoke
                          </button>
                        ) : null}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

function CapacityCard({ model }: { model: CapacityModel }) {
  const totals = model.totals
  const unknown =
    totals.windows_unknown > 0
      ? ` · ${count(totals.windows_unknown)} window${totals.windows_unknown === 1 ? '' : 's'} with no known limit`
      : ''
  return (
    <section className="gem-model" aria-label={`Capacity for ${model.model}`}>
      <div className="gem-model__head">
        <h3 className="gem-model__name mono">{model.model}</h3>
        <StatusChip tone={totals.confidence === 'CONFIRMED' ? 'ok' : 'attention'}>
          {CONFIDENCE_LABEL[totals.confidence]}
        </StatusChip>
      </div>
      <p className="gem-model__reset">
        {count(totals.requests_per_minute_remaining)} requests/min and{' '}
        {count(totals.requests_per_day_remaining)} requests/day remaining across{' '}
        {count(totals.projects)} independent project{totals.projects === 1 ? '' : 's'}
        {unknown}
      </p>
      <ul className="gem-projects">
        {model.projects.map((project) => (
          <li key={project.project_id} className="gem-projects__row">
            <span className="gem-projects__id mono">{project.project_id}</span>
            <span className="gem-projects__keys">
              {count(project.contributors)} contributor{project.contributors === 1 ? '' : 's'} ·{' '}
              {count(project.keys)} key{project.keys === 1 ? '' : 's'} ·{' '}
              {count(project.requests_per_day_remaining)} requests left today
            </span>
            <StatusChip tone={project.confidence === 'CONFIRMED' ? 'ok' : 'attention'}>
              {CONFIDENCE_LABEL[project.confidence]}
            </StatusChip>
          </li>
        ))}
      </ul>
    </section>
  )
}

function ContributorTableRow({
  row,
  token,
  act,
}: {
  row: ContributorRow
  token: string | null
  act: (label: string, run: () => Promise<ApiResult<unknown>>) => Promise<void>
}) {
  const contributor = row.contributor
  const withdrawQuestion = `Withdraw ${contributor.display_name}? Every key they contributed is revoked and its ciphertext destroyed. This cannot be undone.`
  return (
    <tr>
      <td>
        <span className="gem-key__label">{contributor.display_name}</span>
        <span className="gem-key__fp mono">{contributor.id.slice(0, 8)}</span>
      </td>
      <td>
        <StatusChip tone={CONTRIBUTOR_TONE[contributor.status] ?? 'neutral'}>
          {contributor.status}
        </StatusChip>
        {contributor.status_reason ? (
          <span className="gem-key__cooldown">{contributor.status_reason}</span>
        ) : null}
      </td>
      <td>
        <span className="mono">{contributor.consent_version}</span>
        <span className="gem-key__fp">{stamp(contributor.consent_at)}</span>
      </td>
      <td className="mono">
        {count(row.keys_eligible)} / {count(row.keys_total)}
        {row.keys_revoked ? (
          <span className="gem-key__cooldown">{count(row.keys_revoked)} revoked</span>
        ) : null}
      </td>
      <td className="mono">{row.projects.length > 0 ? row.projects.join(', ') : '—'}</td>
      <td className="mono">{count(row.today.requests)}</td>
      <td className="mono">{count(row.window.requests)}</td>
      <td>{stamp(row.window.last_success_at)}</td>
      <td>
        <div className="gem-actions">
          {contributor.status === 'ACTIVE' ? (
            <button
              type="button"
              className="btn btn--outline btn--small"
              disabled={!token}
              onClick={() =>
                void act('Suspension', () =>
                  suspendContributor(contributor.id, 'Withheld by a platform administrator.', {
                    token,
                  }),
                )
              }
            >
              Suspend
            </button>
          ) : null}
          {contributor.status === 'SUSPENDED' ? (
            <button
              type="button"
              className="btn btn--outline btn--small"
              disabled={!token}
              onClick={() =>
                void act('Reinstatement', () => reinstateContributor(contributor.id, { token }))
              }
            >
              Reinstate
            </button>
          ) : null}
          {contributor.status !== 'WITHDRAWN' ? (
            <button
              type="button"
              className="btn btn--outline btn--small"
              disabled={!token}
              onClick={() => {
                if (!window.confirm(withdrawQuestion)) return
                void act('Withdrawal', () =>
                  withdrawContributor(contributor.id, 'Withdrawn by a platform administrator.', {
                    token,
                  }),
                )
              }}
            >
              Withdraw
            </button>
          ) : null}
        </div>
      </td>
    </tr>
  )
}

function RegisterContributor({
  token,
  notify,
  onDone,
}: {
  token: string | null
  notify: (message: string | null) => void
  onDone: () => void
}) {
  const [displayName, setDisplayName] = useState('')
  const [email, setEmail] = useState('')
  const [consentVersion, setConsentVersion] = useState('')
  const [reference, setReference] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!token) return
    setBusy(true)
    const result = await createContributor(
      {
        display_name: displayName.trim(),
        contact_email: email.trim() || undefined,
        consent_version: consentVersion.trim(),
        consent_reference: reference.trim() || undefined,
      },
      { token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      notify(`${result.data.display_name} registered as a contributor.`)
      setDisplayName('')
      setEmail('')
      setConsentVersion('')
      setReference('')
      onDone()
    } else {
      notify(`Registration failed: ${result.reason}`)
    }
  }

  return (
    <div className="gem-add">
      <form className="gem-add__form" onSubmit={submit}>
        <h3 className="gem-add__title">Contributor</h3>
        <label className="gem-field">
          <span>Display name</span>
          <input
            value={displayName}
            required
            maxLength={200}
            placeholder="who lent the key"
            onChange={(event) => setDisplayName(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Contact email</span>
          <input
            type="email"
            value={email}
            maxLength={320}
            placeholder="optional"
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Consent version</span>
          <input
            value={consentVersion}
            required
            maxLength={40}
            placeholder="2026-11"
            onChange={(event) => setConsentVersion(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Consent reference</span>
          <input
            value={reference}
            maxLength={200}
            placeholder="optional: agreement id or date"
            onChange={(event) => setReference(event.target.value)}
          />
        </label>
        <button type="submit" className="btn btn--primary" disabled={busy || !token}>
          {busy ? 'Registering…' : 'Register contributor'}
        </button>
        <p className="gem-add__hint">
          A contribution without a recorded agreement is refused by the engine; the reference is the
          evidence an operator would cite if the use of a key were ever questioned.
        </p>
      </form>
    </div>
  )
}

function AddContributorKey({
  token,
  contributors,
  notify,
  onDone,
}: {
  token: string | null
  contributors: ContributorRow[]
  notify: (message: string | null) => void
  onDone: () => void
}) {
  const [contributorId, setContributorId] = useState(contributors[0]?.contributor.id ?? '')
  const [projectId, setProjectId] = useState('')
  const [apiKeyValue, setApiKeyValue] = useState('')
  const [label, setLabel] = useState('')
  const [tier, setTier] = useState<'FREE' | 'PAID' | 'UNKNOWN'>('UNKNOWN')
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!token || !contributorId) return
    setBusy(true)
    const result = await addContributorKey(
      contributorId,
      {
        project_id: projectId.trim(),
        api_key: apiKeyValue.trim(),
        label: label.trim() || undefined,
        tier,
      },
      { token },
    )
    setBusy(false)
    if (result.status === 'ok') {
      notify(`Key ${result.data.account_label} registered in ${result.data.project_id}.`)
      setApiKeyValue('')
      setProjectId('')
      setLabel('')
      onDone()
    } else {
      notify(`Registration failed: ${result.reason}`)
    }
  }

  return (
    <div className="gem-add">
      <form className="gem-add__form" onSubmit={submit}>
        <h3 className="gem-add__title">Key and its project</h3>
        <label className="gem-field">
          <span>Contributor</span>
          <select value={contributorId} onChange={(event) => setContributorId(event.target.value)}>
            {contributors.map((row) => (
              <option key={row.contributor.id} value={row.contributor.id}>
                {row.contributor.display_name}
              </option>
            ))}
          </select>
        </label>
        <label className="gem-field">
          <span>Google Cloud project</span>
          <input
            value={projectId}
            required
            maxLength={100}
            placeholder="their-gcp-project"
            onChange={(event) => setProjectId(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>API key</span>
          <input
            type="password"
            value={apiKeyValue}
            required
            minLength={8}
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => setApiKeyValue(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Label</span>
          <input
            value={label}
            maxLength={120}
            placeholder="optional"
            onChange={(event) => setLabel(event.target.value)}
          />
        </label>
        <label className="gem-field">
          <span>Tier</span>
          <select value={tier} onChange={(event) => setTier(event.target.value as typeof tier)}>
            <option value="UNKNOWN">Unverified</option>
            <option value="FREE">Free</option>
            <option value="PAID">Paid</option>
          </select>
        </label>
        <button type="submit" className="btn btn--primary" disabled={busy || !token}>
          {busy ? 'Registering…' : 'Add key'}
        </button>
        <p className="gem-add__hint">
          The key is encrypted before storage and never returned by the API. Two keys in one project
          still share that project&rsquo;s allowance, so this screen counts projects, not keys.
        </p>
      </form>
    </div>
  )
}

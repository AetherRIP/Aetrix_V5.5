import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel, StatusChip } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { useAuth } from '../lib/auth/AuthProvider'
import type { ApiResult, RequestOptions } from '../lib/api/client'
import {
  addKey,
  alerts as fetchAlerts,
  importKeys,
  listKeys,
  overview as fetchOverview,
  removeKey,
  setKeyEnabled,
  usage as fetchUsage,
  validateKey,
  type Confidence,
  type FleetAlert,
  type FleetKey,
  type FleetOverview,
  type ImportRow,
  type KeyPage,
  type ProjectRow,
  type QuotaWindow,
  type UsageReport,
} from '../lib/api/gemini'

export const Route = createFileRoute('/_app/platform/gemini')({
  head: () => ({ meta: [{ title: 'Gemini fleet · Aetrix' }] }),
  component: PlatformGemini,
})

const TABS = ['Overview', 'API keys', 'Projects', 'Usage', 'Alerts'] as const
type Tab = (typeof TABS)[number]

type Loaded<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

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
  COOLDOWN: 'attention',
  UNKNOWN: 'attention',
  INVALID: 'neutral',
  DISABLED: 'neutral',
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

function dayLabel(value: string): string {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' })
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
          <h1 className="app-card__title">Gemini fleet</h1>
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
        {tab === 'Projects' ? (
          <ProjectsTab state={overview} onRefresh={reloadOverview} />
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
  const windows = data.projects_detail.flatMap((project) =>
    project.estimates.map((estimate) => estimate.requests_per_day),
  )
  const known = windows.filter((window) => window.limit !== null)
  if (known.length === 0) return 'no known limit to subtract from'
  const left = known.reduce((total, window) => total + (window.remaining ?? 0), 0)
  const confirmed = known.every((window) => window.confidence === 'CONFIRMED')
  return `${count(left)} requests left today across ${known.length} project-model${
    known.length === 1 ? '' : 's'
  } (${confirmed ? 'confirmed' : 'estimated'})`
}

function OverviewTab({ state, onRefresh }: { state: Loaded<FleetOverview>; onRefresh: () => void }) {
  if (state.state !== 'ok') {
    return (
      <Panel title="Overview" note="Awaits the engine">
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
          <Stat label="Registered keys" value={count(data.keys_total)} note={`${count(data.projects)} Google Cloud projects`} />
          <Stat label="Healthy keys" value={count(health.HEALTHY ?? 0)} note="last call succeeded" />
          <Stat label="Disabled" value={count(health.DISABLED ?? 0)} note="withheld by an operator" />
          <Stat label="Invalid" value={count(health.INVALID ?? 0)} note="rejected by Google" />
          <Stat label="Requests today" value={count(data.requests_today)} note="Aetrix ledger, since Pacific midnight" />
          <Stat
            label="Tokens today"
            value={count(data.input_tokens_today + data.output_tokens_today)}
            note={`${count(data.input_tokens_today)} in · ${count(data.output_tokens_today)} out`}
          />
          <Stat label="Failures today" value={count(data.failures_today)} note={`error rate ${share(data.error_rate_today)}`} />
          <Stat label="Next daily reset" value={stamp(data.reset_at)} note="midnight Pacific" />
        </div>
        <p className="gem-footnote">
          Estimated available capacity: {capacityNote(data)}.
        </p>
        <button type="button" className="btn btn--outline gem-refresh" onClick={onRefresh}>
          Refresh
        </button>
      </Panel>

      <Panel title="Projects" note={`${count(data.projects)} pooled allowances`}>
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
              {project.invalid ? ` · ${count(project.invalid)} invalid` : ''}
              {project.disabled ? ` · ${count(project.disabled)} disabled` : ''}
            </span>
            {project.cooldown_until && new Date(project.cooldown_until) > new Date() ? (
              <StatusChip tone="attention">Paused until {stamp(project.cooldown_until)}</StatusChip>
            ) : worst ? (
              <StatusChip tone="attention">Quota exhausted ({worst.model})</StatusChip>
            ) : (
              <StatusChip tone="ok">Eligible</StatusChip>
            )}
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
      <Panel title="Projects" note="Awaits the engine">
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
          <p className="gem-footnote">
            Shared allowance: every key below is metered against this project, not against itself.
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

  return (
    <div className="app-stack">
      <Panel title="API key management" note={keys.state === 'ok' ? `${count(keys.data.total)} keys` : 'Awaits the engine'}>
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
                {['HEALTHY', 'COOLDOWN', 'UNKNOWN', 'INVALID', 'DISABLED'].map((value) => (
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
          <KeyTable keys={keys.data.items} token={token} act={act} />
        ) : (
          <LoadFailure state={keys} capability="GET /api/v1/admin/providers/keys" />
        )}
      </Panel>
    </div>
  )
}

function KeyTable({
  keys,
  token,
  act,
}: {
  keys: FleetKey[]
  token: string | null
  act: (label: string, run: () => Promise<ApiResult<unknown>>) => Promise<void>
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
                {key.cooldown_until ? <span className="gem-key__cooldown">until {stamp(key.cooldown_until)}</span> : null}
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
                    disabled={!token}
                    onClick={() => void act('Validation', () => validateKey(key.id, { token }))}
                  >
                    Validate
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
      <Panel title="Usage analytics" note="Awaits the engine">
        <LoadFailure state={report} capability="GET /api/v1/admin/providers/usage" />
      </Panel>
    )
  }
  const data = report.data
  const peak = Math.max(1, ...data.daily.map((row) => row.requests))

  return (
    <div className="app-stack">
      <Panel title="Daily requests" note={`since ${stamp(data.since)}`}>
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
                <span className="gem-chart__day">{dayLabel(row.day)}</span>
                <span className="gem-chart__sub">
                  {count(row.input_tokens + row.output_tokens)} tok · {count(row.failures)} fail
                </span>
              </li>
            ))}
          </ol>
        )}
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
      <Panel title="Alerts" note={state.state === 'ok' ? `${count(state.data.length)} open` : 'Awaits the engine'}>
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
        title="Google-reported quota is not synchronised"
        capability="Cloud Monitoring quota metrics (not configured)"
      >
        <p>
          No Google credential is configured, so this build cannot read Cloud Monitoring or any
          authoritative quota figure. Limits shown as <code>ESTIMATED</code> are Aetrix policy;
          check AI Studio for the project&rsquo;s real allowance before relying on them.
        </p>
      </StatePanel>
    </div>
  )
}

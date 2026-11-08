import { useCallback, useEffect, useState } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel } from '../components/app/PageBlocks'
import type { ApiResult } from '../lib/api/client'
import { env, isApiConfigured } from '../lib/env'
import { healthService, type EngineHealth, type EngineReadiness } from '../lib/services'

export const Route = createFileRoute('/_app/platform/health')({
  component: PlatformHealth,
})

type Probe<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T; latencyMs: number }
  | { state: 'unavailable'; reason: string }
  | { state: 'error'; reason: string; code?: number }

/**
 * Times one request and normalises every outcome into a renderable state. The
 * engine client already distinguishes "not configured" from "request failed";
 * this keeps that distinction instead of collapsing it into a red dot.
 */
async function measure<T>(read: () => Promise<ApiResult<T>>): Promise<Probe<T>> {
  const started = performance.now()
  const result = await read()
  const latencyMs = Math.round(performance.now() - started)
  if (result.status === 'ok') return { state: 'ok', data: result.data, latencyMs }
  if (result.status === 'unavailable') return { state: 'unavailable', reason: result.reason }
  return { state: 'error', reason: result.reason, code: result.code }
}

const checkedFormat = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

function endpointHost(value: string): string {
  try {
    return new URL(value).host
  } catch {
    return value
  }
}

function Metric({
  label,
  value,
  note,
}: {
  label: string
  value: string
  note: string
}) {
  return (
    <div className="hub-stat">
      <dt className="hub-stat__label">{label}</dt>
      <dd className="hub-stat__value mono">{value}</dd>
      <dd className="hub-stat__note">{note}</dd>
    </div>
  )
}

/**
 * Without a configured engine origin the screen has nothing to call. It says
 * so rather than rendering a green light that no request produced.
 */
function UnconfiguredHealth() {
  return (
    <div className="app-stack">
      <Panel title="Service state" note="As far as this build can tell">
        <dl className="hub-stats">
          <Metric label="API" value="—" note="not configured" />
          <Metric label="Worker" value="—" note="no deployment" />
          <Metric label="Database" value="—" note="not reachable from here" />
          <Metric label="Provider" value="—" note="UNVERIFIED" />
        </dl>
      </Panel>

      <Panel title="Components" note="What each one needs">
        <CapabilityList
          items={[
            {
              label: 'HTTP API',
              detail: 'VITE_AETRIX_API_URL is absent from this build, so no endpoint is called.',
              state: 'pending',
              icon: 'server',
            },
            {
              label: 'Worker',
              detail: 'Separate process, leases jobs with FOR UPDATE SKIP LOCKED.',
              state: 'pending',
              icon: 'pulse',
            },
            {
              label: 'PostgreSQL',
              detail: 'Supabase in development; RLS guard runs in CI.',
              state: 'pending',
              icon: 'records',
            },
            {
              label: 'AI provider',
              detail: 'Live Gemini responses are UNVERIFIED; no DRAFT exists.',
              state: 'pending',
              icon: 'blueprint',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="This build has no engine address"
        capability="VITE_AETRIX_API_URL at build time"
      >
        <p>
          The health screen reads the engine’s own <code>/health</code> and <code>/ready</code>{' '}
          routes. Both are implemented; this build was compiled without an origin to call, so
          it cannot report uptime or database readiness.
        </p>
      </StatePanel>
    </div>
  )
}

function LiveHealth() {
  const [health, setHealth] = useState<Probe<EngineHealth>>({ state: 'loading' })
  const [ready, setReady] = useState<Probe<EngineReadiness>>({ state: 'loading' })
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [tick, setTick] = useState(0)

  const refresh = useCallback(() => setTick((value) => value + 1), [])

  useEffect(() => {
    let live = true
    setHealth({ state: 'loading' })
    setReady({ state: 'loading' })
    void Promise.all([measure(() => healthService.live()), measure(() => healthService.ready())]).then(
      ([nextHealth, nextReady]) => {
        if (!live) return
        setHealth(nextHealth)
        setReady(nextReady)
        setCheckedAt(new Date())
      },
    )
    return () => {
      live = false
    }
  }, [tick])

  const loading = health.state === 'loading' || ready.state === 'loading'
  const healthFailed = health.state === 'error'

  const apiValue = loading ? 'Checking…' : health.state === 'ok' ? 'Reachable' : 'Unreachable'
  const apiNote =
    health.state === 'ok'
      ? `${health.data.service} ${health.data.version} · ${health.latencyMs} ms`
      : health.state === 'loading'
        ? 'GET /health'
        : health.state === 'error'
          ? `GET /health failed${health.code ? ` (${health.code})` : ''}`
          : 'no endpoint configured'

  const databaseValue = loading ? 'Checking…' : ready.state === 'ok' ? 'Ready' : 'Not ready'
  const databaseNote =
    ready.state === 'ok'
      ? `${ready.data.database} · ${ready.latencyMs} ms`
      : ready.state === 'loading'
        ? 'GET /ready'
        : ready.state === 'error'
          ? `GET /ready failed${ready.code ? ` (${ready.code})` : ''}`
          : 'readiness not checked'

  return (
    <div className="app-stack">
      <Panel
        title="Service state"
        note={checkedAt ? `checked ${checkedFormat.format(checkedAt)}` : 'Checking the engine'}
      >
        <dl className="hub-stats" aria-live="polite" aria-busy={loading}>
          <Metric label="API" value={apiValue} note={apiNote} />
          <Metric
            label="Worker"
            value="Not checked"
            note="separate process; the API never starts it"
          />
          <Metric label="Database" value={databaseValue} note={databaseNote} />
          <Metric label="Provider" value="UNVERIFIED" note="live Gemini is not exercised here" />
        </dl>
        <button
          type="button"
          className="btn btn--outline"
          onClick={refresh}
          disabled={loading}
        >
          {loading ? 'Checking…' : 'Check again'}
        </button>
      </Panel>

      <Panel title="Endpoint" note={endpointHost(env.apiBaseUrl)}>
        <p className="panel-copy">
          This build calls the correction engine over HTTPS at{' '}
          <code>{endpointHost(env.apiBaseUrl)}</code>. The address is compiled from{' '}
          <code>VITE_AETRIX_API_URL</code>; the bundle carries no database credential, provider
          key or signing secret. Liveness and readiness were each read once in the browser, and
          the figures above are their answers.
        </p>
      </Panel>

      <Panel title="Components" note="What each one needs">
        <CapabilityList
          items={[
            {
              label: 'HTTP API',
              detail:
                health.state === 'ok'
                  ? `FastAPI answered /health in ${health.latencyMs} ms.`
                  : 'No answer from /health yet.',
              state: health.state === 'ok' ? 'available' : 'pending',
              icon: 'server',
            },
            {
              label: 'Worker',
              detail: 'Separate process, leases jobs with FOR UPDATE SKIP LOCKED.',
              state: 'pending',
              icon: 'pulse',
            },
            {
              label: 'PostgreSQL',
              detail:
                ready.state === 'ok'
                  ? 'The readiness query SELECT 1 succeeded.'
                  : 'No successful readiness query yet.',
              state: ready.state === 'ok' ? 'available' : 'pending',
              icon: 'records',
            },
            {
              label: 'AI provider',
              detail: 'Live Gemini responses are UNVERIFIED; no DRAFT exists.',
              state: 'pending',
              icon: 'blueprint',
            },
          ]}
        />
      </Panel>

      {healthFailed ? (
        <StatePanel
          tone="error"
          title="The engine did not answer"
          capability={`GET ${env.apiBaseUrl.replace(/\/$/, '')}/health`}
        >
          <p>{health.reason}</p>
          <p>
            Nothing above is an estimate: an unreachable endpoint is reported as unreachable,
            not as downtime or as a healthy service.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

function PlatformHealth() {
  return isApiConfigured ? <LiveHealth /> : <UnconfiguredHealth />
}

import { createFileRoute } from '@tanstack/react-router'
import { ComponentHealthTable, SystemStatusGrid } from '../components/app/SystemStatus'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel, type LineItem } from '../components/app/PageBlocks'
import { useSystemStatus } from '../lib/api/useSystemStatus'
import { env, isApiConfigured } from '../lib/env'

export const Route = createFileRoute('/_app/platform/health')({
  component: PlatformHealth,
})

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

function Metric({ label, value, note }: { label: string; value: string; note: string }) {
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
          <Metric label="API" value="—" note="unknown without an engine address" />
          <Metric label="Worker" value="—" note="unknown without an engine address" />
          <Metric label="Database" value="—" note="unknown without an engine address" />
          <Metric label="Provider" value="—" note="unknown without an engine address" />
        </dl>
      </Panel>

      <Panel title="Components" note="Not observable from this build">
        <p className="panel-copy">
          This build was compiled without <code>VITE_AETRIX_API_URL</code>, so the HTTP API, the
          background worker, PostgreSQL and the AI provider are all <strong>unknown</strong> here.
          None of them is reported as deployed, available or unavailable: no request was made that
          could observe them, and a status the engine never sent would be invented.
        </p>
      </Panel>

      <StatePanel
        tone="wip"
        title="This build has no engine address"
        capability="VITE_AETRIX_API_URL at build time"
      >
        <p>
          The health screen reads the engine’s own <code>/status</code> route, which reports the
          API, readiness, database, worker and provider separately. This build was compiled
          without an origin to call, so it cannot report any of them.
        </p>
      </StatePanel>
    </div>
  )
}

function LiveHealth() {
  const [status, refresh, checkedAt] = useSystemStatus()
  const features = status.state === 'ok' ? status.data.features : null

  return (
    <div className="app-stack">
      <Panel
        title="Service state"
        note={checkedAt ? `checked ${checkedFormat.format(checkedAt)}` : 'Reading GET /status'}
      >
        <SystemStatusGrid
          value={status}
          checkedAt={checkedAt}
          footer={
            <button
              type="button"
              className="btn btn--outline"
              onClick={refresh}
              disabled={status.state === 'loading'}
            >
              {status.state === 'loading' ? 'Checking…' : 'Check again'}
            </button>
          }
        />
        <p className="panel-copy">
          A 200 from this screen means only that the API answered. Each row is a separate
          observation: the worker is read from its own heartbeat, readiness from a real database
          query, and a provider is never reported as available because none was called.
        </p>
      </Panel>

      <Panel
        title="Components"
        note="Deployment, operation and readiness, each reported separately"
      >
        <ComponentHealthTable value={status} />
        <p className="panel-copy">
          Deployment is not operation: a worker can be deployed and temporarily unavailable, and a
          provider can be configured while its last live call is unverified. Readiness is a
          capability fact, so the worker and the provider stay “not ready” while marking is
          unimplemented — a successful provider call proves reachability, not correct marking.
        </p>
      </Panel>

      <Panel title="Feature availability" note="Reported by the engine">
        {features ? (
          <CapabilityList
            items={features.map(
              (feature): LineItem => ({
                label: feature.name,
                detail: feature.reason,
                state: feature.state === 'available' ? 'available' : 'unimplemented',
                icon: 'blueprint',
              }),
            )}
          />
        ) : (
          <p className="panel-copy">
            The engine has not answered, so feature availability is unknown. Nothing here is an
            estimate.
          </p>
        )}
      </Panel>

      <Panel title="Endpoint" note={endpointHost(env.apiBaseUrl)}>
        <p className="panel-copy">
          This build calls the correction engine over HTTPS at{' '}
          <code>{endpointHost(env.apiBaseUrl)}</code>. The address is compiled from{' '}
          <code>VITE_AETRIX_API_URL</code>; the bundle carries no database credential, provider
          key or signing secret.
        </p>
      </Panel>

      {status.state === 'error' ? (
        <StatePanel
          tone="error"
          title="The engine did not answer"
          capability={`GET ${env.apiBaseUrl.replace(/\/$/, '')}/status`}
        >
          <p>{status.reason}</p>
          <p>
            An unreachable endpoint is reported as unreachable — not as downtime, and not as a
            healthy service.
          </p>
        </StatePanel>
      ) : null}
    </div>
  )
}

function PlatformHealth() {
  return isApiConfigured ? <LiveHealth /> : <UnconfiguredHealth />
}

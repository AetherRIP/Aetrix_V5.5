import type { ReactNode } from 'react'
import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import {
  DEPLOYMENT_LABEL,
  OPERATIONAL_CHIP,
  READINESS_LABEL,
} from '../components/app/SystemStatus'
import { STATUS_POLL_MS, useSystemStatus } from '../lib/api/useSystemStatus'
import type { SystemStatusState } from '../lib/api/useSystemStatus'
import { env, isApiConfigured } from '../lib/env'
import type { ComponentHealth, SubsystemState } from '../lib/services'

export const Route = createFileRoute('/_app/platform/health')({
  component: PlatformHealth,
})

type ChannelKey = 'api' | 'engine' | 'readiness' | 'database' | 'worker' | 'provider'

type Channel = { key: ChannelKey; label: string; ok: string }

/**
 * The six channels the engine reports separately. The healthy word differs per
 * channel on purpose: "Connected" is transport, "Online" is a process, "Ready"
 * is a capability, and "Verified" is a recorded call.
 */
const CHANNELS: readonly Channel[] = [
  { key: 'api', label: 'API', ok: 'Connected' },
  { key: 'engine', label: 'Correction engine', ok: 'Online' },
  { key: 'readiness', label: 'Readiness', ok: 'Ready' },
  { key: 'database', label: 'Database', ok: 'Connected' },
  { key: 'worker', label: 'Worker', ok: 'Online' },
  { key: 'provider', label: 'Provider', ok: 'Verified' },
]

const STATE_WORD: Record<SubsystemState, string> = {
  ok: 'Operational',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
  unknown: 'Unknown',
  not_implemented: 'Not implemented',
}

// A feature the engine reports as blocked is not the same as one it has never
// built: the playtest found "Marking: Available" beside an unavailable worker.
const FEATURE_CHIP: Record<
  'available' | 'degraded' | 'unavailable' | 'not_implemented',
  { tone: 'ok' | 'attention' | 'neutral'; text: string }
> = {
  available: { tone: 'ok', text: 'Available' },
  degraded: { tone: 'attention', text: 'Degraded' },
  unavailable: { tone: 'attention', text: 'Unavailable' },
  not_implemented: { tone: 'neutral', text: 'Not implemented' },
}

// Times are shown in UTC with the suffix, so two operators in different places
// read the same stamp from the same read.
const clockFormat = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  timeZone: 'UTC',
})

const stampFormat = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
})

function stamp(value: string | null): string {
  if (!value) return 'not recorded'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : `${stampFormat.format(parsed)} UTC`
}

function endpointHost(value: string): string {
  if (!value) return 'No origin compiled'
  try {
    return new URL(value).host
  } catch {
    return value
  }
}

type Readout = { word: string; summary: string; detail: string | null; tone: string }

/** One channel's own answer, or the explicit reason this build has none. */
function readout(value: SystemStatusState, channel: Channel): Readout {
  if (value.state === 'loading') {
    return {
      word: 'Reading',
      summary: 'Waiting for the first answer.',
      detail: null,
      tone: 'loading',
    }
  }
  if (value.state === 'unavailable') {
    return {
      word: STATE_WORD.unknown,
      summary: 'This build has no engine origin to call.',
      detail: null,
      tone: 'unknown',
    }
  }
  if (value.state === 'error') {
    return {
      word: STATE_WORD.unknown,
      summary: 'No answer reached this channel.',
      detail: null,
      tone: 'unknown',
    }
  }
  const observed = value.data[channel.key]
  return {
    word: observed.state === 'ok' ? channel.ok : STATE_WORD[observed.state],
    summary: observed.summary,
    detail: observed.detail,
    tone: observed.state,
  }
}

type Verdict = { word: string; note: string; tone: 'ok' | 'error' | 'idle' }

/** The page states what it observed — not a score assembled from the channels. */
function verdict(value: SystemStatusState): Verdict {
  if (value.state === 'loading') {
    return {
      word: 'Reading',
      note: `Waiting for the first answer from GET /status. This screen re-reads every ${
        STATUS_POLL_MS / 1000
      } seconds.`,
      tone: 'idle',
    }
  }
  if (value.state === 'unavailable') {
    return {
      word: 'Not observable',
      note: 'This build was compiled without an engine origin, so there is nothing to read.',
      tone: 'idle',
    }
  }
  if (value.state === 'error') {
    return { word: 'No answer', note: value.reason, tone: 'error' }
  }
  return {
    word: 'Answered',
    note: 'The API answered this read. Nothing below is inferred from it.',
    tone: 'ok',
  }
}

function HealthHead({ action }: { action?: ReactNode }) {
  return (
    <header className="health-head">
      <div className="health-head__copy">
        <h1 className="health-head__title">System health</h1>
        <p className="health-head__lede">
          What the engine reports about itself. An answer here proves the API replied; the
          database, worker and provider are read separately below.
        </p>
      </div>
      {action ? <div className="health-head__action">{action}</div> : null}
    </header>
  )
}

function ReadLine({ value, checkedAt }: { value: SystemStatusState; checkedAt: Date | null }) {
  return (
    <p className="health-read mono" aria-live="polite">
      <span>GET /status</span>
      {value.state === 'ok' ? (
        <span>answered in {value.latencyMs} ms</span>
      ) : value.state === 'loading' ? (
        <span>first read</span>
      ) : value.state === 'unavailable' ? (
        <span>no engine origin</span>
      ) : (
        <span>no response</span>
      )}
      {checkedAt ? <span>checked {clockFormat.format(checkedAt)} UTC</span> : null}
      <span>re-reads every {STATUS_POLL_MS / 1000} s</span>
    </p>
  )
}

function Identity({ value }: { value: SystemStatusState }) {
  const data = value.state === 'ok' ? value.data : null
  return (
    <dl className="health-identity" aria-label="Engine identity">
      <div>
        <dt>Service</dt>
        <dd>{data?.service ?? '—'}</dd>
      </div>
      <div>
        <dt>Version</dt>
        <dd>{data?.version ?? '—'}</dd>
      </div>
      <div>
        <dt>Environment</dt>
        <dd>{data?.environment ?? '—'}</dd>
      </div>
    </dl>
  )
}

function Instrument({
  value,
  checkedAt,
}: {
  value: SystemStatusState
  checkedAt: Date | null
}) {
  const summary = verdict(value)
  return (
    <section className="health-instrument" data-tone={summary.tone} aria-label="Current engine read">
      <div className="health-verdict-pane">
        <ReadLine value={value} checkedAt={checkedAt} />
        <p className="health-verdict">{summary.word}</p>
        <p className="health-verdict__note">{summary.note}</p>
        <Identity value={value} />
      </div>

      <ul className="health-channels" aria-label="Subsystem states">
        {CHANNELS.map((channel) => {
          const read = readout(value, channel)
          return (
            <li
              className="health-channel"
              key={channel.key}
              data-state={read.tone}
              data-channel={channel.key}
            >
              <div className="health-channel__head">
                <span className="health-lamp" aria-hidden="true" />
                <span className="health-channel__label mono">{channel.label}</span>
              </div>
              <strong className="health-channel__state">{read.word}</strong>
              <p className="health-channel__summary">{read.summary}</p>
              {read.detail ? <p className="health-channel__detail">{read.detail}</p> : null}
            </li>
          )
        })}
      </ul>
    </section>
  )
}

function ComponentRow({ component }: { component: ComponentHealth }) {
  const operational = OPERATIONAL_CHIP[component.operational]
  return (
    <li className="health-component">
      <div className="health-component__head">
        <h3 className="health-component__name">{component.name}</h3>
        <span className="health-component__success mono">
          Last success {stamp(component.last_success_at)}
        </span>
      </div>

      <dl className="health-facts">
        <div>
          <dt>Deployment</dt>
          <dd>{DEPLOYMENT_LABEL[component.deployment]}</dd>
        </div>
        <div>
          <dt>Operation</dt>
          <dd>
            <span className="chip app-chip" data-tone={operational.tone}>
              {operational.text}
            </span>
          </dd>
        </div>
        <div>
          <dt>Readiness</dt>
          <dd>{READINESS_LABEL[component.readiness]}</dd>
        </div>
      </dl>

      <p className="health-component__diagnostic">{component.diagnostic}</p>
      {component.last_failure ? (
        <p className="health-component__failure mono">
          Last failure {stamp(component.last_failure_at)} — {component.last_failure}
        </p>
      ) : null}
    </li>
  )
}

function Components({ value }: { value: SystemStatusState }) {
  const components = value.state === 'ok' ? (value.data.components ?? []) : []
  return (
    <section className="health-ledger" aria-labelledby="health-components">
      <header className="health-ledger__head">
        <h2 id="health-components">Components</h2>
        <p className="mono">
          {value.state === 'ok' ? `reported ${stamp(value.data.checked_at)}` : 'not observed'}
        </p>
      </header>

      {value.state === 'loading' ? (
        <p className="health-empty">Reading component health…</p>
      ) : null}
      {value.state === 'error' ? (
        <p className="health-empty">
          No component was observed: the engine did not answer this request.
        </p>
      ) : null}
      {value.state === 'unavailable' ? (
        <p className="health-empty">
          No component was observed: this build has no engine origin to call.
        </p>
      ) : null}
      {value.state === 'ok' && components.length === 0 ? (
        <p className="health-empty">
          This engine build did not report component health, so nothing is assumed about the
          worker or the provider.
        </p>
      ) : null}

      {components.length > 0 ? (
        <ul className="health-components">
          {components.map((component) => (
            <ComponentRow key={component.name} component={component} />
          ))}
        </ul>
      ) : null}
    </section>
  )
}

function Features({ value }: { value: SystemStatusState }) {
  const features = value.state === 'ok' ? value.data.features : []
  return (
    <section className="health-block" aria-labelledby="health-features">
      <header className="health-block__head">
        <h2 className="health-block__title" id="health-features">
          Feature availability
        </h2>
      </header>

      {value.state === 'ok' ? (
        features.length > 0 ? (
          <ul className="health-features">
            {features.map((feature) => {
              const chip = FEATURE_CHIP[feature.state]
              return (
                <li className="health-feature" key={feature.name}>
                  <div className="health-feature__row">
                    <span className="health-feature__name">{feature.name}</span>
                    <span className="chip app-chip" data-tone={chip.tone}>
                      {chip.text}
                    </span>
                  </div>
                  <p className="health-feature__reason">{feature.reason}</p>
                </li>
              )
            })}
          </ul>
        ) : (
          <p className="health-empty">The engine reported no feature entry.</p>
        )
      ) : (
        <p className="health-empty">
          {value.state === 'unavailable'
            ? 'This build has no engine origin, so no feature can be reported.'
            : 'Feature availability is unknown until the engine answers.'}
        </p>
      )}
    </section>
  )
}

function ReadingGuide() {
  return (
    <section className="health-block" aria-labelledby="health-guide">
      <header className="health-block__head">
        <h2 className="health-block__title" id="health-guide">
          Reading the states
        </h2>
      </header>
      <dl className="health-defs">
        <div>
          <dt>Deployment</dt>
          <dd>The component exists and has run.</dd>
        </div>
        <div>
          <dt>Operation</dt>
          <dd>What it is doing at this read.</dd>
        </div>
        <div>
          <dt>Readiness</dt>
          <dd>Whether it can do its own job.</dd>
        </div>
      </dl>
      <p className="health-defs__note">
        A deployed worker can still be unavailable, and a configured provider can still be
        unverified. No row is upgraded from another.
      </p>
    </section>
  )
}

function Endpoint() {
  return (
    <section className="health-block" aria-labelledby="health-endpoint">
      <header className="health-block__head">
        <h2 className="health-block__title" id="health-endpoint">
          Endpoint
        </h2>
        <p className="health-block__note mono">{endpointHost(env.apiBaseUrl)}</p>
      </header>
      <dl className="health-defs">
        <div>
          <dt>Route</dt>
          <dd className="mono">GET /status</dd>
        </div>
        <div>
          <dt>Origin</dt>
          <dd className="mono">{endpointHost(env.apiBaseUrl)}</dd>
        </div>
        <div>
          <dt>Compiled from</dt>
          <dd className="mono">VITE_AETRIX_API_URL</dd>
        </div>
        <div>
          <dt>Secrets</dt>
          <dd>None in this bundle: no database credential, provider key or signing secret.</dd>
        </div>
      </dl>
    </section>
  )
}

function LiveHealth() {
  const [status, refresh, checkedAt] = useSystemStatus()

  return (
    <div className="hub-main health-page">
      <HealthHead
        action={
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

      <Instrument value={status} checkedAt={checkedAt} />

      <div className="health-board">
        <Components value={status} />
        <aside className="health-rail" aria-label="Platform detail">
          <Features value={status} />
          <ReadingGuide />
          <Endpoint />
        </aside>
      </div>

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

/**
 * Without a configured engine origin the screen has nothing to call. It says
 * so rather than rendering a green light that no request produced.
 */
function UnconfiguredHealth() {
  const value: SystemStatusState = {
    state: 'unavailable',
    reason: 'This build was compiled without VITE_AETRIX_API_URL.',
  }

  return (
    <div className="hub-main health-page">
      <HealthHead />
      <Instrument value={value} checkedAt={null} />

      <div className="health-board">
        <Components value={value} />
        <aside className="health-rail" aria-label="Platform detail">
          <Features value={value} />
          <ReadingGuide />
          <Endpoint />
        </aside>
      </div>

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

function PlatformHealth() {
  return isApiConfigured ? <LiveHealth /> : <UnconfiguredHealth />
}

import type { ReactNode } from 'react'
import type {
  ComponentDeployment,
  ComponentOperational,
  ComponentReadiness,
  SubsystemState,
} from '../../lib/services'
import type { SystemStatusState } from '../../lib/api/useSystemStatus'

export type SubsystemKey = 'api' | 'engine' | 'readiness' | 'database' | 'worker' | 'provider'

const LABEL: Record<SubsystemKey, string> = {
  api: 'API',
  engine: 'Correction engine',
  readiness: 'Readiness',
  database: 'Database',
  worker: 'Worker',
  provider: 'Provider',
}

/**
 * What a healthy subsystem is called. The wording matters: "Connected" is a
 * transport fact, "Online" a process fact, "Ready" a capability fact. The card
 * never upgrades one into another.
 */
const OK_LABEL: Record<SubsystemKey, string> = {
  api: 'Connected',
  engine: 'Online',
  readiness: 'Ready',
  database: 'Connected',
  worker: 'Online',
  // A provider reaches `ok` only from a recorded successful call, so the honest
  // word is "Verified", never "Configured" (which says nothing about working).
  provider: 'Verified',
}

const STATE_LABEL: Record<SubsystemState, string> = {
  ok: 'Operational',
  degraded: 'Degraded',
  unavailable: 'Unavailable',
  unknown: 'Unknown',
  not_implemented: 'Not implemented',
}

const checkedFormat = new Intl.DateTimeFormat('en-GB', {
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

const stampFormat = new Intl.DateTimeFormat('en-GB', {
  dateStyle: 'short',
  timeStyle: 'medium',
})

function stamp(value: string | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : stampFormat.format(parsed)
}

type Cell = { value: string; note: string; state: SubsystemState | 'probe' }

function cell(value: SystemStatusState, key: SubsystemKey): Cell {
  if (value.state === 'loading') {
    return { value: 'Checking…', note: 'Reading GET /status', state: 'probe' }
  }
  if (value.state === 'unavailable') {
    return {
      value: '—',
      note: 'No engine address is compiled into this build',
      state: 'unknown',
    }
  }
  if (value.state === 'error') {
    return { value: 'Unknown', note: value.reason, state: 'unavailable' }
  }
  const subsystem = value.data[key]
  return {
    value: subsystem.state === 'ok' ? OK_LABEL[key] : STATE_LABEL[subsystem.state],
    note: subsystem.detail ? `${subsystem.summary} ${subsystem.detail}` : subsystem.summary,
    state: subsystem.state,
  }
}

function hint(value: SystemStatusState, checkedAt: Date | null): string {
  if (value.state === 'ok') {
    const at = checkedAt ? checkedFormat.format(checkedAt) : value.data.checked_at
    return `GET /status · ${at} · ${value.latencyMs} ms`
  }
  return value.state === 'loading' ? 'GET /status · first read' : 'GET /status'
}

/**
 * The one status instrument used by every dashboard.
 *
 * It renders the engine's own answer; it never derives a subsystem from another
 * one, and it can show a subset where a page only cares about a few rows.
 */
const DEPLOYMENT_LABEL: Record<ComponentDeployment, string> = {
  deployed: 'Deployed',
  not_deployed: 'Not deployed',
  not_configured: 'Not configured',
  unknown: 'Unknown',
}

const OPERATIONAL_CHIP: Record<
  ComponentOperational,
  { tone: 'ok' | 'attention' | 'neutral'; text: string }
> = {
  available: { tone: 'ok', text: 'Available' },
  starting: { tone: 'attention', text: 'Starting' },
  degraded: { tone: 'attention', text: 'Degraded' },
  unavailable: { tone: 'attention', text: 'Unavailable' },
  // Unverified is not a failure and not a success: no observation was recorded.
  unverified: { tone: 'neutral', text: 'Unverified' },
  unknown: { tone: 'neutral', text: 'Unknown' },
}

const READINESS_LABEL: Record<ComponentReadiness, string> = {
  ready: 'Ready',
  not_ready: 'Not ready',
  not_applicable: 'Not applicable',
  unavailable: 'Unavailable',
  unknown: 'Unknown',
}

/**
 * The component table: deployment, operation and readiness side by side, with
 * the evidence behind each row.
 *
 * It renders only what the engine reported. A component the engine could not
 * observe is shown as unknown, never as down or healthy, and the diagnostic
 * carries the engine's own words rather than a generic status sentence.
 */
export function ComponentHealthTable({ value }: { value: SystemStatusState }) {
  if (value.state === 'loading') {
    return <p className="panel-copy">Reading GET /status…</p>
  }
  if (value.state === 'unavailable') {
    return (
      <p className="panel-copy">
        No engine address is compiled into this build, so no component can be observed. None is
        reported as deployed, available or unavailable.
      </p>
    )
  }
  if (value.state === 'error') {
    return (
      <p className="panel-copy">
        The engine did not answer, so component health is unknown: {value.reason}
      </p>
    )
  }
  const components = value.data.components ?? []
  if (components.length === 0) {
    return (
      <p className="panel-copy">
        This engine build did not report component health, so nothing is assumed about the
        worker or the provider.
      </p>
    )
  }

  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">Component health reported by the engine</caption>
        <thead>
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Deployment</th>
            <th scope="col">Operational</th>
            <th scope="col">Readiness</th>
            <th scope="col">Last success</th>
            <th scope="col">Last failure</th>
            <th scope="col">Diagnostic</th>
          </tr>
        </thead>
        <tbody>
          {components.map((component) => {
            const chip = OPERATIONAL_CHIP[component.operational]
            return (
              <tr key={component.name}>
                <th scope="row">{component.name}</th>
                <td>{DEPLOYMENT_LABEL[component.deployment]}</td>
                <td>
                  <span className="chip app-chip" data-tone={chip.tone}>
                    {chip.text}
                  </span>
                </td>
                <td>{READINESS_LABEL[component.readiness]}</td>
                <td className="mono">{stamp(component.last_success_at)}</td>
                <td className="mono">
                  {component.last_failure
                    ? `${stamp(component.last_failure_at)} — ${component.last_failure}`
                    : '—'}
                </td>
                <td>{component.diagnostic}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function SystemStatusGrid({
  value,
  checkedAt,
  only,
  footer,
}: {
  value: SystemStatusState
  checkedAt: Date | null
  only?: readonly SubsystemKey[]
  footer?: ReactNode
}) {
  const keys = (Object.keys(LABEL) as SubsystemKey[]).filter(
    (key) => !only || only.includes(key),
  )

  return (
    <div className="system-status">
      <dl className="hub-stats" aria-live="polite" aria-busy={value.state === 'loading'}>
        {keys.map((key) => {
          const current = cell(value, key)
          return (
            <div className="hub-stat" key={key} data-state={current.state}>
              <dt className="hub-stat__label">{LABEL[key]}</dt>
              <dd className="hub-stat__value mono">{current.value}</dd>
              <dd className="hub-stat__note">{current.note}</dd>
            </div>
          )
        })}
      </dl>
      <p className="app-hint mono">{hint(value, checkedAt)}</p>
      {footer}
    </div>
  )
}

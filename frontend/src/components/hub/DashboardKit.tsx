import type { CSSProperties, ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import type { AppPath } from '../../lib/auth/roles'
import { Icon, type IconName } from '../ui/Icons'

/** Shared instruments for the three role command centres. */

export type DashboardRole = 'teacher' | 'assistant' | 'platform'

export function DashboardHero({
  role,
  eyebrow,
  title,
  lede,
  actions,
  aside,
}: {
  role: DashboardRole
  eyebrow: string
  title: string
  lede: string
  actions: ReactNode
  aside?: ReactNode
}) {
  return (
    <section
      className={`hub-hero dash-hero dash-hero--${role}`}
      aria-labelledby="dashboard-title"
    >
      <div className="dash-hero__copy">
        <p className="dash-hero__kicker mono">{eyebrow}</p>
        <h1 className="hub-hero__title" id="dashboard-title">
          {title}
        </h1>
        <p className="hub-hero__lede">{lede}</p>
        <div className="hub-hero__actions">{actions}</div>
      </div>
      {aside ? <div className="dash-hero__aside">{aside}</div> : null}
    </section>
  )
}

export function QuickAction({
  to,
  icon,
  label,
  note,
  primary = false,
}: {
  to: AppPath
  icon: IconName
  label: string
  note: string
  primary?: boolean
}) {
  return (
    <Link
      to={to}
      className={primary ? 'dash-action dash-action--primary' : 'dash-action'}
    >
      <span className="dash-action__icon" aria-hidden="true">
        <Icon name={icon} size={16} />
      </span>
      <span className="dash-action__copy">
        <strong>{label}</strong>
        <small>{note}</small>
      </span>
      <Icon name="arrow" size={14} />
    </Link>
  )
}

export function Pulse({
  label,
  children,
  note,
}: {
  label: string
  children: ReactNode
  note?: string
}) {
  return (
    <div className="dash-pulse" role="group" aria-label={label}>
      {children}
      {note ? <p className="dash-pulse__note">{note}</p> : null}
    </div>
  )
}

export function PulseStat({
  label,
  value,
  note,
  tone = 'default',
}: {
  label: string
  value: string | number | null
  note: string
  tone?: 'default' | 'attention' | 'ok'
}) {
  const shown = value === null || value === undefined || value === '' ? '—' : value
  return (
    <div className="dash-pulse__item" data-tone={tone}>
      <span className="dash-pulse__label">{label}</span>
      <strong className="dash-pulse__value mono">{shown}</strong>
      <span className="dash-pulse__caption">{note}</span>
    </div>
  )
}

export type WorkloadPart = {
  label: string
  value: number | null
  tone?: 'accent' | 'attention' | 'neutral'
}

export function WorkloadBar({
  parts,
  loading = false,
  empty = 'No jobs in this queue.',
}: {
  parts: readonly WorkloadPart[]
  loading?: boolean
  empty?: string
}) {
  const known = parts.every((part) => part.value !== null)
  const total = known ? parts.reduce((sum, part) => sum + (part.value ?? 0), 0) : null

  return (
    <div className="dash-workload" aria-label="Queue workload" aria-busy={loading}>
      <div
        className="dash-workload__track"
        role="img"
        aria-label={
          loading || total === null
            ? 'Queue workload not available'
            : `${total} jobs: ${parts
                .map((part) => `${part.label} ${part.value ?? 0}`)
                .join(', ')}`
        }
      >
        {loading || total === null ? (
          <span className="dash-workload__unknown" />
        ) : total === 0 ? (
          <span className="dash-workload__zero" />
        ) : (
          parts.map((part) =>
            part.value && part.value > 0 ? (
              <span
                className="dash-workload__part"
                data-tone={part.tone ?? 'accent'}
                key={part.label}
                style={{ width: `${(part.value / total) * 100}%` }}
              />
            ) : null,
          )
        )}
      </div>
      <div className="dash-workload__legend">
        {parts.map((part) => (
          <span className="dash-workload__legend-item" key={part.label}>
            <span className="dash-workload__swatch" data-tone={part.tone ?? 'accent'} />
            <span>{part.label}</span>
            <strong className="mono">{part.value === null ? '—' : part.value}</strong>
          </span>
        ))}
      </div>
      {!loading && total === 0 ? <p className="dash-workload__empty">{empty}</p> : null}
    </div>
  )
}

export type FlowStage = {
  id: string
  label: string
  value: number | null
  note: string
  to: AppPath
  icon: IconName
  tone?: 'default' | 'attention' | 'ok'
}

/**
 * A left-to-right account of where work currently sits. The stages follow the
 * marking lifecycle, but each value is a count of jobs in that state rather than
 * a conversion rate; the surrounding copy says so instead of implying a funnel.
 */
export function FlowRail({
  stages,
  state,
  label,
}: {
  stages: readonly FlowStage[]
  state: 'loading' | 'ok' | 'unavailable' | 'error'
  label: string
}) {
  const unavailable = state === 'unavailable' || state === 'error'
  return (
    <div className="dash-flow" role="group" aria-label={label} aria-busy={state === 'loading'}>
      <ol className="dash-flow__rail">
        {stages.map((stage) => (
          <li className="dash-flow__stage" key={stage.id} data-tone={stage.tone ?? 'default'}>
            <Link to={stage.to} className="dash-flow__link">
              <span className="dash-flow__icon" aria-hidden="true">
                <Icon name={stage.icon} size={15} />
              </span>
              <span className="dash-flow__copy">
                <span className="dash-flow__label">{stage.label}</span>
                <strong className="dash-flow__value mono">
                  {stage.value === null ? '—' : stage.value}
                </strong>
                <small>{stage.note}</small>
              </span>
              <Icon name="arrow" size={14} className="dash-flow__arrow" />
            </Link>
          </li>
        ))}
      </ol>
      {state === 'loading' ? (
        <p className="dash-flow__status mono">Reading the marking pipeline…</p>
      ) : unavailable ? (
        <p className="dash-flow__status mono">
          The engine has not answered, so every stage stays blank.
        </p>
      ) : null}
    </div>
  )
}

export type BarRow = {
  id: string
  label: string
  value: number | null
  detail?: string
  suffix?: string
}

export function Bars({
  rows,
  label,
  empty,
}: {
  rows: readonly BarRow[]
  label: string
  empty: string
}) {
  const max = Math.max(...rows.map((row) => row.value ?? 0), 1)
  if (rows.length === 0) return <p className="dash-empty">{empty}</p>

  return (
    <div className="dash-bars" role="list" aria-label={label}>
      {rows.map((row) => {
        const width = row.value === null ? 0 : Math.max(2, (row.value / max) * 100)
        return (
          <div className="dash-bars__row" role="listitem" key={row.id}>
            <span className="dash-bars__label" title={row.label}>
              {row.label}
            </span>
            <span className="dash-bars__track" aria-hidden="true">
              <span
                className="dash-bars__fill"
                data-missing={row.value === null ? 'true' : undefined}
                style={{ '--bar-width': `${width}%` } as CSSProperties}
              />
            </span>
            <span className="dash-bars__value mono">
              {row.value === null ? '—' : `${Math.round(row.value * 10) / 10}${row.suffix ?? ''}`}
            </span>
            {row.detail ? <span className="dash-bars__detail">{row.detail}</span> : null}
          </div>
        )
      })}
    </div>
  )
}

export type TimelineItem = {
  id: string
  title: string
  detail: string
  stamp: string
  tone?: 'accent' | 'attention' | 'neutral' | 'ok'
  action?: ReactNode
}

export function Timeline({ items }: { items: readonly TimelineItem[] }) {
  if (items.length === 0) {
    return <p className="dash-empty">No recorded activity yet.</p>
  }
  return (
    <ol className="dash-timeline">
      {items.map((item) => (
        <li className="dash-timeline__item" key={item.id}>
          <span className="dash-timeline__marker" data-tone={item.tone ?? 'accent'} aria-hidden="true" />
          <div className="dash-timeline__body">
            <div className="dash-timeline__head">
              <strong>{item.title}</strong>
              <time className="mono">{item.stamp}</time>
            </div>
            <p>{item.detail}</p>
            {item.action ? <div className="dash-timeline__action">{item.action}</div> : null}
          </div>
        </li>
      ))}
    </ol>
  )
}

export function DashboardFallback({
  title,
  reason,
  capability,
  compact = false,
}: {
  title: string
  reason: string
  capability?: string
  compact?: boolean
}) {
  return (
    <div className={compact ? 'dash-fallback dash-fallback--compact' : 'dash-fallback'} role="status">
      <span className="dash-fallback__icon" aria-hidden="true">
        <Icon name="server" size={16} />
      </span>
      <div>
        <strong>{title}</strong>
        <p>{reason}</p>
        {capability ? <span className="mono dash-fallback__capability">{capability}</span> : null}
      </div>
    </div>
  )
}

export function DashboardSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="dash-skeleton" aria-busy="true" aria-label="Reading from the engine">
      {Array.from({ length: rows }, (_, index) => (
        <div className="dash-skeleton__row" key={index}>
          <span className="hub-skel" />
          <span className="hub-skel" />
          <span className="hub-skel" />
        </div>
      ))}
    </div>
  )
}

// UTC keeps the server-rendered timestamp and the hydrated client on the same
// value; the tooltip and surrounding label carry the date context.
const stampFormat = new Intl.DateTimeFormat('en-GB', {
  day: '2-digit',
  month: 'short',
  hour: '2-digit',
  minute: '2-digit',
  timeZone: 'UTC',
})

export function dashboardStamp(value: string | null | undefined): string {
  if (!value) return 'not recorded'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'not recorded' : stampFormat.format(date)
}

export function percent(value: number | null | undefined, digits = 1): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(digits)}%`
}

import type { CSSProperties, ReactNode } from 'react'
import { Icon, type IconName } from '../ui/Icons'

/**
 * Shared page blocks for the account dashboards.
 *
 * These compose the classes that already exist in `hub.css` (`app-card`,
 * `hub-stats`, `data-table`, `chip`) so every role reads as one application.
 * Anything that needs engine data shows an explicit unavailable state instead of
 * a number that was made up for the screenshot.
 */

export function Panel({
  title,
  note,
  index,
  children,
  className,
}: {
  title: string
  note?: string
  /** Stagger order for the card entrance. */
  index?: number
  children?: ReactNode
  className?: string
}) {
  return (
    <section
      className={className ? `app-card ${className}` : 'app-card'}
      style={index === undefined ? undefined : ({ '--i': index } as CSSProperties)}
      aria-label={title}
    >
      <div className="app-card__head">
        <h2 className="app-card__title">{title}</h2>
        {note ? <span className="app-card__note mono">{note}</span> : null}
      </div>
      {children}
    </section>
  )
}

export type Metric = { label: string; note?: string }

/**
 * The ruled stat strip used on the hub. Values are an em dash with an explicit
 * accessible name, because no engine figures exist yet.
 */
export function StatsStrip({ metrics, source = 'engine' }: { metrics: readonly Metric[]; source?: string }) {
  return (
    <dl className="hub-stats">
      {metrics.map((metric) => (
        <div className="hub-stat" key={metric.label}>
          <dt className="hub-stat__label">{metric.label}</dt>
          <dd className="hub-stat__value mono" aria-label={`${metric.label}: not available`}>
            —
          </dd>
          <dd className="hub-stat__note">
            {metric.note ??
              (source === 'engine'
                ? 'not reported by the engine'
                : `not reported by ${source}`)}
          </dd>
        </div>
      ))}
    </dl>
  )
}

/** A table whose columns are real and whose rows are honestly absent. */
export function EmptyTable({
  columns,
  caption,
  note,
}: {
  columns: readonly string[]
  caption: string
  note: string
}) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <caption className="visually-hidden">{caption}</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={columns.length} className="data-table__empty">
              {note}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export type LineItem = {
  label: string
  detail: string
  /**
   * `unimplemented` is distinct from `pending`: the capability does not exist in
   * this build, so waiting for a deployment will not deliver it.
   */
  state: 'available' | 'pending' | 'blocked' | 'unimplemented'
  icon?: IconName
}

const STATE_CHIP: Record<LineItem['state'], { tone: 'ok' | 'attention' | 'neutral'; text: string }> = {
  available: { tone: 'ok', text: 'Available' },
  pending: { tone: 'attention', text: 'Not deployed' },
  blocked: { tone: 'neutral', text: 'Blocked' },
  unimplemented: { tone: 'neutral', text: 'Not implemented' },
}

/** A capability ledger: what exists, what is waiting for the engine. */
export function CapabilityList({ items }: { items: readonly LineItem[] }) {
  return (
    <ul className="cap-list">
      {items.map((item) => {
        const chip = STATE_CHIP[item.state]
        return (
          <li className="cap-list__row" key={item.label}>
            <span className="cap-list__icon" aria-hidden="true">
              <Icon name={item.icon ?? 'dot'} size={15} />
            </span>
            <span className="cap-list__copy">
              <span className="cap-list__label">{item.label}</span>
              <span className="cap-list__detail">{item.detail}</span>
            </span>
            <span className="chip app-chip" data-tone={chip.tone}>
              {chip.text}
            </span>
          </li>
        )
      })}
    </ul>
  )
}

/** A short numbered routine, used where a dashboard describes a workflow. */
export function StepList({ steps }: { steps: readonly { title: string; body: string }[] }) {
  return (
    <ol className="step-list">
      {steps.map((step, i) => (
        <li className="step-list__row" key={step.title}>
          <span className="step-list__index mono">{String(i + 1).padStart(2, '0')}</span>
          <span className="step-list__copy">
            <span className="step-list__title">{step.title}</span>
            <span className="step-list__body">{step.body}</span>
          </span>
        </li>
      ))}
    </ol>
  )
}

import type { ReactNode } from 'react'
import { Icon, type IconName } from '../ui/Icons'

export type StateTone = 'wip' | 'empty' | 'error'

const TONE_META: Record<StateTone, { label: string; icon: IconName }> = {
  wip: { label: 'Work in progress', icon: 'server' },
  empty: { label: 'Nothing here yet', icon: 'records' },
  error: { label: 'Request failed', icon: 'review' },
}

/**
 * The single honest placeholder used across the application. It states what the
 * screen needs, why it cannot show it yet, and never renders invented figures.
 */
export function StatePanel({
  tone,
  title,
  children,
  capability,
}: {
  tone: StateTone
  title: string
  children?: ReactNode
  /** The backend capability this screen is waiting for. */
  capability?: string
}) {
  const meta = TONE_META[tone]

  return (
    <section className="state-panel" data-tone={tone} aria-label={title}>
      <div className="state-panel__head">
        <span className="state-panel__badge mono">
          <Icon name={meta.icon} size={14} />
          {meta.label}
        </span>
      </div>
      <h2 className="state-panel__title">{title}</h2>
      {children ? <div className="state-panel__body">{children}</div> : null}
      {capability ? (
        <p className="state-panel__capability mono">
          Waiting on: <span>{capability}</span>
        </p>
      ) : null}
    </section>
  )
}

/** A compact status chip for a table cell or list row. */
export function StatusChip({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'attention' | 'ok'
}) {
  return (
    <span className="chip app-chip" data-tone={tone}>
      {children}
    </span>
  )
}

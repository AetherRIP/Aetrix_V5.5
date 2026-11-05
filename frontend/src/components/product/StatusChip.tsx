import type { DemoStatus } from '../../lib/demo-data'
import { Icon, type IconName } from '../ui/Icons'

const STATUS: Record<DemoStatus, { label: string; icon: IconName }> = {
  approved: { label: 'Approved', icon: 'check' },
  review: { label: 'Needs review', icon: 'triangle' },
  queued: { label: 'Queued', icon: 'dot' },
  marking: { label: 'Marking', icon: 'half' },
  override: { label: 'Override', icon: 'pen' },
  published: { label: 'Published', icon: 'checkDouble' },
}

/**
 * Status is carried by a word, a shape and a weight — never by colour. This is
 * the encoding docs/design/ACCESSIBILITY.md §4 requires, and on a monochrome
 * surface it is the only encoding available.
 */
export function StatusChip({
  status,
  size = 'md',
}: {
  status: DemoStatus
  size?: 'sm' | 'md'
}) {
  const entry = STATUS[status]
  return (
    <span className="chip" data-status={status} data-size={size}>
      <Icon name={entry.icon} size={size === 'sm' ? 10 : 12} strokeWidth={1.8} />
      <span className="chip__label">{entry.label}</span>
    </span>
  )
}

export function Skeleton({
  width = '100%',
  className,
}: {
  width?: string
  className?: string
}) {
  return (
    <span
      className={className ? `skeleton ${className}` : 'skeleton'}
      style={{ width }}
      aria-hidden="true"
    />
  )
}

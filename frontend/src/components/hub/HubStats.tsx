import { HubSection } from './HubSection'

const METRICS = [
  { key: 'received', label: 'Submissions received' },
  { key: 'awaiting', label: 'Awaiting marking' },
  { key: 'review', label: 'Needing review' },
  { key: 'marked', label: 'Marked this week' },
] as const

/**
 * Figures on one ruled line rather than four floating cards: the workspace is a
 * ledger, and the numbers should read like one. Every cell is empty because the
 * engine is not deployed — the em dash is the honest value, not a placeholder
 * waiting to be replaced by a made-up count.
 */
export function HubStats() {
  return (
    <HubSection
      id="hub-overview"
      title="Workspace overview"
      note="Awaits the engine API"
      index={1}
      className="hub-section--stats"
    >
      <dl className="hub-stats">
        {METRICS.map((metric) => (
          <div className="hub-stat" key={metric.key}>
            <dt className="hub-stat__label">{metric.label}</dt>
            <dd className="hub-stat__value mono" aria-label={`${metric.label}: not available`}>
              —
            </dd>
            <dd className="hub-stat__note">awaits engine</dd>
          </div>
        ))}

        <div className="hub-stat hub-stat--state">
          <dt className="hub-stat__label">Data source</dt>
          <dd className="hub-stat__value hub-stat__value--text">Not connected</dd>
          <dd className="hub-stat__note">no public API</dd>
        </div>
      </dl>
    </HubSection>
  )
}

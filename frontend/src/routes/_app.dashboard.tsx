import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { API_UNAVAILABLE_REASON } from '../lib/env'
import { formatDateTime } from '../lib/format'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/_app/dashboard')({
  component: Dashboard,
})

const METRICS = [
  { label: 'Submissions received', unit: 'scripts' },
  { label: 'Awaiting marking', unit: 'scripts' },
  { label: 'Needing review', unit: 'scripts' },
  { label: 'Marked this week', unit: 'scripts' },
] as const

function Dashboard() {
  const { user, session } = useAuth()
  const name = displayName(user)

  return (
    <div className="app-stack">
      <section className="app-callout" aria-label="Session summary">
        <div>
          <p className="app-callout__kicker mono">Signed in</p>
          <p className="app-callout__title">{name}</p>
          <p className="app-callout__body">
            Session verified by Supabase at {formatDateTime(session?.user.last_sign_in_at)}.
            This is live session data, not a placeholder.
          </p>
        </div>
        <span className="chip app-chip" data-tone="ok">
          <Icon name="shield" size={13} /> Authenticated
        </span>
      </section>

      <section className="metric-grid" aria-label="Workspace metrics">
        {METRICS.map((metric) => (
          <article className="metric" key={metric.label}>
            <p className="metric__label mono">{metric.label}</p>
            <p className="metric__value" aria-label={`${metric.label}: unavailable`}>
              —
            </p>
            <p className="metric__unit">{metric.unit} · awaits engine</p>
          </article>
        ))}
      </section>

      <StatePanel
        tone="wip"
        title="Live figures need the deployed engine"
        capability="GET /api/v1/workspaces/{id}/dashboard"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          The dashboard contract is wired but unpopulated: the metric cards above are
          deliberately empty rather than filled with invented numbers. As soon as the
          API answers, this section renders the same cards with real counts.
        </p>
      </StatePanel>

      <div className="app-split">
        <StatePanel tone="wip" title="Marking activity" capability="correction job events">
          <p>
            Recent job transitions appear here once the correction pipeline is
            implemented. The pipeline is intentionally unavailable today, so there is
            no activity to show and none is fabricated.
          </p>
        </StatePanel>

        <section className="app-card" aria-labelledby="next-steps-title">
          <h2 className="app-card__title" id="next-steps-title">
            What already works
          </h2>
          <ul className="app-list">
            <li>
              <Icon name="check" size={15} /> Google authentication through Supabase
            </li>
            <li>
              <Icon name="check" size={15} /> Persistent session with automatic refresh
            </li>
            <li>
              <Icon name="check" size={15} /> Protected routes and sign-out
            </li>
            <li>
              <Icon name="check" size={15} /> Theme preference across the application
            </li>
          </ul>
        </section>
      </div>
    </div>
  )
}

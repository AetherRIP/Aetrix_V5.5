import type { CSSProperties } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { HubActions } from '../components/hub/HubActions'
import { HubFeed } from '../components/hub/HubFeed'
import { HubHealth } from '../components/hub/HubHealth'
import { HubHero } from '../components/hub/HubHero'
import { HubSection } from '../components/hub/HubSection'
import { HubSession } from '../components/hub/HubSession'
import { HubStats } from '../components/hub/HubStats'
import { Icon } from '../components/ui/Icons'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/dashboard')({
  component: Dashboard,
})

const WORKS = [
  'Google authentication through Supabase',
  'Persistent session with automatic refresh',
  'Protected routes and sign-out',
  'Theme preference across the application',
] as const

function Dashboard() {
  const { user } = useAuth()
  const name = displayName(user)
  const firstName = name.split(/\s+/)[0] || name

  return (
    <div className="hub-main">
      <HubHero
        name={firstName}
        lede="Your workspace: its classes, assignments and marking load. Figures stay blank until the engine exposes them — nothing here is estimated."
        actions={
          <>
            <Link to="/queue" className="btn btn--primary">
              Open marking queue
              <Icon name="arrow" size={16} />
            </Link>
            <Link to="/workspace" className="btn btn--outline">
              Workspaces
            </Link>
          </>
        }
      />

      <HubStats />

      <div className="hub-grid">
        <div className="hub-col">
          <HubSession index={2} />
          <HubActions index={3} />

          <HubSection id="hub-works" title="What already works" index={4}>
            <ul className="hub-works">
              {WORKS.map((item) => (
                <li key={item}>
                  <Icon name="check" size={14} />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </HubSection>
        </div>

        <aside className="hub-col hub-col--aside" aria-label="Workspace context">
          <HubHealth />
          <HubFeed />
        </aside>
      </div>

      {/* Full width, at the foot of the page: the statement belongs to the
          screen as a whole, and a half-width panel here would leave the aside
          hanging beside an empty column. */}
      <div className="hub-engine" style={{ '--i': 5 } as CSSProperties}>
        <StatePanel
          tone="wip"
          title="Live figures need the deployed engine"
          capability="GET /api/v1/workspaces/{id}/dashboard"
        >
          <p>{API_UNAVAILABLE_REASON}</p>
          <p>
            The dashboard contract is wired but unpopulated: the figures above are
            deliberately empty rather than filled with invented numbers. As soon as the
            API answers, this section renders the same ledger with real counts.
          </p>
        </StatePanel>
      </div>
    </div>
  )
}

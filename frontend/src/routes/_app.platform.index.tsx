import type { CSSProperties } from 'react'
import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel, StatsStrip } from '../components/app/PageBlocks'
import { HubHero } from '../components/hub/HubHero'
import { HubSection } from '../components/hub/HubSection'
import { Icon } from '../components/ui/Icons'
import { displayName, useAuth } from '../lib/auth/AuthProvider'

export const Route = createFileRoute('/_app/platform/')({
  component: PlatformOverview,
})

/**
 * The operator dashboard. It is deliberately a different instrument from the
 * academic ones: no classes, no students, no marks — workspaces, accounts,
 * allocation and service state.
 */
function PlatformOverview() {
  const { user } = useAuth()
  const firstName = displayName(user).split(/\s+/)[0]

  return (
    <div className="hub-main">
      <HubHero
        name={firstName}
        lede="Platform-level view. Workspaces, accounts and service state are read from the engine; allocation is the operator’s job, not the teacher’s."
        actions={
          <>
            <Link to="/platform/workspaces" className="btn btn--primary">
              Workspaces
              <Icon name="arrow" size={16} />
            </Link>
            <Link to="/platform/users" className="btn btn--outline">
              Accounts
            </Link>
          </>
        }
      />

      <HubSection
        id="platform-figures"
        title="Platform overview"
        note="Awaits the engine API"
        index={1}
        className="hub-section--stats"
      >
        <StatsStrip
          metrics={[
            { label: 'Teacher workspaces' },
            { label: 'Teachers' },
            { label: 'Assistant accounts' },
            { label: 'Active class allocations' },
          ]}
        />
      </HubSection>

      <div className="hub-grid">
        <div className="hub-col">
          <Panel title="Workspace allocation" index={2} note="One workspace per class">
            <CapabilityList
              items={[
                {
                  label: 'Allocate a Google Classroom class',
                  detail: 'Operator-only action; a class holds one active allocation.',
                  state: 'pending',
                  icon: 'classroom',
                },
                {
                  label: 'Reassign an allocation',
                  detail: 'Requires the previous workspace to release the class first.',
                  state: 'pending',
                  icon: 'pulse',
                },
                {
                  label: 'Teacher-side changes to allocation',
                  detail: 'Not permitted by design: teachers cannot move classes.',
                  state: 'blocked',
                  icon: 'lock',
                },
              ]}
            />
          </Panel>

          <Panel title="Accounts and roles" index={3} note="Four account types">
            <CapabilityList
              items={[
                {
                  label: 'owner',
                  detail:
                    'Owns the platform and every workspace. Assigned in the identity provider only; no screen grants or removes it.',
                  state: 'available',
                  icon: 'shield',
                },
                {
                  label: 'platform_operator',
                  detail: 'Operates the platform. No access to student records.',
                  state: 'available',
                  icon: 'shield',
                },
                {
                  label: 'supervisor',
                  detail: 'Owns one workspace; cannot see another workspace.',
                  state: 'available',
                  icon: 'eye',
                },
                {
                  label: 'assistant',
                  detail: 'Assigned work only; no workspace administration.',
                  state: 'available',
                  icon: 'pen',
                },
              ]}
            />
          </Panel>
        </div>

        <aside className="hub-col hub-col--aside" aria-label="Service context">
          <Panel title="Service status" index={4} note="Not reported yet">
            <CapabilityList
              items={[
                { label: 'API', detail: 'No public deployment.', state: 'pending', icon: 'server' },
                { label: 'Worker', detail: 'Leases jobs; pipeline parks them.', state: 'pending', icon: 'pulse' },
                { label: 'Database', detail: 'PostgreSQL; RLS guard passes in CI.', state: 'pending', icon: 'records' },
              ]}
            />
          </Panel>

          <Panel title="AI providers" index={5} note="Configuration only">
            <p className="panel-copy">
              The live provider is <code>UNVERIFIED</code>. Gemini usage and quota
              monitoring are not implemented; the navigation slot exists so the feature can
              arrive without restructuring the platform area.
            </p>
            <Link className="panel-link" to="/platform/integrations">
              <Icon name="blueprint" size={15} />
              Provider configuration
            </Link>
          </Panel>
        </aside>
      </div>

      <div className="hub-engine" style={{ '--i': 6 } as CSSProperties}>
        <StatePanel
          tone="wip"
          title="Platform figures need a platform-level API"
          capability="engine: tenant-scoped endpoints only"
        >
          <p>
            The correction engine exposes tenant-scoped routes (<code>/api/v1/exams</code>,{' '}
            <code>/api/v1/corrections</code>, <code>/api/v1/documents</code>,{' '}
            <code>/api/v1/usage</code>). It has no platform-level endpoint, so this dashboard
            shows an empty ledger rather than numbers invented for it.
          </p>
        </StatePanel>
      </div>
    </div>
  )
}

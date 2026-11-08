import { createFileRoute, Link } from '@tanstack/react-router'
import { HubHero } from '../components/hub/HubHero'
import { HubSection } from '../components/hub/HubSection'
import { CapabilityList, EmptyTable, Panel, StatsStrip } from '../components/app/PageBlocks'
import { Icon } from '../components/ui/Icons'
import { displayName, useAuth } from '../lib/auth/AuthProvider'

export const Route = createFileRoute('/_app/assistant/')({
  component: AssistantOverview,
})

function AssistantOverview() {
  const { user } = useAuth()
  const firstName = displayName(user).split(/\s+/)[0]

  return (
    <div className="hub-main">
      <HubHero
        name={firstName}
        lede="Your work in your teacher’s workspace. Only the classes and submissions assigned to you appear here — nothing else is in scope."
        actions={
          <>
            <Link to="/queue" className="btn btn--primary">
              Open submission queue
              <Icon name="arrow" size={16} />
            </Link>
            <Link to="/assistant/tasks" className="btn btn--outline">
              My tasks
            </Link>
          </>
        }
      />

      <HubSection
        id="assistant-figures"
        title="My work"
        note="Awaits the engine API"
        index={1}
        className="hub-section--stats"
      >
        <StatsStrip
          metrics={[
            { label: 'Assigned classes' },
            { label: 'Awaiting my review' },
            { label: 'Completed this week' },
            { label: 'Overdue' },
          ]}
        />
      </HubSection>

      <div className="hub-grid">
        <div className="hub-col">
          <Panel title="Waiting on me" index={2} note="Newest first">
            <EmptyTable
              columns={['Submission', 'Class', 'Assignment', 'Assigned', 'Due']}
              caption="Submissions assigned to this assistant"
              note="No rows — assignments come from the engine, which does not expose them yet."
            />
          </Panel>

          <Panel title="My scope" index={3} note="Set by the teacher">
            <CapabilityList
              items={[
                {
                  label: 'Assigned classes',
                  detail: 'Only classes your teacher assigned to you are visible.',
                  state: 'available',
                  icon: 'classroom',
                },
                {
                  label: 'Assigned submissions',
                  detail: 'Other students in the same class are out of scope.',
                  state: 'available',
                  icon: 'records',
                },
                {
                  label: 'Workspace administration',
                  detail: 'Not available to assistants, by design.',
                  state: 'blocked',
                  icon: 'lock',
                },
              ]}
            />
          </Panel>
        </div>

        <aside className="hub-col hub-col--aside" aria-label="Assistant context">
          <Panel title="Review rules" index={4} note="Engine-enforced">
            <p className="panel-copy">
              A review you submit is recorded against your account. Marks are not produced by
              this build — the correction pipeline is deliberately unavailable — so review
              here means reading the script, not approving a mark.
            </p>
            <Link className="panel-link" to="/assistant/work">
              <Icon name="pen" size={15} />
              Marking workspace
            </Link>
          </Panel>

          <Panel title="Notifications" index={5} note="Shared inbox">
            <p className="panel-copy">
              Assignments, review requests and failures arrive in the same inbox the teacher
              uses, filtered to your scope.
            </p>
            <Link className="panel-link" to="/inbox">
              <Icon name="records" size={15} />
              Open inbox
            </Link>
          </Panel>
        </aside>
      </div>
    </div>
  )
}

import { createFileRoute, Link } from '@tanstack/react-router'
import { EmptyTable, Panel, StatsStrip } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/_app/assistant/progress')({
  component: AssistantProgress,
})

function AssistantProgress() {
  return (
    <div className="app-stack">
      <Panel title="My throughput" note="No reviews recorded" index={0}>
        <StatsStrip
          metrics={[
            { label: 'Reviews this week' },
            { label: 'Reviews this term' },
            { label: 'Median time per script' },
            { label: 'Flagged for a second look' },
          ]}
        />
      </Panel>

      <Panel title="Per class" index={1} note="Scoped to you">
        <EmptyTable
          columns={['Class', 'Assigned', 'Reviewed', 'Outstanding', 'Median time']}
          caption="This assistant's review progress by class"
          note="No activity — reviews need the marking pipeline, which is not implemented."
        />
      </Panel>

      <Panel title="What these figures would count" index={2} note="Definition">
        <ul className="rule-list">
          <li>
            A <em>review</em> is a script you opened and confirmed or flagged. Reading a page is
            not a review.
          </li>
          <li>The median is per script, not per page, so long papers do not distort it.</li>
          <li>
            Progress is yours only. Your teacher sees workspace totals, not a ranking of
            assistants.
          </li>
        </ul>
      </Panel>

      <StatePanel
        tone="wip"
        title="Progress cannot be measured without recorded reviews"
        capability="engine: review events (not implemented)"
      >
        <p>
          Every figure above is an em dash because there is no review history to count. A
          progress ring filled to a plausible percentage would be a claim about your work that
          no system has made.
        </p>
      </StatePanel>

      <p className="panel-copy">
        Results are reported alongside the teacher’s.{' '}
        <Link className="panel-link" to="/reports">
          <Icon name="blueprint" size={14} />
          Results and reports
        </Link>
      </p>
    </div>
  )
}

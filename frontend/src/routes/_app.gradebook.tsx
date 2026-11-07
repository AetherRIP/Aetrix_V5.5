import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { EmptyTable, Panel, StatsStrip } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/gradebook')({
  component: Gradebook,
})

function Gradebook() {
  return (
    <div className="app-stack">
      <Panel title="Cycle summary" note="Awaits the engine">
        <StatsStrip
          metrics={[
            { label: 'Students' },
            { label: 'Submissions marked' },
            { label: 'Awaiting review' },
            { label: 'Mean mark' },
          ]}
        />
      </Panel>

      <Panel title="Marks" note="One row per student">
        <EmptyTable
          columns={['Student', 'Class', 'Assignment', 'Mark', 'State']}
          caption="Gradebook entries for this workspace"
          note="No rows — no marks exist, because marking is not implemented."
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="A gradebook needs marks, and marking is not implemented"
        capability="engine: corrections pipeline (PIPELINE_UNAVAILABLE)"
      >
        <p>
          The worker leases correction jobs but parks them with{' '}
          <code>PIPELINE_UNAVAILABLE</code> rather than producing a mark. A gradebook built
          on that would be a table of blanks, so this screen states the gap instead.
        </p>
      </StatePanel>
    </div>
  )
}

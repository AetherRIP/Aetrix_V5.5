import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { EmptyTable, Panel, StatsStrip } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/analytics')({
  component: Analytics,
})

function Analytics() {
  return (
    <div className="app-stack">
      <Panel title="Cohort outline" note="Awaits the engine">
        <StatsStrip
          metrics={[
            { label: 'Mean mark' },
            { label: 'Questions below target' },
            { label: 'Scripts needing review' },
            { label: 'Completion' },
          ]}
        />
      </Panel>

      <Panel title="Question-level performance" note="Per assignment">
        <EmptyTable
          columns={['Assignment', 'Question', 'Attempted', 'Mean', 'Flag']}
          caption="Question-level performance for this workspace"
          note="No rows — analytics is derived from marks, and marking is not implemented."
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="Analytics cannot precede marking"
        capability="engine: cohort intelligence (not implemented)"
      >
        <p>
          Cohort intelligence is listed as unimplemented in the engine’s own status. This
          screen is the destination for it, not a simulation of it.
        </p>
      </StatePanel>
    </div>
  )
}

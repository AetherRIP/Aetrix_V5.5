import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, EmptyTable, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/assistants')({
  component: Assistants,
})

function Assistants() {
  return (
    <div className="app-stack">
      <Panel title="Assistants in this workspace" note="Invitations not implemented">
        <EmptyTable
          columns={['Assistant', 'Email', 'Assigned classes', 'Queue', 'State']}
          caption="Assistants belonging to this workspace"
          note="No rows — assistant accounts are engine records, and no endpoint lists them."
        />
      </Panel>

      <Panel title="What an assistant may do" note="Set by the engine, not this page">
        <CapabilityList
          items={[
            {
              label: 'Review assigned submissions',
              detail: 'Only submissions explicitly assigned to that assistant.',
              state: 'available',
              icon: 'pen',
            },
            {
              label: 'See assigned classes',
              detail: 'A class the teacher has not assigned is invisible to them.',
              state: 'available',
              icon: 'classroom',
            },
            {
              label: 'Manage the workspace',
              detail: 'Refused: no assistant may change workspace settings or allocation.',
              state: 'blocked',
              icon: 'lock',
            },
            {
              label: 'Invite or remove assistants',
              detail: 'Needs an engine endpoint that does not exist yet.',
              state: 'pending',
              icon: 'eye',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="Assistant management has no endpoint"
        capability="engine: workspace membership (not exposed)"
      >
        <p>
          Membership is modelled in the engine, but this repository has no route that adds,
          removes or lists assistants. The interface offers no button that would fail
          silently.
        </p>
      </StatePanel>
    </div>
  )
}

import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel, StepList } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/classroom')({
  component: Classroom,
})

function Classroom() {
  return (
    <div className="app-stack">
      <Panel title="Connection" note="Not connected">
        <CapabilityList
          items={[
            {
              label: 'Google Classroom authorisation',
              detail: 'Requires a granted OAuth scope and an engine endpoint to store it.',
              state: 'pending',
              icon: 'lock',
            },
            {
              label: 'Roster import',
              detail: 'Students and classes would be read from the allocated course.',
              state: 'pending',
              icon: 'classroom',
            },
            {
              label: 'Class allocation',
              detail: 'Operator-only. A teacher cannot move a class between workspaces.',
              state: 'blocked',
              icon: 'shield',
            },
          ]}
        />
      </Panel>

      <Panel title="How a class reaches this workspace" note="Four steps, one owner each">
        <StepList
          steps={[
            {
              title: 'The operator allocates the class',
              body: 'Platform administrator assigns the Classroom course to exactly one workspace.',
            },
            {
              title: 'The teacher connects Classroom',
              body: 'The workspace authorises roster reads for the classes it was given.',
            },
            {
              title: 'The roster is imported',
              body: 'Students arrive from the course; nothing is created by hand.',
            },
            {
              title: 'Assistants are assigned',
              body: 'The teacher assigns classes and submissions; assistants see only those.',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="No Classroom integration exists in this build"
        capability="Google Classroom API (not integrated)"
      >
        <p>
          Connecting would need an OAuth scope, a token store in the engine and a sync route.
          None of the three exists, so this screen explains the flow without offering a
          connect button that could not work.
        </p>
      </StatePanel>
    </div>
  )
}

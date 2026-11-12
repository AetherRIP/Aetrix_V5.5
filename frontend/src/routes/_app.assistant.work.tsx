import { createFileRoute, Link } from '@tanstack/react-router'
import { CapabilityList, Panel, StepList } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/_app/assistant/work')({
  component: AssistantWork,
})

function AssistantWork() {
  return (
    <div className="app-stack">
      <Panel title="Marking workspace" note="No script loaded" index={0}>
        <p className="panel-copy">
          Opening a submission shows the student’s pages beside the marking surface. This
          build gives assistants no marking surface of their own, so the panel stays empty
          and says so — there is no placeholder mark to click.
        </p>
        <CapabilityList
          items={[
            {
              label: 'Page viewer',
              detail: 'Renders stored documents; needs the document route and object storage.',
              state: 'pending',
              icon: 'records',
            },
            {
              label: 'Marking surface',
              detail: 'Assistants have no marking endpoint in this build.',
              state: 'blocked',
              icon: 'pen',
            },
            {
              label: 'Review notes',
              detail: 'Would be written to the engine against your account.',
              state: 'pending',
              icon: 'eye',
            },
          ]}
        />
      </Panel>

      <Panel title="A review, once marking exists" note="Four steps" index={1}>
        <StepList
          steps={[
            {
              title: 'Open from the queue',
              body: 'Work arrives through the shared queue, already filtered to your assignment.',
            },
            {
              title: 'Read the engine’s corrections',
              body: 'Each annotation would link back to the rule that produced it.',
            },
            {
              title: 'Confirm or flag',
              body: 'Your decision is recorded with your identity and a timestamp.',
            },
            {
              title: 'Hand back',
              body: 'The teacher sees the reviewed result in the gradebook, not a silent edit.',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="The marking workspace cannot open a script yet"
        capability="correction engine: assistant marking surface (not implemented)"
      >
        <p>
          Without stored documents and a mark endpoint there is nothing to render. The queue
          remains the place where work is picked up, so this page does not duplicate it with a
          second, fake list.
        </p>
      </StatePanel>

      <p className="panel-copy">
        Assigned work is listed in the queue.{' '}
        <Link className="panel-link" to="/queue">
          <Icon name="pulse" size={14} />
          Open submission queue
        </Link>
      </p>
    </div>
  )
}

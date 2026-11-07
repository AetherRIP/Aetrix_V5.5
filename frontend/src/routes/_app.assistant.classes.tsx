import { createFileRoute, Link } from '@tanstack/react-router'
import { EmptyTable, Panel } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/_app/assistant/classes')({
  component: AssistantClasses,
})

function AssistantClasses() {
  return (
    <div className="app-stack">
      <Panel title="Assigned classes" note="From your teacher" index={0}>
        <EmptyTable
          columns={['Class', 'Students', 'Assigned assignments', 'Open submissions']}
          caption="Classes assigned to this assistant"
          note="No classes assigned yet. Your teacher assigns a class; you cannot add one."
        />
      </Panel>

      <Panel title="What is in scope" note="Assignment, not workspace" index={1}>
        <ul className="rule-list">
          <li>You see the classes your teacher assigned to you, and no others.</li>
          <li>
            Other classes in the same workspace stay hidden — a workspace is shared, an
            assignment is personal.
          </li>
          <li>Students appear here only through the classes you were given.</li>
          <li>If an assignment is withdrawn, its records leave your view immediately.</li>
        </ul>
      </Panel>

      <StatePanel
        tone="wip"
        title="Class assignment is not implemented"
        capability="engine: workspace membership (not deployed)"
      >
        <p>
          The engine has no membership table and no route that returns “classes assigned to
          this reviewer”, so this page cannot be populated. Nothing is inferred from the
          teacher’s classes: that would widen your scope silently.
        </p>
      </StatePanel>

      <p className="panel-copy">
        Need another class? Ask your teacher — they own the assignment.{' '}
        <Link className="panel-link" to="/assistant">
          <Icon name="arrow" size={14} />
          Back to overview
        </Link>
      </p>
    </div>
  )
}

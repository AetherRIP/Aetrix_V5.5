import { createFileRoute, Link } from '@tanstack/react-router'
import { EmptyTable, Panel, StatsStrip } from '../components/app/PageBlocks'
import { StatePanel } from '../components/app/StatePanel'
import { Icon } from '../components/ui/Icons'

export const Route = createFileRoute('/_app/assistant/tasks')({
  component: AssistantTasks,
})

function AssistantTasks() {
  return (
    <div className="app-stack">
      <Panel title="Open tasks" note="Newest first" index={0}>
        <StatsStrip
          metrics={[
            { label: 'Open', note: 'awaits the engine' },
            { label: 'Due today' },
            { label: 'Blocked' },
            { label: 'Done this week' },
          ]}
        />
      </Panel>

      <Panel title="Task list" index={1} note="Assigned by your teacher">
        <EmptyTable
          columns={['Task', 'Class', 'Assignment', 'Assigned by', 'Due', 'Status']}
          caption="Tasks assigned to this assistant"
          note="No tasks — task assignment needs an engine route that does not exist yet."
        />
      </Panel>

      <Panel title="Rules" index={2} note="Fixed">
        <ul className="rule-list">
          <li>Tasks are created by the teacher; assistants cannot assign work to each other.</li>
          <li>A task points at a submission or a class, never at a whole workspace.</li>
          <li>Completing a task records your identity; it does not change a student’s grade.</li>
        </ul>
      </Panel>

      <StatePanel
        tone="wip"
        title="Tasks are a client-side concept only"
        capability="engine: tasks / assignments (not implemented)"
      >
        <p>
          There is no task table in the engine, so this list is empty by fact rather than by
          accident. Nothing is stored in the browser: a task kept in localStorage would
          disappear on another device and would not be visible to your teacher.
        </p>
      </StatePanel>

      <p className="panel-copy">
        Work already assigned to you appears in the queue.{' '}
        <Link className="panel-link" to="/queue">
          <Icon name="pulse" size={14} />
          Submission queue
        </Link>
      </p>
    </div>
  )
}

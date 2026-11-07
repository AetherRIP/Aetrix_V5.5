import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { EmptyTable, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/workspaces')({
  component: PlatformWorkspaces,
})

const COLUMNS = ['Workspace', 'Teacher', 'Assistants', 'Allocated classes', 'State'] as const

function PlatformWorkspaces() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="Workspace allocation is not served yet"
        capability="engine: no platform-level workspace endpoint"
      >
        <p>
          Every teacher gets an individual workspace, assistants belong to it, and a class
          may hold exactly one active allocation. Those rules belong in the engine, which
          currently exposes tenant-scoped routes only, so this table has no source.
        </p>
        <p>
          Allocation is an operator action. A teacher cannot move a class between
          workspaces, and this interface does not offer a way to try.
        </p>
      </StatePanel>

      <Panel title="Workspaces" note="Waiting on the engine">
        <EmptyTable
          columns={COLUMNS}
          caption="Teacher workspaces and their allocations"
          note="No rows — workspace records live in the engine, which has no public deployment."
        />
      </Panel>

      <Panel title="Allocation rules" note="Enforced by the engine">
        <ul className="rule-list">
          <li>One teacher owns one workspace.</li>
          <li>Assistants belong to a teacher’s workspace, not to the platform.</li>
          <li>A class has one active workspace allocation at a time.</li>
          <li>Only an operator may allocate or release a class.</li>
          <li>Cross-workspace reads are refused, and look nonexistent.</li>
        </ul>
      </Panel>
    </div>
  )
}

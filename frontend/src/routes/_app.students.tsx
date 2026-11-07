import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { EmptyTable, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/students')({
  component: Students,
})

function Students() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="Class rosters arrive with the Google Classroom connection"
        capability="engine: classes and students (tenant-scoped)"
      >
        <p>
          Classes are allocated to this workspace by a platform operator, and their students
          come from the Classroom roster. Both are engine records; this build has no route
          that returns them, so no class or student is listed here.
        </p>
      </StatePanel>

      <Panel title="Classes" note="Allocated to this workspace">
        <EmptyTable
          columns={['Class', 'Year group', 'Students', 'Allocation']}
          caption="Classes allocated to this workspace"
          note="No rows — allocation lives in the engine and is operator-controlled."
        />
      </Panel>

      <Panel title="Students" note="From the class roster">
        <EmptyTable
          columns={['Student', 'Class', 'Submissions', 'Last activity']}
          caption="Students in the allocated classes"
          note="No rows — rosters are not imported yet, and none are invented."
        />
      </Panel>
    </div>
  )
}

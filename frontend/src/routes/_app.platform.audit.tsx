import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { EmptyTable, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/audit')({
  component: PlatformAudit,
})

const COLUMNS = ['When', 'Actor', 'Action', 'Workspace', 'Subject'] as const

function PlatformAudit() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="The audit log is append-only and not yet readable here"
        capability="engine: audit_events (tenant-scoped)"
      >
        <p>
          The engine writes <code>audit_events</code>, <code>job_events</code> and{' '}
          <code>provider_usage</code> as append-only tables, so nothing in this interface can
          rewrite history. There is no platform-level read endpoint yet, and the screen does
          not fabricate entries to look complete.
        </p>
      </StatePanel>

      <Panel title="Security and audit events" note="Waiting on the engine">
        <EmptyTable
          columns={COLUMNS}
          caption="Append-only audit events across the platform"
          note="No rows — audit storage exists, the read route does not."
        />
      </Panel>

      <Panel title="What is recorded" note="Implemented in the engine">
        <ul className="rule-list">
          <li>Blueprint approvals and overrides, with the acting user.</li>
          <li>Job state transitions and every lease attempt.</li>
          <li>Provider calls, with fingerprints rather than credentials.</li>
          <li>Append-only at the database layer, not only in application code.</li>
        </ul>
      </Panel>
    </div>
  )
}

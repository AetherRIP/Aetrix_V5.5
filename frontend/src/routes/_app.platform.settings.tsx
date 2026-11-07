import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/settings')({
  component: PlatformSettings,
})

function PlatformSettings() {
  return (
    <div className="app-stack">
      <Panel title="Platform defaults" note="Not persisted yet">
        <ul className="rule-list">
          <li>Default workspace template for a new teacher workspace.</li>
          <li>Retention window for uploaded scripts.</li>
          <li>Which account types may open the audit view.</li>
        </ul>
        <p className="panel-copy">
          None of these is stored anywhere yet. The list is here so the decisions are visible
          rather than implied by defaults hidden in code.
        </p>
      </Panel>

      <StatePanel
        tone="wip"
        title="Platform settings have no storage"
        capability="engine: platform configuration (not implemented)"
      >
        <p>
          Settings would be written to the engine and applied to every workspace. No such
          table exists in the schema, so this screen is read-only prose and does not pretend
          a save succeeded.
        </p>
      </StatePanel>
    </div>
  )
}

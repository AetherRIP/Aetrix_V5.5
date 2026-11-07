import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, EmptyTable, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/users')({
  component: PlatformUsers,
})

const COLUMNS = ['Account', 'Email', 'Role', 'Workspace', 'Status'] as const

function PlatformUsers() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="Account management needs an admin surface"
        capability="engine: tenant-scoped users only"
      >
        <p>
          Accounts are created in Supabase and carry their role in{' '}
          <code>app_metadata.aetrix_role</code>, which only the identity provider can write.
          The engine records workspace membership, but it exposes no platform-level account
          list, and this repository holds no service-role key that could manage users
          directly — by design.
        </p>
      </StatePanel>

      <Panel title="Accounts" note="Waiting on the engine">
        <EmptyTable
          columns={COLUMNS}
          caption="Teachers, assistants and platform operators"
          note="No rows — there is no endpoint to list accounts across workspaces."
        />
      </Panel>

      <Panel title="Role assignment" note="Identity provider">
        <CapabilityList
          items={[
            {
              label: 'platform_operator',
              detail: 'Assigned in app_metadata; opens the platform area.',
              state: 'available',
              icon: 'shield',
            },
            {
              label: 'supervisor',
              detail: 'Assigned in app_metadata; opens one workspace.',
              state: 'available',
              icon: 'eye',
            },
            {
              label: 'assistant',
              detail: 'Assigned in app_metadata; opens assigned work only.',
              state: 'available',
              icon: 'pen',
            },
            {
              label: 'Self-service role change',
              detail: 'Never offered. user_metadata is writable by the account itself.',
              state: 'blocked',
              icon: 'lock',
            },
          ]}
        />
      </Panel>
    </div>
  )
}

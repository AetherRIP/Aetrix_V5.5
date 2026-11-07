import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/integrations')({
  component: PlatformIntegrations,
})

/**
 * The reserved slot for provider work. Quota monitoring is explicitly *not*
 * implemented, so the screen states the gap instead of drawing an empty chart.
 */
function PlatformIntegrations() {
  return (
    <div className="app-stack">
      <Panel title="Providers" note="One adapter today">
        <CapabilityList
          items={[
            {
              label: 'Gemini REST adapter',
              detail: 'Implemented behind the LLMProvider protocol; live calls UNVERIFIED.',
              state: 'available',
              icon: 'blueprint',
            },
            {
              label: 'Credential storage',
              detail: 'Encrypted at rest; only fingerprints and health are returned.',
              state: 'available',
              icon: 'lock',
            },
            {
              label: 'Quota and usage monitoring',
              detail: 'Not implemented. This page reserves the navigation slot for it.',
              state: 'pending',
              icon: 'chart',
            },
            {
              label: 'Provider switching',
              detail: 'No second adapter exists, so no switch is offered.',
              state: 'blocked',
              icon: 'eye',
            },
          ]}
        />
      </Panel>

      <Panel title="Gemini usage" note="Reserved">
        <p className="panel-copy">
          Usage and quota monitoring will live here: request counts, tokens consumed and
          remaining allowance per workspace. The engine already records append-only{' '}
          <code>provider_usage</code> rows, but no aggregation endpoint exists and no quota
          figures should be inferred from the interface.
        </p>
        <div className="reserved-slot" aria-hidden="true">
          <span className="reserved-slot__label mono">Quota monitor</span>
          <span className="reserved-slot__note">Reserved for a later release</span>
        </div>
      </Panel>

      <StatePanel
        tone="wip"
        title="Provider configuration is not exposed over HTTP"
        capability="engine: provider configuration (internal only)"
      >
        <p>
          Provider credentials are encrypted and never returned by the API. There is no
          endpoint that would let this screen read or rotate them, and adding one is an
          engine decision, not a frontend one.
        </p>
      </StatePanel>
    </div>
  )
}

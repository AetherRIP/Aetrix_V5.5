import { createFileRoute, Link } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/integrations')({
  component: PlatformIntegrations,
})

/**
 * The provider screen. Fleet quota monitoring now has a home of its own at
 * `/platform/gemini`; until the engine is hosted neither screen has figures, and
 * both say so instead of drawing an empty chart.
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
              detail:
                'Engine endpoints and the fleet screen exist; no deployment answers them yet.',
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

      <Panel title="Gemini usage" note="Platform operators">
        <p className="panel-copy">
          Request counts, tokens consumed and the estimated remaining allowance are managed per
          Google Cloud project on the Gemini fleet screen. Quota is never counted per key: keys in
          one project share one allowance. Every figure there is labelled confirmed, estimated or
          unknown, and nothing is inferred when no limit is known.
        </p>
        <Link to="/platform/gemini" className="btn btn--outline">
          Open the Gemini fleet
        </Link>
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

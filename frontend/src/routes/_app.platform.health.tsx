import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { CapabilityList, Panel, StatsStrip } from '../components/app/PageBlocks'

export const Route = createFileRoute('/_app/platform/health')({
  component: PlatformHealth,
})

/**
 * Health is the one area where a fact is known without the engine: the engine's
 * own health route exists in code (`app/api/health.py`), but nothing is deployed
 * to answer it. The screen says exactly that.
 */
function PlatformHealth() {
  return (
    <div className="app-stack">
      <Panel title="Service state" note="As far as this build can tell">
        <StatsStrip
          metrics={[
            { label: 'API', note: 'no deployment' },
            { label: 'Worker', note: 'no deployment' },
            { label: 'Database', note: 'not reachable from here' },
            { label: 'Provider', note: 'UNVERIFIED' },
          ]}
          source="deployment"
        />
      </Panel>

      <Panel title="Components" note="What each one needs">
        <CapabilityList
          items={[
            {
              label: 'HTTP API',
              detail: 'FastAPI app with /health; no public HTTPS host yet.',
              state: 'pending',
              icon: 'server',
            },
            {
              label: 'Worker',
              detail: 'Separate process, leases jobs with FOR UPDATE SKIP LOCKED.',
              state: 'pending',
              icon: 'pulse',
            },
            {
              label: 'PostgreSQL',
              detail: 'Supabase in development; RLS guard runs in CI.',
              state: 'pending',
              icon: 'records',
            },
            {
              label: 'AI provider',
              detail: 'Live Gemini responses are UNVERIFIED; no DRAFT exists.',
              state: 'pending',
              icon: 'blueprint',
            },
          ]}
        />
      </Panel>

      <StatePanel
        tone="wip"
        title="No health endpoint is reachable"
        capability="GET /health (engine, not deployed)"
      >
        <p>
          This screen cannot report uptime, queue depth or latency, because nothing is
          deployed to measure. It will read the engine’s own health route once the API is
          hosted.
        </p>
      </StatePanel>
    </div>
  )
}

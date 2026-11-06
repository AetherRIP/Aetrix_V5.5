import { createFileRoute } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { API_UNAVAILABLE_REASON } from '../lib/env'

export const Route = createFileRoute('/_app/workspace')({
  component: WorkspaceHub,
})

function WorkspaceHub() {
  return (
    <div className="app-stack">
      <StatePanel
        tone="wip"
        title="Workspace membership is served by the engine"
        capability="GET /api/v1/workspaces"
      >
        <p>{API_UNAVAILABLE_REASON}</p>
        <p>
          In Aetrix a workspace is a tenant: it owns exams, blueprints, submissions and
          every correction job beneath them. Membership and role are decided by the
          engine from your verified token — never by the browser — so this screen shows
          nothing until that endpoint answers.
        </p>
      </StatePanel>

      <section className="app-card" aria-labelledby="workspace-model-title">
        <h2 className="app-card__title" id="workspace-model-title">
          How the hub will behave
        </h2>
        <dl className="app-definitions">
          <div>
            <dt>Selection</dt>
            <dd>Choose a workspace; the choice scopes every screen in the shell.</dd>
          </div>
          <div>
            <dt>Role</dt>
            <dd>
              Owner, exam manager, marker or viewer. The engine returns the role with
              the workspace; the interface only renders what that role may do.
            </dd>
          </div>
          <div>
            <dt>Isolation</dt>
            <dd>
              Cross-workspace reads are rejected by row security and tenant-scoped
              queries, so a workspace can never enumerate another's records.
            </dd>
          </div>
        </dl>
      </section>
    </div>
  )
}

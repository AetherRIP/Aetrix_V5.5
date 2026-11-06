import { useState } from 'react'
import { createFileRoute, useRouter } from '@tanstack/react-router'
import { StatePanel } from '../components/app/StatePanel'
import { ThemeSwitch } from '../components/site/ThemeSwitch'
import { displayName, useAuth } from '../lib/auth/AuthProvider'
import { formatDateTime, providerLabel } from '../lib/format'

export const Route = createFileRoute('/_app/settings')({
  component: Settings,
})

function Settings() {
  const { user, session, signOut } = useAuth()
  const router = useRouter()
  const [signingOut, setSigningOut] = useState(false)

  const provider = user?.app_metadata?.provider as string | undefined
  const identity = user?.identities?.[0]

  return (
    <div className="app-stack">
      <section className="app-card" aria-labelledby="profile-title">
        <h2 className="app-card__title" id="profile-title">
          Profile
        </h2>
        <p className="app-card__body">
          Sourced from the verified Supabase session — this is live account data.
        </p>
        <dl className="app-definitions">
          <div>
            <dt>Name</dt>
            <dd>{displayName(user)}</dd>
          </div>
          <div>
            <dt>Email</dt>
            <dd className="mono">{user?.email ?? '—'}</dd>
          </div>
          <div>
            <dt>Sign-in provider</dt>
            <dd>{providerLabel(provider ?? identity?.provider)}</dd>
          </div>
          <div>
            <dt>Email verified</dt>
            <dd>{user?.email_confirmed_at ? formatDateTime(user.email_confirmed_at) : 'Not confirmed'}</dd>
          </div>
          <div>
            <dt>Account created</dt>
            <dd>{formatDateTime(user?.created_at)}</dd>
          </div>
          <div>
            <dt>This session started</dt>
            <dd>{formatDateTime(session?.user.last_sign_in_at)}</dd>
          </div>
          <div>
            <dt>User id</dt>
            <dd className="mono app-definitions__id">{user?.id ?? '—'}</dd>
          </div>
        </dl>
      </section>

      <div className="app-split">
        <section className="app-card" aria-labelledby="appearance-title">
          <h2 className="app-card__title" id="appearance-title">
            Appearance
          </h2>
          <p className="app-card__body">
            The theme applies to the marketing site and the application, and is stored
            in this browser.
          </p>
          <ThemeSwitch />
        </section>

        <section className="app-card" aria-labelledby="session-title">
          <h2 className="app-card__title" id="session-title">
            Session
          </h2>
          <p className="app-card__body">
            The session is stored locally, refreshed while it is in use, and revoked on
            sign-out. Signing out clears it on this device.
          </p>
          <button
            type="button"
            className="btn btn--outline btn--small"
            disabled={signingOut}
            onClick={() => {
              setSigningOut(true)
              void (async () => {
                await signOut()
                await router.navigate({ to: '/sign-in', replace: true })
              })()
            }}
          >
            {signingOut ? 'Signing out…' : 'Sign out'}
          </button>
        </section>
      </div>

      <StatePanel
        tone="wip"
        title="Workspace settings need the engine"
        capability="GET/PUT /api/v1/workspaces/{id}/settings"
      >
        <p>
          Roles, membership, marking policy and provider credentials belong to the
          workspace and are managed server-side. They are not configurable from this
          build, and role information from the browser is never treated as
          authorization.
        </p>
      </StatePanel>
    </div>
  )
}
